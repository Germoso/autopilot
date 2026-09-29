#!/usr/bin/env python3
"""
azure-sync.py — Importador ADITIVO de Azure DevOps al board de workitems.

COPIA aditiva de /home/user/sync_workitems.py, adaptada para alimentar
el board de carpetas + Markdown del autopilot (workitems.py, misma carpeta).

Cada Work Item se escribe como new/<tipo>-<numero>-<slug>.md, donde tipo es
task o bug segun System.WorkItemType. <tipo>-<numero> es tambien el nombre de
la rama que el autopilot crea desde la rama base del repo.

FUENTES (azure-sync.env):
  Un repo:    AZURE_PROJECT=<proyecto>  AZURE_ITERATION=<sprint>
  Workspace:  SYNC.<carpeta del repo>=<proyecto>|<sprint>   (una linea por repo)
              La tarea se crea con repo: <carpeta>, asi el autopilot sabe en que
              repo crear la rama.
  <sprint> es la ruta de la iteracion (Proyecto\\Sprint X) o @current, que usa el
  sprint actual del equipo por defecto (<Proyecto> Team); @current:<Equipo> para otro.

GARANTIAS (identicas a las del original):
  - Solo AGREGA tareas nuevas. Nunca mueve, borra ni sobrescribe.
  - Dedup por numero: si ya hay un archivo *-<numero>-*.md en CUALQUIER
    estado del board, lo salta. (Los IDs son unicos en toda la organizacion.)
  - Es idempotente: correrlo N veces crea la tarea una sola vez.
  - Si Azure falla en CUALQUIER fuente, sale con codigo != 0 y NO toca el board.
  - El PAT se lee del entorno, de azure-sync.secrets.env o del de ado-mcp.
    NO se hardcodea y no se pasa por linea de comandos (no aparece en `ps`).

El script ORIGINAL (/home/user/sync_workitems.py) NO se modifica.

Uso:
  python3 azure-sync.py --config <proyecto>/azure-sync.env
  python3 azure-sync.py --config <...> --watch 60
  python3 azure-sync.py --config <...> --dry-run
  python3 azure-sync.py --config <...> --status
"""
import argparse
import html
import shutil
import tempfile
from html.parser import HTMLParser
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# El formato del board vive en un solo lugar: workitems.py, en esta misma carpeta.
sys.path.insert(0, SCRIPT_DIR)
try:
    import workitems as wi
except ImportError:
    print(json.dumps({"action": "error",
                      "message": "no encuentro workitems.py junto a azure-sync.py",
                      "hint": "reinstala el kit con install.sh"}, ensure_ascii=False, indent=2))
    sys.exit(2)

# Prioridad de Azure (1=alta) -> board
PRIO_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
PRIO_DEFAULT = "Medium"
PAT_MCP = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                       "autopilot-kit", "ado-mcp.secrets.env")

CFG = {"org": "", "user": "", "pat": "", "fuentes": []}
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
    """Carga azure-sync.env, las fuentes y el PAT (entorno > secrets.env > PAT del MCP)."""
    if not os.path.exists(path):
        die("No existe el archivo de config: %s" % path, "Crealo con /autopilot-init o install.sh --init")
    vals = leer_env(path)
    CFG["org"] = vals.get("AZURE_ORG", "")
    CFG["user"] = vals.get("AZURE_USER", "") or "pat"

    fuentes = []
    for k, v in sorted(vals.items()):
        if k.startswith("SYNC.") and k[5:]:
            proyecto, _, iteracion = v.partition("|")
            fuentes.append({"repo": k[5:], "project": proyecto.strip(), "iteration": iteracion.strip()})
    if not fuentes and vals.get("AZURE_PROJECT"):
        fuentes.append({"repo": "", "project": vals["AZURE_PROJECT"], "iteration": vals.get("AZURE_ITERATION", "")})
    CFG["fuentes"] = fuentes

    secrets = path[:-4] + ".secrets.env" if path.endswith(".env") else path + ".secrets"
    for origen in (os.environ, leer_env(secrets) if os.path.exists(secrets) else {},
                   leer_env(PAT_MCP) if os.path.exists(PAT_MCP) else {}):
        if origen.get("AZURE_DEVOPS_PAT"):
            CFG["pat"] = origen["AZURE_DEVOPS_PAT"]
            break


def die(msg, hint=None, code=2):
    out = {"action": "error", "message": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(code)


# ----------------------------------------------------------------- azure
def curl(url, data=None):
    """curl con las credenciales por stdin (-K -): el PAT nunca va en argv."""
    conf = 'user = "%s:%s"\n' % (CFG["user"], CFG["pat"].replace('"', '\\"'))
    cmd = ["curl", "-sS", "-K", "-", url]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(data)]
    r = subprocess.run(cmd, input=conf, capture_output=True, text=True)
    if r.returncode != 0:
        die("curl fallo contactando Azure: %s" % r.stderr.strip()[:200])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Azure devolvio algo que no es JSON (PAT invalido o sin permisos?): %s" % r.stdout[:200])


def base_url(project, team=None):
    parts = [CFG["org"], urllib.parse.quote(project)] + ([urllib.parse.quote(team)] if team else [])
    return "https://dev.azure.com/" + "/".join(parts)


class _HtmlAMd(HTMLParser):
    """HTML de Azure -> Markdown simple: conserva parrafos, listas, encabezados e imagenes.

    Las <img> se reemplazan por un marcador \\x00IMG<n>\\x00 y su src se agrega a `imagenes`
    (compartida entre campos: la numeracion es continua en toda la tarea).
    """
    BLOQUES = {"p", "div", "tr", "table", "blockquote", "pre"}

    def __init__(self, imagenes):
        super().__init__(convert_charrefs=True)
        self.out, self.listas, self.imagenes = [], [], imagenes
        self.tras_vineta = False   # recien se escribio "1. " o "- ": un <p> no debe cortar la linea
        self.titulo = None         # indice en out donde empezo un <hN>

    def salto(self, n):
        cola = "".join(self.out[-4:])
        falta = n - (len(cola) - len(cola.rstrip("\n")))
        if self.out and falta > 0:
            self.out.append("\n" * falta)

    def bloque(self):
        if not self.tras_vineta:
            self.salto(1 if self.listas else 2)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "br":
            self.out.append("\n")
        elif tag in self.BLOQUES:
            self.bloque()
        elif tag in ("ul", "ol"):
            self.salto(1 if self.listas else 2)
            self.listas.append([tag, 0])
        elif tag == "li":
            self.salto(1)
            if self.listas and self.listas[-1][0] == "ol":
                self.listas[-1][1] += 1
                vineta = "%d. " % self.listas[-1][1]
            else:
                vineta = "- "
            self.out.append("  " * max(len(self.listas) - 1, 0) + vineta)
            self.tras_vineta = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.salto(2)
            self.titulo = len(self.out)
        elif tag == "img" and a.get("src"):
            src = html.unescape(a["src"])
            if src not in self.imagenes:
                self.imagenes.append(src)
            self.out.append("\x00IMG%d\x00" % self.imagenes.index(src))
            self.tras_vineta = False

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag) and self.titulo is not None:
            texto = "".join(self.out[self.titulo:]).strip()
            del self.out[self.titulo:]
            self.titulo = None
            if texto:
                self.out.append("**%s**" % texto)
            self.salto(1)
        elif tag in ("ul", "ol"):
            if self.listas:
                self.listas.pop()
            self.salto(1 if self.listas else 2)
        elif tag == "li":
            self.tras_vineta = False
        elif tag in self.BLOQUES:
            self.bloque()

    def handle_data(self, data):
        t = re.sub(r"[ \t\r\n\xa0]+", " ", data)
        if self.tras_vineta or (self.out and self.out[-1].endswith("\n")):
            t = t.lstrip()
        if t:
            self.out.append(t)
            self.tras_vineta = False


def html_a_md(t, imagenes):
    """HTML -> Markdown legible. `imagenes` acumula los src de las <img> (ver _HtmlAMd)."""
    if not t:
        return ""
    p = _HtmlAMd(imagenes)
    p.feed(t)
    p.close()
    txt = "\n".join(l.rstrip() for l in "".join(p.out).split("\n"))
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return re.sub(r"^\**ℹ️\s*Descripción\s*\**\s*", "", txt)


# ----------------------------------------------------------------- adjuntos
IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"}
EXT_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
            "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
MAX_BYTES = 50 * 1024 * 1024
MAX_FOTOGRAMAS = 12


def descargar(url, destino):
    """Descarga binaria con el PAT por stdin. Devuelve (ok, content_type o motivo)."""
    conf = 'user = "%s:%s"\n' % (CFG["user"], CFG["pat"].replace('"', '\\"'))
    sep = "&" if "?" in url else "?"
    r = subprocess.run(["curl", "-sS", "-L", "-K", "-", "--max-filesize", str(MAX_BYTES),
                        "-o", destino, "-w", "%{http_code} %{content_type}",
                        url + sep + "download=true&api-version=7.1"],
                       input=conf, capture_output=True, text=True)
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
        return [], "sin fotogramas: instala ffmpeg (sudo apt install ffmpeg) y corre azure-sync --fotogramas"
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


def adjuntos_de(item, imagenes):
    """[(url, nombre, origen)] de imagenes incrustadas + adjuntos del work item (sin repetir)."""
    out, vistos = [], set()
    for i, src in enumerate(imagenes):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)
        out.append((src, (q.get("fileName") or ["imagen%d.png" % (i + 1)])[0], "img%d" % i))
        vistos.add(src.split("?")[0])
    for r in item.get("relations") or []:
        if r.get("rel") == "AttachedFile" and r["url"].split("?")[0] not in vistos:
            out.append((r["url"], r.get("attributes", {}).get("name") or "adjunto", "rel"))
            vistos.add(r["url"].split("?")[0])
    return out


def descargar_adjuntos(item, clave, imagenes):
    """Baja todo a <board>/adjuntos/<clave>/. Devuelve (rutas de img por indice, seccion md, fallidos)."""
    carpeta = os.path.join(BOARD.dir, "adjuntos", clave)
    rel = lambda p: "../adjuntos/%s/%s" % (clave, os.path.relpath(p, carpeta))
    por_img, lineas, fallidos = {}, [], []
    lista = adjuntos_de(item, imagenes)
    if lista:
        os.makedirs(carpeta, exist_ok=True)
    for n, (url, nombre, origen) in enumerate(lista, 1):
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
        if origen.startswith("img"):
            por_img[int(origen[3:])] = rel(destino)
        if ext in VIDEO:
            frames, nota = fotogramas(destino, os.path.splitext(destino)[0] + ".frames")
            lineas.append("- Video [`%s`](%s) — %s" % (os.path.basename(destino), rel(destino), nota))
            lineas += ["  - ![%s](%s)" % (os.path.basename(f), rel(f)) for f in frames]
        elif ext in IMAGEN:
            lineas.append("- ![%s](%s)" % (os.path.basename(destino), rel(destino)))
        else:
            lineas.append("- [`%s`](%s)" % (os.path.basename(destino), rel(destino)))
    return por_img, "\n".join(lineas), fallidos


def poner_imagenes(txt, por_img):
    """Marcadores de imagen -> ![imagen N](ruta) en su lugar, cada una en su parrafo."""
    txt = re.sub(r"[ \t]*\x00IMG(\d+)\x00[ \t]*",
                 lambda m: ("\n\n![imagen %d](%s)\n\n" % (int(m.group(1)) + 1, por_img[int(m.group(1))])
                            if int(m.group(1)) in por_img else " [imagen %d no descargada] " % (int(m.group(1)) + 1)),
                 txt)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def fetch_new_workitems(fuente):
    """WIQL: Task/Bug del sprint de la fuente, en estado New."""
    it, team = fuente["iteration"], None
    if it.startswith("@current"):
        team = it.partition(":")[2].strip() or "%s Team" % fuente["project"]
        filtro = "[System.IterationPath] = @CurrentIteration"
    else:
        filtro = "[System.IterationPath] UNDER '%s'" % it.replace("'", "''")
    query = ("SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND %s AND "
             "[System.WorkItemType] IN ('Task','Bug') AND [System.State] CONTAINS 'New' "
             "ORDER BY [System.Id]" % filtro)
    d = curl(base_url(fuente["project"], team) + "/_apis/wit/wiql?api-version=7.1", {"query": query})
    if "workItems" not in d:
        die("Azure no devolvio workItems para %s: %s" % (fuente["project"], json.dumps(d)[:200]))
    return [w["id"] for w in d["workItems"]]


def fetch_detail(project, wid):
    """Work item completo: fields + relations (adjuntos)."""
    return curl(base_url(project) + "/_apis/wit/workitems/%d?api-version=7.1&$expand=all" % wid)


# ----------------------------------------------------------------- board
def tipo_de(f):
    """Bug -> bug; todo lo demas (Task) -> task."""
    return "bug" if (f.get("System.WorkItemType") or "").lower() == "bug" else "task"


def textos(f, imagenes):
    """(descripcion, criterio) en Markdown. En los bugs, los pasos para reproducir van al criterio."""
    desc = html_a_md(f.get("System.Description"), imagenes)
    crit = (html_a_md(f.get("Microsoft.VSTS.Common.AcceptanceCriteria"), imagenes)
            or html_a_md(f.get("Microsoft.VSTS.TCM.ReproSteps"), imagenes))
    return desc, crit


# ----------------------------------------------------------------- sync
def recolectar():
    """[(fuente, id)] de todas las fuentes. Si una falla, die() antes de tocar el board."""
    return [(f, wid) for f in CFG["fuentes"] for wid in fetch_new_workitems(f)]


def one_pass(dry_run=False):
    pendientes = recolectar()
    if not pendientes:
        return {"action": "no-op", "added": [], "skipped": [],
                "message": "Azure sin tareas New en los sprints configurados"}

    already = BOARD.numeros()
    added, skipped, errors = [], [], []

    for fuente, wid in pendientes:
        key = str(wid)
        donde = fuente["repo"] or fuente["project"]
        if key in already:
            skipped.append({"id": wid, "repo": donde, "reason": "ya en el board (numero %s)" % key})
            continue
        try:
            item = fetch_detail(fuente["project"], wid)
        except SystemExit:
            raise
        except Exception as e:
            errors.append({"id": wid, "error": str(e)[:200]})
            continue
        f = item["fields"]
        imagenes = []
        desc, crit = textos(f, imagenes)

        title = f.get("System.Title") or "Work Item #%d" % wid
        prio = PRIO_MAP.get(f.get("Microsoft.VSTS.Common.Priority"), PRIO_DEFAULT)
        tipo = tipo_de(f)
        clave = "%s-%d" % (tipo, wid)

        if dry_run:
            exts = [os.path.splitext(n)[1].lower() for _, n, _ in adjuntos_de(item, imagenes)]
            added.append({"id": wid, "clave": clave, "repo": donde, "title": title, "prioridad": prio,
                          "imagenes": sum(e in IMAGEN or e == "" for e in exts),
                          "videos": sum(e in VIDEO for e in exts)})
            already.add(key)  # evita duplicados en la misma pasada
            continue

        # Adjuntos ANTES de crear la tarea: el .md nace completo (azure-sync nunca lo reescribe).
        por_img, seccion, fallidos = descargar_adjuntos(item, clave, imagenes)
        desc, crit = poner_imagenes(desc, por_img), poner_imagenes(crit, por_img)
        try:
            path = BOARD.crear(tipo, wid, prio, title, desc, crit or "_Sin criterio en Azure._",
                               repo=fuente["repo"], origen="azure:%s" % fuente["project"],
                               adjuntos=seccion)
        except wi.Error as e:
            errors.append({"id": wid, "error": str(e)[:200]})
        else:
            entrada = {"id": wid, "clave": clave, "repo": donde, "title": title, "archivo": path}
            if fallidos:
                entrada["adjuntos_fallidos"] = fallidos
            added.append(entrada)
            already.add(key)

    action = "dry-run" if dry_run else ("added" if added else ("partial" if errors else "no-op"))
    result = {"action": action, "added": added, "skipped": skipped, "errors": errors}

    if added and not dry_run:
        BOARD.log("azure-sync importo tareas", "sistema", "deteccion",
                  ", ".join(a["clave"] for a in added[:5]), "-", "-",
                  "Importadas %d tarea(s) de Azure DevOps: %s" % (
                      len(added), ", ".join("%s (%s)" % (a["id"], a["repo"]) for a in added)))
    return result


def do_refrescar(claves):
    """Vuelve a traer de Azure la descripcion, el criterio y los adjuntos de tareas YA importadas y
    reescribe solo esas secciones con el formato actual (listas, pasos, imagenes en su lugar).
    No cambia el estado ni toca notas, reporte, feedback ni resultado. Sin claves: todas las de Azure."""
    hechas, errores = [], []
    for t in BOARD.todas():
        origen = ""
        try:
            origen = wi.parsear(open(t["archivo"], encoding="utf-8").read())[0].get("origen", "")
        except OSError:
            pass
        if not origen.startswith("azure:") or (claves and t["id"] not in claves and t["numero"] not in claves):
            continue
        proyecto = origen.split(":", 1)[1]
        try:
            item = fetch_detail(proyecto, int(t["numero"]))
            imagenes = []
            desc, crit = textos(item["fields"], imagenes)
            por_img, seccion, fallidos = descargar_adjuntos(item, t["id"], imagenes)
            BOARD.modificar(t["id"], secs_set={
                "Descripción": poner_imagenes(desc, por_img) or "-",
                "Criterio de aceptación": poner_imagenes(crit, por_img) or "_Sin criterio en Azure._",
                "Adjuntos": seccion or "_Ninguno. Podés dejar imágenes en adjuntos/%s/._" % t["id"]})
            hechas.append({"tarea": t["id"], "estado": t["estado"], "adjuntos_fallidos": fallidos})
        except SystemExit:
            raise
        except Exception as e:
            errores.append({"tarea": t["id"], "error": str(e)[:200]})
    if hechas:
        BOARD.log("azure-sync refresco tareas", "sistema", "nota", ", ".join(h["tarea"] for h in hechas[:5]), "-", "-",
                  "Descripcion, criterio y adjuntos actualizados desde Azure: %d tarea(s)" % len(hechas))
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
    fuentes = []
    for f in CFG["fuentes"]:
        ids = fetch_new_workitems(f)
        nuevos = [i for i in ids if str(i) not in already]
        fuentes.append({"repo": f["repo"] or "-", "project": f["project"], "iteration": f["iteration"],
                        "azure_new_count": len(ids), "already_in_board": len(ids) - len(nuevos),
                        "pending_import": len(nuevos), "pending_ids": nuevos[:20]})
    print(json.dumps({"action": "status", "fuentes": fuentes}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ruta a azure-sync.env")
    ap.add_argument("--watch", type=int, metavar="SEG", help="bucle cada N segundos")
    ap.add_argument("--dry-run", action="store_true", help="muestra que haria sin escribir")
    ap.add_argument("--status", action="store_true", help="solo diagnostico")
    ap.add_argument("--refrescar", nargs="*", metavar="CLAVE",
                    help="re-trae descripcion/criterio/adjuntos de tareas ya importadas (sin claves: todas)")
    ap.add_argument("--fotogramas", action="store_true",
                    help="extrae fotogramas de videos ya descargados (tras instalar ffmpeg)")
    args = ap.parse_args()

    load_config(args.config)

    if not CFG["org"]:
        die("Falta AZURE_ORG en %s" % args.config)
    if not CFG["fuentes"]:
        die("No hay fuentes en %s" % args.config,
            "Un repo: AZURE_PROJECT + AZURE_ITERATION. Workspace: SYNC.<repo>=<proyecto>|<sprint o @current>")
    for f in CFG["fuentes"]:
        if not f["project"] or not f["iteration"]:
            die("Fuente incompleta para %s: falta proyecto o sprint" % (f["repo"] or "AZURE_PROJECT"),
                "Formato: SYNC.<repo>=<proyecto>|<Proyecto\\Sprint X o @current>")
    if not CFG["pat"]:
        die("Falta AZURE_DEVOPS_PAT", "Ponelo en el entorno, en azure-sync.secrets.env o en %s" % PAT_MCP)

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
        faltan = [f["repo"] for f in CFG["fuentes"] if f["repo"] not in BOARD.cfg["repos"]]
        if faltan:
            die("SYNC.%s no tiene su REPO.%s en autopilot.env" % (faltan[0], faltan[0]),
                "Cada repo de azure-sync.env debe estar declarado en autopilot.env")

    if args.status:
        return do_status()
    if args.refrescar is not None:
        return do_refrescar([c.lower() for c in args.refrescar])
    if args.fotogramas:
        return do_fotogramas()

    if args.watch:
        print("azure-sync en modo watch cada %ds. Ctrl+C para salir." % args.watch, flush=True)
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
