#!/usr/bin/env python3
"""
linear-sync.py — Importador ADITIVO de Linear al board de workitems.

Integracion EXTERNA al autopilot, espejo de azure-sync.py para otro tracker: el
autopilot no la conoce, solo usa la API publica del board (workitems.py del kit
instalado).

Cada issue de Linear se escribe como new/<tipo>-<team>_<numero>-<slug>.md, donde
tipo es bug si el issue tiene la label "Bug" (en cualquier mayuscula/minuscula),
si no task. "<team>_<numero>" (team.key en minusculas + Issue.number, p. ej.
"eng_123") es la clave del board y el nombre de la rama que el autopilot crea
desde la rama base del repo. Se usa ese id corto y no el identifier de Linear
("ENG-123") porque la clave del board no admite guiones.

FUENTE (linear-sync.env):
  LINEAR_TEAM=<team key>           (p. ej. ENG)
  LINEAR_REPO=<carpeta del repo>   (solo si el board es un workspace de varios repos)

Trae los issues del team en estado tipo backlog o unstarted (Linear agrupa sus
workflow states en esos "tipos" aunque cada equipo les haya puesto nombres
distintos). No filtra por ciclo/sprint: entra todo lo que este en esos dos tipos
de estado, sin importar el ciclo al que pertenezca.

GARANTIAS (identicas a azure-sync.py):
  - Solo AGREGA tareas nuevas. Nunca mueve, borra ni sobrescribe.
  - Dedup por "<team>_<numero>": si ya hay un archivo con esa clave en CUALQUIER
    estado del board, lo salta. (El numero es unico dentro del team en Linear.)
  - Es idempotente: correrlo N veces crea la tarea una sola vez.
  - Si Linear falla al traer la fuente, sale con codigo != 0 y NO toca el board.
  - La API key se lee del entorno o de linear-sync.secrets.env. NO se hardcodea y
    no se pasa por linea de comandos (no aparece en `ps`).

NOTA sobre la API de Linear: el filtro de issues por team (`team: { id: { eq } }`)
y la forma exacta de bajar archivos de uploads.linear.app (con o sin "Bearer" en
el header) no estan documentados con un ejemplo verbatim al momento de escribir
esto; se infirieron por analogia con lo que si esta documentado y se prueban en
tiempo de ejecucion (ver `descargar()`: reintenta con "Bearer" si falla sin el).
Corre primero con --dry-run: si algo no calza con tu cuenta, Linear devuelve un
error de GraphQL bien descriptivo en el campo "errors".

Linear desaconseja el polling de su API (recomienda webhooks). Si usas --watch,
usa un intervalo generoso (300s o mas): hay un limite de 2500 requests/hora por
API key.

Uso:
  python3 linear-sync.py --config <proyecto>/linear-sync.env
  python3 linear-sync.py --config <...> --watch 300
  python3 linear-sync.py --config <...> --dry-run
  python3 linear-sync.py --config <...> --status
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# El formato del board vive en el kit del autopilot (workitems.py); se busca en
# $AUTOPILOT_KIT, en el kit instalado o en el lib/ del repo (si se corre desde el repo).
KIT = os.environ.get("AUTOPILOT_KIT") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "autopilot-kit")
for d in (KIT, os.path.join(SCRIPT_DIR, "..", "..", "lib")):  # el ultimo insertado gana
    if os.path.exists(os.path.join(d, "workitems.py")):
        sys.path.insert(0, os.path.abspath(d))
try:
    import workitems as wi
except ImportError:
    print(json.dumps({"action": "error",
                      "message": "no encuentro workitems.py del autopilot (busque en %s)" % KIT,
                      "hint": "instala el kit con install.sh o exporta AUTOPILOT_KIT"}, ensure_ascii=False, indent=2))
    sys.exit(2)

GRAPHQL_URL = "https://api.linear.app/graphql"
# Prioridad de Linear (0=sin prioridad, 1=Urgent .. 4=Low) -> board
PRIO_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
PRIO_DEFAULT = "Medium"
STATE_TYPES = ("backlog", "unstarted")  # "tipos" de workflow state que se importan

CFG = {"key": "", "fuente": None}
BOARD = None  # wi.Board, se arma en main()


# ----------------------------------------------------------------- config
def leer_env(path):
    vals = {}
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip("'\"")
    return vals


def load_config(path):
    """Carga linear-sync.env (team + repo opcional) y la API key (entorno > secrets.env)."""
    if not os.path.exists(path):
        die("No existe el archivo de config: %s" % path,
            "Copia linear-sync.env.example de la integracion a la raiz del proyecto")
    vals = leer_env(path)
    team = vals.get("LINEAR_TEAM", "").strip()
    if team:
        CFG["fuente"] = {"repo": vals.get("LINEAR_REPO", "").strip(), "team_key": team}

    secrets = path[:-4] + ".secrets.env" if path.endswith(".env") else path + ".secrets"
    for origen in (os.environ, leer_env(secrets) if os.path.exists(secrets) else {}):
        if origen.get("LINEAR_API_KEY"):
            CFG["key"] = origen["LINEAR_API_KEY"]
            break


def die(msg, hint=None, code=2):
    out = {"action": "error", "message": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(code)


# ----------------------------------------------------------------- linear (graphql)
def curl_conf(headers):
    return "".join('header = "%s"\n' % h.replace('"', '\\"') for h in headers)


def graphql(query, variables=None):
    """POST a la API de Linear. La API key va por stdin (-K -), nunca en argv (no aparece en `ps`)."""
    conf = curl_conf(["Authorization: %s" % CFG["key"], "Content-Type: application/json"])
    body = json.dumps({"query": query, "variables": variables or {}})
    r = subprocess.run(["curl", "-sS", "-K", "-", "-X", "POST", "-d", body, GRAPHQL_URL],
                       input=conf, capture_output=True, text=True)
    if r.returncode != 0:
        die("curl fallo contactando Linear: %s" % r.stderr.strip()[:200])
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Linear devolvio algo que no es JSON (API key invalida?): %s" % r.stdout[:200])
    if d.get("errors"):
        msg = "; ".join(e.get("message", "") for e in d["errors"])
        if any(e.get("extensions", {}).get("code") == "RATELIMITED" for e in d["errors"]):
            die("Linear: limite de requests alcanzado, reintenta mas tarde (%s)" % msg[:200])
        die("Linear devolvio un error de GraphQL: %s" % msg[:300])
    return d.get("data") or {}


TEAMS_Q = "query { teams { nodes { id key name } } }"


def resolver_team(team_key):
    data = graphql(TEAMS_Q)
    for t in data.get("teams", {}).get("nodes", []):
        if t["key"].lower() == team_key.lower():
            return t["id"]
    die("No existe el team '%s' en Linear (o la API key no tiene acceso)" % team_key,
        "Revisa LINEAR_TEAM en la config: debe ser la 'key' corta del team (ej. ENG), no su nombre")


ISSUES_Q = """
query Issues($teamId: ID!, $stateType: String!, $after: String) {
  issues(first: 50, after: $after,
         filter: { team: { id: { eq: $teamId } }, state: { type: { eq: $stateType } } }) {
    nodes { id number }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def fetch_new_issues(team_id):
    """[(issue_id, numero)] de issues en backlog o unstarted del team."""
    out = []
    for stype in STATE_TYPES:
        after = None
        while True:
            data = graphql(ISSUES_Q, {"teamId": team_id, "stateType": stype, "after": after})
            page = data.get("issues", {})
            out += [(n["id"], n["number"]) for n in page.get("nodes", [])]
            info = page.get("pageInfo", {})
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
    return out


ALL_ISSUES_Q = """
query AllIssues($teamId: ID!, $after: String) {
  issues(first: 100, after: $after, filter: { team: { id: { eq: $teamId } } }) {
    nodes { id number }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def resolver_issue_id(team_id, numero):
    """Busca el id (uuid) de un issue por su numero, sin depender del tipo de estado actual
    (lo necesita --refrescar para tareas que en Linear ya avanzaron de backlog/unstarted)."""
    after = None
    while True:
        data = graphql(ALL_ISSUES_Q, {"teamId": team_id, "after": after})
        page = data.get("issues", {})
        for n in page.get("nodes", []):
            if n["number"] == numero:
                return n["id"]
        info = page.get("pageInfo", {})
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    raise RuntimeError("no encuentro el issue numero %s en Linear" % numero)


ISSUE_Q = """
query IssueDetail($id: ID!) {
  issue(id: $id) {
    id number identifier title description priority url createdAt
    state { name type }
    team { key name }
    labels { nodes { name } }
    attachments { nodes { id title url } }
  }
}
"""


def fetch_detail(issue_id):
    return graphql(ISSUE_Q, {"id": issue_id})["issue"]


# ----------------------------------------------------------------- adjuntos
IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"}
EXT_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
            "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
MAX_BYTES = 50 * 1024 * 1024
MAX_FOTOGRAMAS = 12
IMG_MD = re.compile(r"!\[([^\]]*)\]\((https://[^)\s]+)\)")


def _es_host_linear(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return host == "linear.app" or host.endswith(".linear.app")


def descargar(url, destino):
    """Descarga binaria. El header Authorization SOLO se manda a hosts *.linear.app: los
    adjuntos externos (Attachment de Linear) pueden apuntar a Figma, GitHub, Sentry, etc.,
    y ahi la API key nunca se envia. Para uploads.linear.app no esta documentado si hace
    falta el prefijo "Bearer": se prueba sin el primero y, si da 401, se reintenta con el."""
    def intento(auth):
        cmd = ["curl", "-sS", "-L", "--max-filesize", str(MAX_BYTES), "-o", destino,
              "-w", "%{http_code} %{content_type}"]
        if auth:
            cmd += ["-K", "-"]
        cmd.append(url)
        conf = curl_conf(["Authorization: %s" % auth]) if auth else None
        return subprocess.run(cmd, input=conf, capture_output=True, text=True)

    auth = CFG["key"] if _es_host_linear(url) else None
    r = intento(auth)
    code, _, ctype = r.stdout.strip().partition(" ")
    if code == "401" and auth:
        r = intento("Bearer %s" % CFG["key"])
        code, _, ctype = r.stdout.strip().partition(" ")
    if r.returncode == 63:
        return False, "no descargado: supera %d MB" % (MAX_BYTES // 1048576)
    if r.returncode != 0 or code != "200":
        if os.path.exists(destino):
            os.remove(destino)
        return False, "no descargado: HTTP %s %s" % (code, r.stderr.strip()[:80])
    return True, ctype.split(";")[0].strip()


def nombre_seguro(n):
    base, ext = os.path.splitext(os.path.basename(n or "adjunto"))
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:60] or "adjunto") + ext.lower()


def fotogramas(video, carpeta):
    """Fotogramas de un video para que el modelo lo 'vea'. Devuelve (lista, nota)."""
    if not shutil.which("ffmpeg"):
        return [], "sin fotogramas: instala ffmpeg (sudo apt install ffmpeg) y corre linear-sync --fotogramas"
    os.makedirs(carpeta, exist_ok=True)
    escala = "scale='min(1280,iw)':-2"
    with tempfile.TemporaryDirectory() as tmp:
        # 1) primer fotograma + cambios de escena (hasta 60), 2) se eligen 12 repartidos
        subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf",
                        "select='eq(n,0)+gt(scene,0.25)',%s" % escala, "-vsync", "vfr",
                        "-frames:v", "60", os.path.join(tmp, "s%03d.png")], capture_output=True)
        cand = sorted(os.listdir(tmp))
        if len(cand) < 3:  # video con pocos cambios: intervalo fijo
            for c in cand:
                os.remove(os.path.join(tmp, c))
            dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", video], capture_output=True, text=True).stdout.strip()
            try:
                fps = "%.4f" % (8 / max(float(dur), 1))
            except ValueError:
                fps = "0.5"
            subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", "fps=%s,%s" % (fps, escala),
                            "-frames:v", str(MAX_FOTOGRAMAS), os.path.join(tmp, "s%03d.png")],
                           capture_output=True)
            cand = sorted(os.listdir(tmp))
        if not cand:
            return [], "sin fotogramas: ffmpeg no pudo leer el video"
        if len(cand) > MAX_FOTOGRAMAS:
            paso = (len(cand) - 1) / (MAX_FOTOGRAMAS - 1)
            cand = [cand[round(i * paso)] for i in range(MAX_FOTOGRAMAS)]
        out = []
        for i, c in enumerate(cand, 1):
            dst = os.path.join(carpeta, "f%02d.png" % i)
            shutil.move(os.path.join(tmp, c), dst)
            out.append(dst)
    return out, "%d fotogramas en orden temporal" % len(out)


def imagenes_embebidas(desc):
    """[(url, nombre)] de las imagenes ![alt](url) de la descripcion que son de Linear
    (uploads.linear.app): las unicas a las que se les manda la API key al descargar."""
    out = []
    for alt, url in IMG_MD.findall(desc or ""):
        if _es_host_linear(url):
            nombre = alt.strip() or os.path.basename(urllib.parse.urlparse(url).path) or "imagen.png"
            out.append((url, nombre))
    return out


def descargar_adjuntos(item, clave):
    """Baja todo a <board>/adjuntos/<clave>/. Devuelve (url->ruta de imagenes embebidas,
    seccion md, fallidos)."""
    carpeta = os.path.join(BOARD.dir, "adjuntos", clave)
    rel = lambda p: "../adjuntos/%s/%s" % (clave, os.path.relpath(p, carpeta))
    embebidas = imagenes_embebidas(item.get("description") or "")
    urls_embebidas = {u for u, _ in embebidas}
    externos = [(a["url"], a.get("title") or "adjunto")
                for a in (item.get("attachments") or {}).get("nodes", [])]

    lista, vistos = [], set()
    for url, nombre in embebidas + externos:
        base = url.split("?")[0]
        if base in vistos:
            continue
        vistos.add(base)
        lista.append((url, nombre))
    if lista:
        os.makedirs(carpeta, exist_ok=True)

    por_url, lineas, fallidos = {}, [], []
    for n, (url, nombre) in enumerate(lista, 1):
        nombre = nombre_seguro(nombre)
        destino = os.path.join(carpeta, "%02d-%s" % (n, nombre))
        if os.path.isfile(destino) and os.path.getsize(destino) > 0:
            ok, info = True, ""  # ya descargado (p. ej. al refrescar): no se vuelve a bajar
        else:
            ok, info = descargar(url, destino)
        if not ok:
            lineas.append("- `%s` — %s" % (nombre, info))
            fallidos.append({"archivo": nombre, "motivo": info})
            continue
        ext = os.path.splitext(destino)[1]
        if ext not in IMAGEN | VIDEO and info in EXT_MIME:  # sin extension util: por Content-Type
            os.rename(destino, destino + EXT_MIME[info])
            destino, ext = destino + EXT_MIME[info], EXT_MIME[info]
        if url in urls_embebidas:
            por_url[url] = rel(destino)
        if ext in VIDEO:
            _, nota = fotogramas(destino, os.path.splitext(destino)[0] + ".frames")
            lineas.append("- 🎞️ Video [`%s`](%s) — %s" % (os.path.basename(destino), rel(destino), nota))
        elif ext in IMAGEN:
            lineas.append("- 📷 %s" % os.path.basename(destino))
        else:
            lineas.append("- [`%s`](%s)" % (os.path.basename(destino), rel(destino)))
    return por_url, "\n".join(lineas), fallidos


def reemplazar_imagenes(desc, por_url):
    """![alt](url de Linear) -> '📷 <archivo> — imagen N' en su lugar (referenciada, no
    incrustada). Una imagen que no sea de Linear (enlazada desde afuera) se deja intacta."""
    contador = [0]

    def rep(m):
        url = m.group(2)
        if url not in por_url and not _es_host_linear(url):
            return m.group(0)
        contador[0] += 1
        ruta = por_url.get(url)
        if not ruta:
            return "[imagen %d no descargada]" % contador[0]
        return "\n\n📷 %s — imagen %d\n\n" % (ruta.rsplit("/", 1)[-1], contador[0])

    txt = IMG_MD.sub(rep, desc or "")
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


# ----------------------------------------------------------------- board
def tipo_de(labels):
    """Label 'Bug' (cualquier mayuscula/minuscula) -> bug; todo lo demas -> task."""
    return "bug" if any((l.get("name") or "").strip().lower() == "bug" for l in labels) else "task"


def clave_de(fuente, numero):
    return "%s_%d" % (fuente["team_key"].lower(), numero)


# ----------------------------------------------------------------- sync
def recolectar():
    """[(fuente, issue_id, numero)]. Si Linear falla, die() antes de tocar el board."""
    f = CFG["fuente"]
    f["team_id"] = resolver_team(f["team_key"])
    return [(f, iid, numero) for iid, numero in fetch_new_issues(f["team_id"])]


def one_pass(dry_run=False):
    pendientes = recolectar()
    if not pendientes:
        return {"action": "no-op", "added": [], "skipped": [],
                "message": "Linear sin issues backlog/unstarted en el team configurado"}

    already = BOARD.numeros()
    added, skipped, errors = [], [], []

    for fuente, issue_id, numero in pendientes:
        key = clave_de(fuente, numero)
        donde = fuente["repo"] or fuente["team_key"]
        if key in already:
            skipped.append({"numero": numero, "repo": donde, "reason": "ya en el board (id %s)" % key})
            continue
        try:
            item = fetch_detail(issue_id)
        except SystemExit:
            raise
        except Exception as e:
            errors.append({"numero": numero, "error": str(e)[:200]})
            continue

        title = item.get("title") or "Issue #%d" % numero
        prio = PRIO_MAP.get(item.get("priority"), PRIO_DEFAULT)
        tipo = tipo_de((item.get("labels") or {}).get("nodes", []))

        if dry_run:
            embebidas = imagenes_embebidas(item.get("description") or "")
            adjs = (item.get("attachments") or {}).get("nodes", [])
            added.append({"numero": numero, "clave": "%s-%s" % (tipo, key), "repo": donde, "title": title,
                          "prioridad": prio, "imagenes": len(embebidas), "adjuntos": len(adjs)})
            already.add(key)  # evita duplicados en la misma pasada
            continue

        # Adjuntos ANTES de crear la tarea: el .md nace completo (linear-sync nunca lo reescribe).
        por_url, seccion, fallidos = descargar_adjuntos(item, key)
        desc = reemplazar_imagenes(item.get("description") or "", por_url)
        try:
            path = BOARD.crear(tipo, key, prio, title, desc, "_Sin criterio en Linear._",
                               repo=fuente["repo"], origen="linear:%s" % fuente["team_key"],
                               adjuntos=seccion)
        except wi.Error as e:
            errors.append({"numero": numero, "error": str(e)[:200]})
        else:
            entrada = {"numero": numero, "clave": "%s-%s" % (tipo, key), "repo": donde, "title": title,
                      "archivo": path}
            if fallidos:
                entrada["adjuntos_fallidos"] = fallidos
            added.append(entrada)
            already.add(key)

    action = "dry-run" if dry_run else ("added" if added else ("partial" if errors else "no-op"))
    result = {"action": action, "added": added, "skipped": skipped, "errors": errors}

    if added and not dry_run:
        BOARD.log("linear-sync importo tareas", "sistema", "deteccion",
                  ", ".join(a["clave"] for a in added[:5]), "-", "-",
                  "Importadas %d tarea(s) de Linear: %s" % (
                      len(added), ", ".join("%s (%s)" % (a["numero"], a["repo"]) for a in added)))
        BOARD.avisar("📥 %d tarea(s) nueva(s) de Linear:\n%s" % (
            len(added), "\n".join("- %s — %s" % (a["clave"], a["title"][:80]) for a in added[:15])))
    return result


def do_refrescar(claves):
    """Vuelve a traer de Linear la descripcion y los adjuntos de tareas YA importadas y
    reescribe solo esas secciones. No cambia el estado ni toca notas, reporte, feedback ni
    resultado. Sin claves: todas las de Linear. Encuentra el issue por numero (no por su
    estado actual en Linear), asi sigue funcionando aunque ya haya avanzado de columna."""
    hechas, errores = [], []
    cache_team = {}
    for t in BOARD.todas():
        origen = t.get("origen") or ""
        if not origen.startswith("linear:") or (claves and t["id"] not in claves and t["numero"] not in claves):
            continue
        team_key = origen.split(":", 1)[1]
        try:
            if team_key not in cache_team:
                cache_team[team_key] = resolver_team(team_key)
            numero = int(t["numero"].rsplit("_", 1)[-1])
            issue_id = resolver_issue_id(cache_team[team_key], numero)
            item = fetch_detail(issue_id)
            por_url, seccion, fallidos = descargar_adjuntos(item, t["id"])
            desc = reemplazar_imagenes(item.get("description") or "", por_url)
            BOARD.modificar(t["id"], secs_set={
                "Descripción": desc or "-",
                "Adjuntos": seccion or "_Ninguno. Podés dejar imágenes en adjuntos/%s/._" % t["id"]})
            hechas.append({"tarea": t["id"], "estado": t["estado"], "adjuntos_fallidos": fallidos})
        except SystemExit:
            raise
        except Exception as e:
            errores.append({"tarea": t["id"], "error": str(e)[:200]})
    if hechas:
        BOARD.log("linear-sync refresco tareas", "sistema", "nota", ", ".join(h["tarea"] for h in hechas[:5]), "-", "-",
                  "Descripcion y adjuntos actualizados desde Linear: %d tarea(s)" % len(hechas))
    print(json.dumps({"action": "refrescar", "refrescadas": hechas, "errores": errores}, ensure_ascii=False, indent=2))
    return 0 if not errores else 1


def do_fotogramas():
    """Extrae fotogramas de los videos ya descargados que todavia no los tienen (tras instalar ffmpeg).
    Solo escribe en adjuntos/<clave>/<video>.frames/: no toca los .md (el agente los ve igual)."""
    if not shutil.which("ffmpeg"):
        die("ffmpeg no esta instalado", "sudo apt install ffmpeg")
    hechos = []
    for raiz, _, files in os.walk(os.path.join(BOARD.dir, "adjuntos")):
        for f in sorted(files):
            video = os.path.join(raiz, f)
            carpeta = os.path.splitext(video)[0] + ".frames"
            if os.path.splitext(f)[1].lower() in VIDEO and not os.path.isdir(carpeta):
                frames, nota = fotogramas(video, carpeta)
                hechos.append({"video": os.path.relpath(video, BOARD.dir), "resultado": nota})
    print(json.dumps({"action": "fotogramas", "videos": hechos}, ensure_ascii=False, indent=2))
    return 0


def do_status():
    already = BOARD.numeros()
    f = CFG["fuente"]
    team_id = resolver_team(f["team_key"])
    ids = fetch_new_issues(team_id)
    claves = [clave_de(f, numero) for _, numero in ids]
    nuevos = [c for c in claves if c not in already]
    fuentes = [{"repo": f["repo"] or "-", "team": f["team_key"],
               "linear_count": len(ids), "already_in_board": len(ids) - len(nuevos),
               "pending_import": len(nuevos), "pending_ids": nuevos[:20]}]
    print(json.dumps({"action": "status", "fuentes": fuentes}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ruta a linear-sync.env")
    ap.add_argument("--watch", type=int, metavar="SEG",
                    help="bucle cada N segundos (Linear desaconseja polling seguido: 300+ recomendado)")
    ap.add_argument("--dry-run", action="store_true", help="muestra que haria sin escribir")
    ap.add_argument("--status", action="store_true", help="solo diagnostico")
    ap.add_argument("--refrescar", nargs="*", metavar="CLAVE",
                    help="re-trae descripcion/adjuntos de tareas ya importadas (sin claves: todas)")
    ap.add_argument("--fotogramas", action="store_true",
                    help="extrae fotogramas de videos ya descargados (tras instalar ffmpeg)")
    args = ap.parse_args()

    load_config(args.config)

    if not CFG["fuente"]:
        die("Falta LINEAR_TEAM en %s" % args.config,
            "Formato: LINEAR_TEAM=<team key> (y LINEAR_REPO=<carpeta> si el board es un workspace)")
    if not CFG["key"]:
        die("Falta LINEAR_API_KEY", "Ponela en el entorno o en linear-sync.secrets.env (junto al config)")

    global BOARD
    try:
        # El board lo define autopilot.env (misma carpeta): de ahi salen tambien los repos.
        env_ap = os.path.join(os.path.dirname(os.path.abspath(args.config)), "autopilot.env")
        BOARD = wi.Board(wi.cargar_config(env_ap if os.path.exists(env_ap) else args.config))
    except wi.Error as e:
        die(str(e))
    if not args.dry_run and not args.status and not os.path.isdir(BOARD.dir):
        die("No existe el board %s" % BOARD.dir, "Crealo con /autopilot-init")
    if BOARD.cfg["workspace"]:
        repo = CFG["fuente"]["repo"]
        if not repo:
            die("El board es un workspace: agrega LINEAR_REPO=<carpeta> en %s" % args.config)
        if repo not in BOARD.cfg["repos"]:
            die("LINEAR_REPO=%s no tiene su REPO.%s en autopilot.env" % (repo, repo),
                "Declara el repo en autopilot.env")

    if args.status:
        return do_status()
    if args.refrescar is not None:
        return do_refrescar([c.lower() for c in args.refrescar])
    if args.fotogramas:
        return do_fotogramas()

    if args.watch:
        print("linear-sync en modo watch cada %ds. Ctrl+C para salir." % args.watch, flush=True)
        while True:
            try:
                r = one_pass()
                if r.get("added") or r.get("errors"):
                    print(json.dumps(r, ensure_ascii=False), flush=True)
            except SystemExit:
                raise
            except Exception as e:
                print(json.dumps({"action": "error", "message": str(e)[:300]}), flush=True)
            time.sleep(args.watch)

    r = one_pass(dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if not r.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
