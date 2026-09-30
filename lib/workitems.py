#!/usr/bin/env python3
"""
workitems.py — El tablero de workitems en carpetas + Markdown.

Unica implementacion del formato. La usan wi.sh (escritura), watcher.sh
(lectura) y azure-sync.py (alta de tareas). Solo stdlib.

ESTRUCTURA
  $WORKITEMS_DIR/
    new/ in-progress/ qa/ validando/ e2e/ probando-e2e/ bug-fix/ stopped/ done/ reviewed/
    log.md

  - El ESTADO de una tarea es la carpeta donde esta. Nunca se guarda en el archivo.
  - Cambiar de estado = os.rename (atomico). Reescribir = tmp + os.replace (atomico).
  - Adjuntos en adjuntos/<clave>/ (fuera de las carpetas de estado: mover la tarea no los mueve).
    Desde el .md se referencian como ../adjuntos/<clave>/... (todas las carpetas de estado estan
    a la misma profundidad). Los fotogramas de un video van en <video>.frames/fNN.png.
  - Archivo: <tipo>-<numero>-<slug>.md. La clave de la tarea es <tipo>-<numero>,
    que es tambien el nombre de su rama de git. Ej: bug-140123.

DOS MODOS (autopilot.env):
  - Un repo:    BASE_BRANCH=<rama>. El repo es la carpeta del .env (o REPO_PATH).
  - Workspace:  una linea REPO.<carpeta>=<rama base> por repo, en la carpeta padre.
                Cada tarea indica su repo en el frontmatter (repo: <carpeta>) y su rama
                se crea DENTRO de ese repo, desde la base de ese repo.

EL BOARD NO VA EN GIT. Si viviera en el repo, cada cambio de rama del coder
cambiaria el tablero. install.sh --init lo agrega al .gitignore.
"""
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

ESTADOS = ["new", "in-progress", "qa", "validando", "e2e", "probando-e2e", "bug-fix", "stopped", "done", "reviewed"]
# Tareas que ya no estan activas. `reviewed` = done que el humano ya reviso (lo mueve el humano).
CERRADAS = ("done", "stopped", "reviewed")
PRIO = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
TIPOS = ("task", "bug")
SECCIONES = ["Descripción", "Criterio de aceptación", "Adjuntos", "Repos modificados", "Notas del desarrollador",
             "Reporte de QA", "Feedback de QA", "Reporte E2E", "Feedback de E2E", "Resultado", "Motivo de stopped"]
# Puestos que trabajan en paralelo: estado en el que esta la tarea mientras el puesto la trabaja.
# e2e solo recibe tareas con E2E=true (QA APROBADO -> e2e en vez de done).
PUESTOS = {"coder": "in-progress", "qa": "validando", "e2e": "probando-e2e"}
IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"}
CAMPOS = ["id", "tipo", "prioridad", "intento", "rama", "repo", "repos_extra", "origen", "sesion", "espera",
          "actualizado"]

RE_ARCHIVO = re.compile(r"^(task|bug)-(\d+)(?:-.*)?\.md$")


class Error(Exception):
    pass


# ----------------------------------------------------------------- config
def cargar_config(env_path=None):
    """Lee el .env del proyecto. El entorno tiene prioridad sobre el archivo.

    Modo un repo:
      REPO_PATH     default: carpeta del .env (o cwd si no hay .env)
      BASE_BRANCH   OBLIGATORIA: rama desde la que nacen las ramas de los workitems
    Modo workspace (hay al menos una clave REPO.<carpeta>):
      REPO.<carpeta>=<rama base>   una por repo; <carpeta> es relativa al .env
    Ambos:
      WORKITEMS_DIR default: <raiz>/.workitems. Relativo = relativo al .env.
      PARALLEL=true|false  (default false: 1 coder + 1 QA). Con true: MAX_CODERS y MAX_QA (default 2 y 2).
      WATCHDOG=true|false (default true), WATCHDOG_INTERVAL=60 s, HUNG_MINUTES=10, STALE_MINUTES=45,
      COMMAND_TIMEOUT=900 s (lo aplica aenv.sh).
    E2E (etapa despues del QA, agente e2e-tester):
      E2E=true|false (default false), MAX_E2E (default 1; con PARALLEL=false siempre 1),
      E2E_COMMAND_TIMEOUT=2400 s (aenv.sh --e2e y e2e.sh),
      E2E_CLIENTS.<backend>=<front>,<front>   que frontends del workspace consumen cada backend
      E2E_PLATFORMS.<front>=web,android       en que plataformas se prueba cada frontend
      E2E_API.<front-flutter>=<archivo>|<regex de la linea>|<reemplazo con {API}>
                                              como apuntar la app al backend LOCAL en la copia E2E
      TELEGRAM=true|false (avisos y comandos por Telegram), TELEGRAM_ALERTS_ONLY=true|false
      E2E_API.<front-web>=env:VAR1,VAR2       variables de URL del front web que aenv.sh --e2e apunta al
                                              backend LOCAL (conserva ruta; https->http, wss->ws)
    """
    vals = {}
    base = os.getcwd()
    if env_path:
        if not os.path.isfile(env_path):
            raise Error("no existe el archivo de config: %s" % env_path)
        base = os.path.dirname(os.path.abspath(env_path))
        for raw in open(env_path, encoding="utf-8"):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip("'\"")
    for k in ("REPO_PATH", "WORKITEMS_DIR", "BASE_BRANCH"):
        if os.environ.get(k):
            vals[k] = os.environ[k]

    absoluta = lambda x: os.path.abspath(os.path.join(base, os.path.expanduser(x)))
    ws = {k[5:]: v.strip() for k, v in vals.items() if k.startswith("REPO.") and k[5:]}
    if ws:
        repos = {n: {"path": absoluta(n), "base": b} for n, b in ws.items()}
        raiz = base
    else:
        raiz = absoluta(vals.get("REPO_PATH") or base)
        repos = {"": {"path": raiz, "base": vals.get("BASE_BRANCH", "").strip()}}
    wdir = absoluta(vals.get("WORKITEMS_DIR") or os.path.join(raiz, ".workitems"))
    valor_parallel = vals.get("PARALLEL", "false").strip().lower()
    paralelo = valor_parallel == "true"   # solo true/false; cualquier otro valor = false (y aviso)
    entero = lambda k, d: max(1, int(vals.get(k, d))) if str(vals.get(k, d)).strip().isdigit() else d
    capacidad = ({"coder": entero("MAX_CODERS", 2), "qa": entero("MAX_QA", 2), "e2e": entero("MAX_E2E", 1)}
                 if paralelo else {"coder": 1, "qa": 1, "e2e": 1})
    lista = lambda v: [x.strip() for x in v.split(",") if x.strip()]
    e2e_api = {}
    for k, v in vals.items():
        if k.startswith("E2E_API.") and k[8:] and v.strip().startswith("env:"):
            e2e_api[k[8:]] = {"env": [x.strip() for x in v.strip()[4:].split(",") if x.strip()]}
        elif k.startswith("E2E_API.") and k[8:]:
            partes = v.split("|")
            e2e_api[k[8:]] = ({"archivo": partes[0].strip(), "regex": partes[1], "reemplazo": "|".join(partes[2:])}
                              if len(partes) >= 3 and partes[0].strip() else {"invalido": v})
    valor_e2e = vals.get("E2E", "false").strip().lower()
    valor_tg = vals.get("TELEGRAM", "false").strip().lower()
    return {"workspace": bool(ws), "raiz": raiz, "dir": wdir, "repos": repos,
            "paralelo": paralelo, "capacidad": capacidad,
            "parallel_invalido": None if valor_parallel in ("true", "false") else vals.get("PARALLEL"),
            "vigia": {"activo": vals.get("WATCHDOG", "true").strip().lower() != "false",
                      "intervalo": entero("WATCHDOG_INTERVAL", 60), "hung_min": entero("HUNG_MINUTES", 10),
                      "stale_min": entero("STALE_MINUTES", 45), "timeout": entero("COMMAND_TIMEOUT", 900)},
            "e2e": {"activo": valor_e2e == "true",
                    "invalido": None if valor_e2e in ("true", "false") else vals.get("E2E"),
                    "timeout": entero("E2E_COMMAND_TIMEOUT", 2400),
                    "block_hosts": lista(vals.get("E2E_BLOCK_HOSTS", "").lower()),
                    "clients": {k[12:]: lista(v) for k, v in vals.items() if k.startswith("E2E_CLIENTS.") and k[12:]},
                    "platforms": {k[14:]: lista(v.lower()) for k, v in vals.items()
                                  if k.startswith("E2E_PLATFORMS.") and k[14:]},
                    "api": e2e_api},
            "telegram": {"activo": valor_tg == "true",
                         "invalido": None if valor_tg in ("true", "false") else vals.get("TELEGRAM"),
                         "solo_alertas": vals.get("TELEGRAM_ALERTS_ONLY", "false").strip().lower() == "true"},
            "env_path": os.path.abspath(env_path) if env_path else None}


# ----------------------------------------------------------------- util
def herramientas_faltantes(repo):
    """Lo que falta instalar para compilar y probar el repo (lo que el QA exige para certificar)."""
    import shutil
    faltan = []
    fvmrc = os.path.join(repo, ".fvmrc")
    fvm_viejo = os.path.join(repo, ".fvm", "fvm_config.json")
    if os.path.exists(os.path.join(repo, "pubspec.yaml")):
        if os.path.exists(fvmrc) or os.path.exists(fvm_viejo):
            version = ""
            for f, k in ((fvmrc, "flutter"), (fvm_viejo, "flutterSdkVersion")):
                try:
                    version = json.load(open(f)).get(k, "") or version
                except (OSError, ValueError):
                    pass
            if not shutil.which("fvm"):
                faltan.append("fvm (Flutter %s)" % version if version else "fvm")
        elif not shutil.which("flutter"):
            faltan.append("flutter")
    if os.path.exists(os.path.join(repo, "package.json")):
        faltan += [h for h in ("node", "npm") if not shutil.which(h)]
    return faltan



def filecmp_iguales(a, b):
    import filecmp
    return filecmp.cmp(a, b, shallow=False)


def cache_kit(*partes):
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "autopilot-kit", *partes)


RE_WT = re.compile(r"^(?P<repo>.+)-(?P<clave>(task|bug)-\d+)$")


def coder_wt_activo(repo, clave):
    return os.path.isdir(cache_kit("coder", "%s-%s" % (repo, clave)))


def reservar(repo, clave, rels):
    """Reserva archivos (rutas relativas al repo) para una tarea. Devuelve [(archivo, otra_clave)] de
    los que ya tiene OTRA tarea activa (su worktree de coder existe); esos no se reservan."""
    os.makedirs(cache_kit("reservas"), exist_ok=True)
    path = cache_kit("reservas", repo + ".json")
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            data = {}
        choques = []
        for rel in rels:
            rel = os.path.normpath(rel)
            otra = data.get(rel)
            if otra and otra != clave and coder_wt_activo(repo, otra):
                choques.append((rel, otra))
            else:
                data[rel] = clave
        escribir_atomico(path, json.dumps(data, ensure_ascii=False, indent=1))
    return choques


def liberar(repo, clave):
    path = cache_kit("reservas", repo + ".json")
    if not os.path.exists(path):
        return 0
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            data = json.load(open(path))
        except (OSError, ValueError):
            data = {}
        n = len(data)
        data = {k: v for k, v in data.items() if v != clave}
        escribir_atomico(path, json.dumps(data, ensure_ascii=False, indent=1))
    return n - len(data)


def reservas_de(repo, clave=None):
    try:
        data = json.load(open(cache_kit("reservas", repo + ".json")))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if clave is None or v == clave}


def reservar_ruta(ruta):
    """Para el hook: si `ruta` esta dentro del worktree de un coder, la reserva para esa tarea.
    Devuelve None si esta bien, o el motivo del bloqueo."""
    real = os.path.realpath(os.path.expanduser(ruta))
    raiz = os.path.realpath(cache_kit("coder")) + os.sep
    if not real.startswith(raiz):
        return None
    wt, _, rel = real[len(raiz):].partition(os.sep)
    m = RE_WT.match(wt)
    if not m or not rel:
        return None
    choques = reservar(m.group("repo"), m.group("clave"), [rel])
    if choques:
        return ("%s ya lo esta trabajando la tarea %s (reservado). Para no pisarse, dos tareas en paralelo no "
                "tocan el mismo archivo: no commitees lo parcial y termina con RESULTADO: EN ESPERA y "
                "CHOCA CON: %s" % (rel, choques[0][1], choques[0][1]))
    return None


def matar_procesos_en(ruta):
    try:
        import vigia
        return vigia.matar_en(ruta)
    except Exception:
        return []


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def slugify(texto, maximo=50):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:maximo].rstrip("-") or "tarea"


def escribir_atomico(path, contenido):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(contenido)
    os.replace(tmp, path)


# ----------------------------------------------------------------- formato
def parsear(texto):
    """Devuelve (meta, titulo, secciones). secciones: dict ordenado heading->contenido."""
    meta, cuerpo = {}, texto
    if texto.startswith("---\n"):
        fin = texto.find("\n---", 4)
        if fin != -1:
            for line in texto[4:fin].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            cuerpo = texto[fin + 4:].lstrip("\n")

    titulo, secciones, actual, buf = "", {}, None, []
    for line in cuerpo.splitlines():
        if line.startswith("# ") and not titulo and actual is None:
            titulo = line[2:].strip()
        elif line.startswith("## "):
            if actual is not None:
                secciones[actual] = "\n".join(buf).strip()
            actual, buf = line[3:].strip(), []
        elif actual is not None:
            buf.append(line)
    if actual is not None:
        secciones[actual] = "\n".join(buf).strip()
    return meta, titulo, secciones


def serializar(meta, titulo, secciones):
    out = ["---"]
    for k in CAMPOS + [k for k in meta if k not in CAMPOS]:
        if k in meta:
            out.append("%s: %s" % (k, meta[k]))
    out += ["---", "# %s" % titulo, ""]
    for h in SECCIONES + [h for h in secciones if h not in SECCIONES]:
        out += ["## %s" % h, "", secciones.get(h, "").strip(), ""]
    return "\n".join(out).rstrip() + "\n"


# ----------------------------------------------------------------- board
class Board:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = cfg["dir"]

    # -- repos
    def repo_de(self, nombre):
        """{'nombre','path','base'} del repo de una tarea. En modo un repo, siempre el unico."""
        repos = self.cfg["repos"]
        if not self.cfg["workspace"]:
            return dict(repos[""], nombre="")
        nombre = (nombre or "").strip()
        if nombre not in repos:
            raise Error("la tarea indica repo '%s', que no esta en autopilot.env (REPO.<carpeta>=<base>). "
                        "Repos: %s" % (nombre or "-", ", ".join(sorted(repos))))
        return dict(repos[nombre], nombre=nombre)

    def avisos(self):
        """Problemas de configuracion que dejarian tareas en stopped."""
        out = []
        if self.cfg.get("parallel_invalido") is not None:
            out.append("PARALLEL=%s no es valido: usa true o false. Se usa false (1 coder + 1 QA)"
                       % self.cfg["parallel_invalido"])
        out += self.avisos_e2e()
        tg = self.cfg.get("telegram", {})
        if tg.get("invalido") is not None:
            out.append("TELEGRAM=%s no es valido: usa true o false" % tg["invalido"])
        if tg.get("activo"):
            import telegram
            if not all(telegram.credenciales()):
                out.append("TELEGRAM=true pero no hay credenciales del bot: wi.sh <env> telegram-setup (en tu terminal)")
        for n, r in sorted(self.cfg["repos"].items()):
            etiqueta = "REPO.%s" % n if n else "BASE_BRANCH"
            if not r["base"]:
                out.append("%s vacia: define la rama base" % etiqueta)
            elif not os.path.isdir(r["path"]):
                out.append("%s: no existe la carpeta %s" % (etiqueta, r["path"]))
            else:
                import entorno
                e = entorno.validar(r["path"], copia=True)
                if e["destinos_en_env_real"] and e["estado"] != "ok":
                    out.append("%s: %s .env.autopilot (%s). Nada que se conecte a BD/API se va a ejecutar ahi: "
                               "%s" % (n or os.path.basename(r["path"]),
                                       {"falta": "no tiene", "inseguro": "no es seguro su",
                                        "incompleto": "esta incompleto su"}[e["estado"]], e["estado"],
                                       e.get("recomendacion", "")))
                faltan = herramientas_faltantes(r["path"])
                if faltan:
                    out.append("%s: faltan herramientas para compilar y probar: %s. El QA no va a poder "
                               "certificar sus tareas (quedaran en stopped)" % (n or os.path.basename(r["path"]),
                                                                                ", ".join(faltan)))
        return out

    # -- imagenes en los reportes
    RE_IMG = re.compile(r"(?:~|/)[^\s`'\"()<>\[\]]+?\.(?:png|jpe?g|gif|webp|bmp)", re.I)

    def incrustar_imagenes(self, clave, texto, carpetas=(), subcarpeta="imagenes"):
        """Convierte las imagenes que un agente menciona en su texto en imagenes Markdown.

        - Una ruta a una imagen que existe se reemplaza por ![nombre](../adjuntos/...).
        - Si esta fuera del board (p. ej. una captura del QA en su worktree, que se borra al dar
          el veredicto) se COPIA antes a adjuntos/<clave>/<subcarpeta>/.
        - Las imagenes de `carpetas` que el texto no menciona se agregan al final.
        Asi el humano ve las imagenes en el .md (VS Code, Obsidian, GitHub...).
        """
        base = os.path.join(self.dir, "adjuntos", clave)
        destino_dir = os.path.join(base, subcarpeta)
        rel = lambda p: "../" + os.path.relpath(p, self.dir).replace(os.sep, "/")
        copiadas = {}

        def al_board(ruta):
            real = os.path.realpath(os.path.expanduser(ruta))
            if real in copiadas:
                return copiadas[real]
            if not os.path.isfile(real):
                return None
            if real.startswith(os.path.realpath(self.dir) + os.sep):
                copiadas[real] = real
                return real
            os.makedirs(destino_dir, exist_ok=True)
            nombre = os.path.basename(real)
            dst, n = os.path.join(destino_dir, nombre), 1
            while os.path.exists(dst) and not filecmp_iguales(dst, real):
                n += 1
                dst = os.path.join(destino_dir, "%s-%d%s" % (os.path.splitext(nombre)[0], n, os.path.splitext(nombre)[1]))
            if not os.path.exists(dst):
                shutil.copy2(real, dst)
            copiadas[real] = dst
            return dst

        def reemplazo(ruta):
            dst = al_board(ruta)
            if not dst:
                return ruta
            return "![%s](%s)" % (os.path.basename(dst), rel(dst))  # en linea: no rompe listas

        # Una sola pasada: ![alt](ruta), `ruta` o una ruta suelta (absoluta o con ~, no parte de otra).
        ruta = r"(?<![\w./~-])(?:~|/)[^\s`'\"()<>\[\]]+?\.(?:png|jpe?g|gif|webp|bmp)(?!\w)"
        patron = re.compile(r"!\[[^\]]*\]\(\s*(?P<a>%s)\s*\)|`(?P<b>%s)`|(?P<c>%s)" % (ruta, ruta, ruta), re.I)
        texto = patron.sub(lambda m: reemplazo(m.group("a") or m.group("b") or m.group("c")), texto)
        extra = []
        for c in carpetas:
            for raiz, _, files in os.walk(os.path.expanduser(c)):
                for f in sorted(files):
                    p = os.path.join(raiz, f)
                    if self.RE_IMG.fullmatch(p) and os.path.realpath(p) not in copiadas:
                        dst = al_board(p)
                        if dst:
                            extra.append("![%s](%s)" % (os.path.basename(dst), rel(dst)))
        if extra:
            texto = texto.rstrip() + "\n\n**Imágenes:**\n\n" + "\n\n".join(extra)
        return re.sub(r"\n{3,}", "\n\n", texto).strip()

    RE_VIDEO = re.compile(r"(?<![\w./~-])(?:~|/)[^\s`'\"()<>\[\]]+?\.(?:mp4|webm|mov|mkv)(?!\w)", re.I)

    def enlazar_videos(self, clave, texto, subcarpeta):
        """Los videos que el texto menciona (p. ej. del agente E2E, en su copia que se va a borrar) se
        copian a adjuntos/<clave>/<subcarpeta>/ y quedan como enlace [nombre](../adjuntos/...)."""
        destino_dir = os.path.join(self.dir, "adjuntos", clave, subcarpeta)

        def copiar(m):
            real = os.path.realpath(os.path.expanduser(m.group(0)))
            if not os.path.isfile(real):
                return m.group(0)
            if not real.startswith(os.path.realpath(self.dir) + os.sep):
                os.makedirs(destino_dir, exist_ok=True)
                dst = os.path.join(destino_dir, os.path.basename(real))
                if not os.path.exists(dst):
                    shutil.copy2(real, dst)
                real = dst
            return "[%s](../%s)" % (os.path.basename(real), os.path.relpath(real, self.dir).replace(os.sep, "/"))
        return self.RE_VIDEO.sub(copiar, texto)

    # -- estructura
    def init(self):
        for e in ESTADOS:
            os.makedirs(os.path.join(self.dir, e), exist_ok=True)
        log = os.path.join(self.dir, "log.md")
        if not os.path.exists(log):
            escribir_atomico(log, "# Log de actividad\n\n"
                                  "| Hora | Origen | Tipo | Tarea | Rama | Commit | Evento | Detalle |\n"
                                  "|---|---|---|---|---|---|---|---|\n")

    def verificar(self):
        if not os.path.isdir(self.dir):
            raise Error("no existe el board %s. Crealo con: wi.sh <env> init" % self.dir)

    def lock(self):
        os.makedirs(self.dir, exist_ok=True)
        f = open(os.path.join(self.dir, ".lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    # -- lectura
    def archivos(self):
        """[(estado, clave, path)] de todas las tareas del board."""
        out = []
        for e in ESTADOS:
            d = os.path.join(self.dir, e)
            if not os.path.isdir(d):
                continue
            for n in sorted(os.listdir(d)):
                m = RE_ARCHIVO.match(n)
                if m:
                    out.append((e, "%s-%s" % (m.group(1), m.group(2)), os.path.join(d, n)))
        return out

    def numeros(self):
        """Numeros de workitem presentes en cualquier estado (para dedup)."""
        return {c.split("-", 1)[1] for _, c, _ in self.archivos()}

    def buscar(self, clave):
        clave = clave.strip().lower()
        if not re.match(r"^(task|bug)-\d+$", clave):
            raise Error("clave invalida '%s'. Formato: task-<numero> o bug-<numero>" % clave)
        hits = [(e, p) for e, c, p in self.archivos() if c == clave]
        if not hits:
            raise Error("no existe la tarea %s en %s" % (clave, self.dir))
        if len(hits) > 1:
            raise Error("la tarea %s esta duplicada: %s" % (clave, ", ".join(p for _, p in hits)))
        return hits[0]

    def leer(self, clave):
        estado, path = self.buscar(clave)
        meta, titulo, secs = parsear(open(path, encoding="utf-8").read())
        return estado, path, meta, titulo, secs

    def tarea_json(self, estado, clave, path):
        meta, titulo, secs = parsear(open(path, encoding="utf-8").read())
        try:
            intento = int(meta.get("intento") or 0)
        except ValueError:
            intento = 0
        return {
            "id": clave, "numero": clave.split("-", 1)[1], "tipo": clave.split("-", 1)[0],
            "nombre": titulo, "estado": estado, "archivo": path,
            "prioridad": meta.get("prioridad", "Medium"),
            "intento": intento, "rama": meta.get("rama") or clave,
            "repo": meta.get("repo", ""),
            "repo_path": None, "base": None, "repo_error": None,
            "descripcion": secs.get("Descripción", ""),
            "criterio": secs.get("Criterio de aceptación", ""),
            "feedback": secs.get("Feedback de QA", ""),
            "resultado": secs.get("Resultado", ""),
            "motivo": secs.get("Motivo de stopped", ""),
            "notas_dev": secs.get("Notas del desarrollador", ""),
            "repos_modificados": secs.get("Repos modificados", ""),
            "reporte_qa": secs.get("Reporte de QA", ""),
            "reporte_e2e": secs.get("Reporte E2E", ""),
            "feedback_e2e": secs.get("Feedback de E2E", ""),
            "sesion": meta.get("sesion") or None,
            "espera": meta.get("espera") or None,
            **self.adjuntos(clave),
        }

    def adjuntos(self, clave):
        """Imagenes (incluye fotogramas de videos, en orden) y videos de adjuntos/<clave>/.
        Tambien sirve para imagenes que el usuario deje a mano en esa carpeta."""
        carpeta = os.path.join(self.dir, "adjuntos", clave)
        imgs, vids = [], []
        for raiz, dirs, files in os.walk(carpeta):
            dirs.sort()
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                (imgs if ext in IMAGEN else vids if ext in VIDEO else []).append(os.path.join(raiz, f))
        return {"adjuntos": imgs, "videos": vids}

    def todas(self):
        out = []
        for e, c, p in self.archivos():
            t = self.tarea_json(e, c, p)
            try:
                repos = self.repos_de_tarea(parsear(open(p, encoding="utf-8").read())[0])
                t["repo_path"], t["base"] = repos[0]["path"], repos[0]["base"]
                t["repos"] = []
                for i, r in enumerate(repos):
                    wt = self.coder_worktree_path(r, c)
                    t["repos"].append({"nombre": r["nombre"] or os.path.basename(r["path"]), "path": r["path"],
                                       "base": r["base"], "principal": i == 0,
                                       "worktree": wt if os.path.isdir(wt) else None})
            except Error as err:
                t["repo_error"], t["repos"] = str(err), []
            out.append(t)
        return out

    def repos_de_tarea(self, meta):
        """Repo principal (el del work item) + los extra que el coder sumo, en ese orden."""
        principal = self.repo_de(meta.get("repo"))
        extra = [x.strip() for x in (meta.get("repos_extra") or "").split(",") if x.strip()]
        return [principal] + [self.repo_de(x) for x in extra if x != principal["nombre"]]

    # -- escritura
    def modificar(self, clave, estado_nuevo=None, meta_set=None, secs_set=None, secs_append=None):
        """Mueve (si corresponde) y reescribe una tarea. Primero rename, luego replace."""
        with self.lock():
            estado, path = self.buscar(clave)
            if estado_nuevo and estado_nuevo != estado:
                if estado_nuevo not in ESTADOS:
                    raise Error("estado invalido: %s" % estado_nuevo)
                puesto = next((p for p, e in PUESTOS.items() if e == estado_nuevo), None)
                ocupada = [c for e, c, _ in self.archivos() if e == estado_nuevo and c != clave.lower()]
                if puesto and len(ocupada) >= self.cfg["capacidad"][puesto]:
                    raise Error("el puesto %s esta lleno (%d de %d: %s). Maximo en %s: %d%s"
                                % (puesto, len(ocupada), self.cfg["capacidad"][puesto], ", ".join(ocupada),
                                   estado_nuevo, self.cfg["capacidad"][puesto],
                                   "" if self.cfg["paralelo"] else " (PARALLEL=false)"))
                destino = os.path.join(self.dir, estado_nuevo, os.path.basename(path))
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                os.rename(path, destino)
                path = destino
            meta, titulo, secs = parsear(open(path, encoding="utf-8").read())
            if estado_nuevo and estado_nuevo not in PUESTOS.values():
                meta.pop("sesion", None)  # la sesion de OpenCode es del puesto, no de la tarea
            if estado_nuevo == "in-progress":
                meta.pop("espera", None)  # la toma un coder: ya no espera a nadie
            for k, v in (meta_set or {}).items():
                meta[k] = v
            for k, v in (secs_set or {}).items():
                secs[k] = v
            for k, v in (secs_append or {}).items():
                prev = secs.get(k, "").strip()
                secs[k] = (prev + "\n\n" + v).strip() if prev else v
            meta["actualizado"] = ahora()
            escribir_atomico(path, serializar(meta, titulo, secs))
        if estado_nuevo == "qa":
            try:
                self._escribir_repos_modificados(clave.lower())
            except Error:
                pass
        if estado_nuevo in CERRADAS:
            self._cerrar_coder(clave.lower(), estado_nuevo)
        if estado_nuevo and estado_nuevo != estado:
            self._avisar_estado(clave.lower(), estado_nuevo, titulo, meta, secs, set(secs_append or {}))
        return path

    def avisar(self, texto, alerta=False, dedup=False):
        """Aviso por Telegram (si TELEGRAM=true). Nunca falla ni bloquea."""
        try:
            import telegram
            telegram.enviar(self.cfg, texto, alerta, dedup=dedup)
        except Exception:
            pass

    def _avisar_estado(self, clave, estado, titulo, meta, secs, escritas=()):
        def ultimo(s):  # ultimo bloque "### ..." de la seccion, sin su encabezado
            b = re.split(r"(?m)^### ", secs.get(s, "").strip())[-1].strip() if secs.get(s, "").strip() else ""
            return b.split("\n", 1)[1].strip() if "\n" in b and "RECHAZADO" in b.split("\n", 1)[0] else b
        n = meta.get("intento", "0")
        t = "%s — %s" % (clave, titulo)
        if estado == "in-progress":
            self.avisar("🧑‍💻 El coder empezó %s%s" % (t, " (corrige el intento %s)" % n if n != "0" else ""))
        elif estado == "qa":
            self.avisar("📦 %s terminada por el coder: a QA" % t)
        elif estado == "validando":
            self.avisar("🔍 QA certificando %s (intento %s)" % (t, n))
        elif estado == "e2e":
            self.avisar("🧾 %s aprobada por QA: en cola de pruebas E2E" % t)
        elif estado == "probando-e2e":
            self.avisar("📱 E2E probando %s" % t)
        elif estado == "bug-fix":
            quien = "E2E" if "Feedback de E2E" in escritas else "QA"
            fb = ultimo("Feedback de %s" % quien)
            self.avisar("↩️ %s rechazada por %s (intento %s), vuelve al coder:\n%s" % (t, quien, n, fb[:600]))
        elif estado == "done":
            self.avisar("✅ %s lista y certificada: revisala y mergea.\n%s" % (t, (secs.get("Resultado", "") or "")[:500]),
                        alerta=True)
        elif estado == "stopped":
            self.avisar("🚨 %s detenida, necesita tu intervencion:\n%s\n\nCuando lo resuelvas: /reqa %s (o /tarea %s)"
                        % (t, (secs.get("Motivo de stopped", "") or "-")[:900], clave, clave), alerta=True)

    def crear(self, tipo, numero, prioridad, titulo, descripcion, criterio, repo="", origen="manual",
              adjuntos=""):
        tipo = tipo.lower()
        if tipo not in TIPOS:
            raise Error("tipo invalido '%s'. Usa task o bug" % tipo)
        numero = str(numero).strip()
        if not numero.isdigit():
            raise Error("numero de workitem invalido: '%s'" % numero)
        if prioridad not in PRIO:
            raise Error("prioridad invalida '%s'. Usa %s" % (prioridad, "|".join(PRIO)))
        if self.cfg["workspace"]:
            self.repo_de(repo)  # valida: en un workspace cada tarea debe decir a que repo va
        with self.lock():
            if numero in self.numeros():
                raise Error("ya existe un workitem con numero %s en el board" % numero)
            clave = "%s-%s" % (tipo, numero)
            path = os.path.join(self.dir, "new", "%s-%s.md" % (clave, slugify(titulo)))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            meta = {"id": numero, "tipo": tipo, "prioridad": prioridad, "intento": "0",
                    "rama": clave, "repo": repo or "-", "origen": origen, "actualizado": ahora()}
            secs = {"Descripción": descripcion or "-",
                    "Criterio de aceptación": criterio or "_Sin criterio._",
                    "Adjuntos": adjuntos or ("_Ninguno. Podés dejar imágenes en adjuntos/%s/._" % clave)}
            escribir_atomico(path, serializar(meta, titulo, secs))
            return path

    def log(self, evento, origen, tipo, tarea="-", rama="-", commit="-", detalle="-"):
        if not os.path.isdir(self.dir):
            return
        c = lambda v: (str(v or "-")).replace("|", "\\|").replace("\n", " ")[:500]
        fila = "| %s |\n" % " | ".join(c(x) for x in (ahora(), origen, tipo, tarea, rama, commit, evento, detalle))
        path = os.path.join(self.dir, "log.md")
        if not os.path.exists(path):
            self.init()
        with self.lock():
            with open(path, "a", encoding="utf-8") as f:
                f.write(fila)

    # -- watcher
    def plan(self, recuperar=False):
        """Lo que el watcher le devuelve al agente principal.

        Dos puestos independientes, con capacidad (PARALLEL=false -> 1 y 1; true -> MAX_CODERS y MAX_QA):
          coder  (in-progress): toma bug-fix > new (saltando las que esperan a otra tarea)
          qa     (validando):   toma qa
        `acciones`: trabajo para cada puesto LIBRE. `terminadas`: tareas de un puesto cuya sesion de
        OpenCode ya termino (en Claude Code el fin del subagente lo avisa el propio cliente).
        recuperar=True (solo al iniciar /autopilot): una tarea en un puesto sin sesion viva no tiene
        agente -> stopped. En los relanzamientos NO se recupera nada: el otro puesto sigue trabajando.
        """
        import oc_sesion
        huerfanas, terminadas = [], []
        ocupados = {p: [] for p in PUESTOS}
        for t in self.todas():
            puesto = next((p for p, e in PUESTOS.items() if e == t["estado"]), None)
            if not puesto:
                continue
            ses = t.get("sesion")
            viva = oc_sesion.estado(ses) if ses else None   # None: sin sesion registrada (Claude Code)
            if ses and viva and viva["activa"] is False:
                terminadas.append({"puesto": puesto, "tarea": t, "sesion": ses, "outcome": viva.get("outcome")})
            elif recuperar and not (ses and viva and viva["activa"]):
                motivo = ("Huerfana en %s sin agente activo (recuperada al iniciar /autopilot). "
                          "Re-encolar manualmente: wi.sh new|reqa|re-e2e <clave>." % t["estado"])
                self.modificar(t["id"], "stopped", secs_set={"Motivo de stopped": motivo})
                self.log("Watcher recupero tarea huerfana", "watcher", "recuperacion",
                         t["id"], t["rama"], "-", "Estaba en %s sin agente. Marcada stopped." % t["estado"])
                huerfanas.append(t["id"])
                continue
            ocupados[puesto].append(t["id"])

        ts = self.todas()
        estado_de = {t["id"]: t["estado"] for t in ts}
        # Una tarea "en espera" (choco con archivos de otra) no se ofrece hasta que la otra termine.
        libre = lambda t: not t.get("espera") or estado_de.get(t["espera"]) in (None,) + CERRADAS
        orden = lambda t: (PRIO.get(t["prioridad"], 9), int(t["numero"]))
        by = lambda s: sorted([t for t in ts if t["estado"] == s], key=orden)
        bugfix, qa, nuevas, e2e = by("bug-fix"), by("qa"), by("new"), by("e2e")
        cap = self.cfg["capacidad"]

        acciones = []
        pausa = os.path.exists(os.path.join(self.dir, ".pausa"))   # /pausa desde Telegram
        huecos = 0 if pausa else cap["coder"] - len(ocupados["coder"])
        for t in [t for t in bugfix if libre(t)] + [t for t in nuevas if libre(t)]:
            if huecos <= 0:
                break
            acciones.append({"puesto": "coder", "tarea": t,
                             "accion": "desarrollar-bugfix" if t["estado"] == "bug-fix" else "desarrollar"})
            huecos -= 1
        for t in ([] if pausa else qa[:max(0, cap["qa"] - len(ocupados["qa"]))]):
            acciones.append({"puesto": "qa", "accion": "certificar", "tarea": t})
        if self.cfg["e2e"]["activo"] and not pausa:  # con E2E=false la cola e2e no se atiende (y avisos() lo dice)
            for t in e2e[:max(0, cap["e2e"] - len(ocupados["e2e"]))]:
                acciones.append({"puesto": "e2e", "accion": "probar-e2e", "tarea": t})
        return {"acciones": acciones, "terminadas": terminadas, "ocupados": ocupados,
                "capacidad": cap, "parallel": self.cfg["paralelo"],
                "en_espera": [{"id": t["id"], "espera": t["espera"]} for t in bugfix + nuevas if not libre(t)],
                "huerfanas_recuperadas": huerfanas, "stopped": [t["id"] for t in by("stopped")],
                "workspace": self.cfg["workspace"], "avisos": self.avisos(),
                "e2e": self.cfg["e2e"]["activo"], "pausa": pausa,
                "cola": {"bugfix": len(bugfix), "qa": len(qa), "new": len(nuevas), "e2e": len(e2e)}}

    # -- worktree del QA
    def qa_worktree(self, clave):
        """Una copia de trabajo por repo de la tarea, SOLO para el QA, en la punta de la rama
        (HEAD separado). Asi prueba sin tocar los repos donde trabaja el coder."""
        clave = clave.lower()
        meta = self.leer(clave)[2]
        rama = meta.get("rama") or clave
        out = []
        for r in self.repos_de_tarea(meta):
            destino = self.qa_worktree_path(r, clave)
            if os.path.isdir(destino):
                self.git(destino, "checkout", "--detach", "--force", rama)  # re-certificacion: punta nueva
            else:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                self.git(r["path"], "worktree", "add", "--detach", destino, rama)
            out.append({"repo": r["nombre"] or os.path.basename(r["path"]), "worktree": destino, "rama": rama,
                        "repo_path": r["path"], "base": r["base"],
                        "head": self.git(destino, "rev-parse", "--short", "HEAD").stdout.strip()})
        return out

    def qa_worktree_borrar(self, clave):
        clave = clave.lower()
        borrados = []
        for r in self.repos_de_tarea(self.leer(clave)[2]):
            destino = self.qa_worktree_path(r, clave)
            matar_procesos_en(destino)  # que no quede nada corriendo (p. ej. un MongoDB en memoria)
            if os.path.isdir(destino):
                self.git(r["path"], "worktree", "remove", "--force", destino)
                borrados.append(destino)
            self.git(r["path"], "worktree", "prune", check=False)
        return {"borrados": borrados}

    @staticmethod
    def qa_worktree_path(repo, clave):
        cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        nombre = repo["nombre"] or os.path.basename(repo["path"])
        return os.path.join(cache, "autopilot-kit", "qa", "%s-%s" % (nombre, clave))

    # -- E2E
    @staticmethod
    def e2e_worktree_path(repo, clave):
        return cache_kit("e2e", "%s-%s" % (repo["nombre"] or os.path.basename(repo["path"]), clave))

    def repos_e2e(self, clave):
        """Repos que entran en la prueba E2E, en orden: los de la tarea (en su rama), y los que hacen
        falta para recorrer el flujo real (en su rama base): los frontends que consumen un backend
        tocado y el backend de un frontend tocado (E2E_CLIENTS)."""
        tarea = self.repos_de_tarea(self.leer(clave)[2])
        nombre = lambda r: r["nombre"] or os.path.basename(r["path"])
        nombres = [nombre(r) for r in tarea]
        out = [dict(r, en_tarea=True) for r in tarea]
        if self.cfg["workspace"]:
            clients = self.cfg["e2e"]["clients"]
            for n in list(nombres):
                for extra in clients.get(n, []) + [be for be, fs in clients.items() if n in fs]:
                    if extra not in nombres and extra in self.cfg["repos"]:
                        nombres.append(extra)
                        out.append(dict(self.repo_de(extra), en_tarea=False))
        return out

    def e2e_worktree(self, clave):
        """Una copia por repo de repos_e2e(), solo para el agente E2E (HEAD separado): la rama de la
        tarea en los repos que toco, la base en los demas. Incluye como probarlo: tipo de repo,
        plataformas, si la app sabe apuntar al backend local (E2E_API) y su .env.autopilot.e2e."""
        import e2e as e2e_mod
        import entorno
        clave = clave.lower()
        meta = self.leer(clave)[2]
        rama = meta.get("rama") or clave
        cfg = self.cfg["e2e"]
        out = []
        for r in self.repos_e2e(clave):
            n = r["nombre"] or os.path.basename(r["path"])
            if r["en_tarea"]:
                ref = rama
            else:
                existe = lambda ref_: self.git(r["path"], "rev-parse", "--verify", "--quiet", ref_,
                                               check=False).returncode == 0
                ref = r["base"] if existe("refs/heads/%s" % r["base"]) else "origin/%s" % r["base"]
            destino = self.e2e_worktree_path(r, clave)
            if os.path.isdir(destino):
                self.git(destino, "checkout", "--detach", "--force", ref)
            else:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                self.git(r["path"], "worktree", "add", "--detach", destino, ref)
            e2e_mod.olvidar_api(destino)  # copia nueva o reusada: sin override de API todavia
            tipo = e2e_mod.tipo_repo(destino)
            info = {"repo": n, "worktree": destino, "ref": ref, "en_tarea": r["en_tarea"], "repo_path": r["path"],
                    "base": r["base"], "tipo": tipo,
                    "head": self.git(destino, "rev-parse", "--short", "HEAD").stdout.strip()}
            if tipo in ("flutter", "web"):
                info["plataformas"] = cfg["platforms"].get(n) or (["web", "android"] if tipo == "flutter" else ["web"])
            if tipo in ("flutter", "web"):
                info["api"] = cfg["api"].get(n)
            if tipo in ("backend", "web"):
                v = entorno.validar(destino, entorno.archivo_e2e(destino))
                info["entorno_e2e"] = dict({k: v[k] for k in ("estado", "recomendacion") if k in v},
                                           archivo=os.path.basename(v["archivo"]))
            out.append(info)
        return out

    def e2e_worktree_borrar(self, clave):
        import e2e as e2e_mod
        clave = clave.lower()
        borrados = []
        for r in self.repos_e2e(clave):
            destino = self.e2e_worktree_path(r, clave)
            matar_procesos_en(destino)  # backend, servidor web, emulador: todo lo que arranco ahi
            e2e_mod.olvidar_api(destino)
            if os.path.isdir(destino):
                self.git(r["path"], "worktree", "remove", "--force", destino)
                borrados.append(destino)
            self.git(r["path"], "worktree", "prune", check=False)
        return {"borrados": borrados}

    RE_ESTADO_CRITERIO = re.compile(r"\b(NO CUMPLE|NO VERIFICABLE|CUMPLE)\b")

    def validar_e2e(self, clave):
        """Revisa el ultimo Reporte E2E antes de aprobar: cada criterio (#### ...) CUMPLE y con al
        menos una captura que existe en el board, y cada plataforma esperada mencionada."""
        clave = clave.lower()
        _, _, meta, _, secs = self.leer(clave)
        intento = int(meta.get("intento") or 0)
        rep = secs.get("Reporte E2E", "")
        bloques = re.split(r"(?m)^### Intento ", rep)
        problemas, criterios = [], []
        ultimo = bloques[-1] if len(bloques) > 1 else ""
        if not ultimo:
            return {"ok": False, "problemas": ["no hay Reporte E2E"], "criterios": []}
        if not ultimo.startswith("%d " % intento) and not ultimo.startswith("%d(" % intento):
            problemas.append("el ultimo Reporte E2E no es del intento actual (%d)" % intento)
        partes = re.split(r"(?m)^#### ", ultimo)
        for p in partes[1:]:
            titulo = p.splitlines()[0].strip()
            m = self.RE_ESTADO_CRITERIO.search(titulo)
            estado = m.group(1) if m else None
            imgs = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", p)
            existentes = [i for i in imgs if os.path.isfile(os.path.normpath(os.path.join(self.dir, "x", i)))]
            criterios.append({"criterio": titulo, "estado": estado, "capturas": len(existentes)})
            if estado != "CUMPLE":
                problemas.append("criterio '%s': %s" % (titulo, estado or "sin estado (CUMPLE / NO CUMPLE / NO VERIFICABLE)"))
            if not existentes:
                problemas.append("criterio '%s': sin capturas (un criterio sin capturas no esta probado)" % titulo)
        if not criterios:
            problemas.append("el reporte no tiene criterios con el formato '#### <criterio>: CUMPLE'")
        esperadas = set()
        try:
            import e2e as e2e_mod
            for r in self.repos_e2e(clave):
                n = r["nombre"] or os.path.basename(r["path"])
                tipo = e2e_mod.tipo_repo(r["path"])
                if tipo == "flutter":
                    esperadas |= set(self.cfg["e2e"]["platforms"].get(n) or ["web", "android"])
                elif tipo == "web":
                    esperadas |= set(self.cfg["e2e"]["platforms"].get(n) or ["web"])
        except Error:
            pass
        for plat in sorted(esperadas):
            if not re.search(r"\b%s\b" % plat, ultimo, re.I):
                problemas.append("no se menciona la plataforma %s (esperada por los frontends de la tarea)" % plat)
        return {"ok": not problemas, "problemas": problemas, "criterios": criterios,
                "plataformas_esperadas": sorted(esperadas)}

    # -- casos de prueba que se guardan en el repo
    # Los casos quedan como tests normales del proyecto: tests/<clave>/ con cases.json. Nada del kit.
    RASTRO = re.compile(r"autopilot|aenv\.sh|e2e\.sh|E2E_PASOS|E2E_SALIDA|\.workitems|\.cache/autopilot", re.I)
    # Nombres que los runners del proyecto tomarian solos (npm test, flutter test, test:e2e): prohibidos.
    RE_NOMBRE_RUNNER = re.compile(r"(\.(spec|test)\.[cm]?[jt]sx?|_test\.dart|\.e2e-spec\.ts)$")

    def validar_casos(self, wt, clave, secretos=()):
        """Problemas de tests/<clave>/ (y tests/services.json) en la copia `wt`; [] si se puede guardar."""
        carpeta = os.path.join(wt, "tests", clave)
        probs = []
        casos = []
        if os.path.isdir(carpeta):
            try:
                casos = json.load(open(os.path.join(carpeta, "cases.json"), encoding="utf-8"))
                assert isinstance(casos, list) and casos
            except (OSError, ValueError, AssertionError):
                return ["tests/%s/cases.json no existe o no es una lista JSON de casos" % clave]
        for c in casos:
            if not isinstance(c, dict) or c.get("type") not in ("qa", "e2e") or not c.get("file"):
                probs.append("caso invalido en cases.json: %s" % json.dumps(c, ensure_ascii=False)[:120])
                continue
            real = os.path.realpath(os.path.join(wt, c["file"]))
            if not real.startswith(os.path.realpath(carpeta) + os.sep) or not os.path.isfile(real):
                probs.append("%s no existe dentro de tests/%s/" % (c["file"], clave))
            if c["type"] == "qa" and not c.get("command"):
                probs.append("%s: falta command" % c["file"])
        archivos = [os.path.join(r, f) for r, _, fs in os.walk(carpeta) for f in fs]
        services = os.path.join(wt, "tests", "services.json")
        if os.path.isfile(services):
            archivos.append(services)
            try:
                json.load(open(services, encoding="utf-8"))
            except ValueError:
                probs.append("tests/services.json no es JSON valido")
        for f in archivos:
            rel = os.path.relpath(f, wt)
            if os.path.islink(f):
                probs.append("%s es un enlace simbolico" % rel)
                continue
            if re.match(r"^\.env", os.path.basename(f)):
                probs.append("%s: no se guardan archivos .env" % rel)
            if self.RE_NOMBRE_RUNNER.search(os.path.basename(f)):
                probs.append("%s: ese nombre lo tomaria el runner del proyecto (npm test / flutter test); usa "
                             "*.check.ts, *_check.dart, *.flow.cjs o *_flow.dart" % rel)
            try:
                txt = open(f, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            m = self.RASTRO.search(txt)
            if m:
                probs.append("%s menciona '%s': los casos no pueden dejar rastro del sistema" % (rel, m.group(0)))
            if any(s and s in txt for s in secretos):
                probs.append("%s contiene el valor de una cuenta de prueba: usa variables de entorno" % rel)
        jest = os.path.join(wt, "node_modules", ".bin", "jest")
        if os.path.exists(jest):  # que el `npm test` del equipo no los tome
            r = subprocess.run([jest, "--listTests"], cwd=wt, capture_output=True, text=True, timeout=120)
            tomados = [l for l in r.stdout.splitlines() if os.path.realpath(l).startswith(os.path.realpath(carpeta))]
            if tomados:
                probs.append("jest del proyecto tomaria %s: cambia el nombre" % ", ".join(os.path.relpath(t, wt) for t in tomados))
        return probs

    def guardar_tests(self, clave, origen):
        """Al aprobar (QA o E2E): copia tests/<clave>/ de las copias del agente a la rama de la tarea y
        la commitea. Nunca bloquea la aprobacion: si algo no es valido, no se guarda y queda el aviso."""
        import e2e as e2e_mod
        clave = clave.lower()
        meta = self.leer(clave)[2]
        repos = self.repos_e2e(clave) if origen == "e2e" else [dict(r, en_tarea=True) for r in self.repos_de_tarea(meta)]
        path_de = self.e2e_worktree_path if origen == "e2e" else self.qa_worktree_path
        secretos = [v for v in e2e_mod.cuentas(self.cfg).values() if len(v) >= 4]
        guardados, avisos = [], []
        for r in repos:
            nombre = r["nombre"] or os.path.basename(r["path"])
            wt = path_de(r, clave)
            hay_casos = os.path.isdir(os.path.join(wt, "tests", clave))
            svc = os.path.join(wt, "tests", "services.json")
            # services.json (como levantar el repo) se guarda aunque el repo no tenga casos, si es nuevo o cambio
            hay_svc = os.path.isfile(svc) and self.git(wt, "status", "--porcelain", "--", "tests/services.json",
                                                         check=False).stdout.strip() != ""
            if not hay_casos and not hay_svc:
                continue
            probs = self.validar_casos(wt, clave, secretos)
            if probs:
                avisos.append("%s: no se guardaron los casos (%s)" % (nombre, "; ".join(probs)))
                continue
            try:
                if not r.get("en_tarea", True):
                    self.preparar_rama(clave, "nueva", repo=nombre)
                dst = self.coder_worktree_path(r, clave)
                if not os.path.isdir(dst):
                    self._rama_en(r, clave, "existente")
                destino = os.path.join(dst, "tests", clave)
                rutas = []
                if hay_casos:
                    if os.path.isdir(destino):
                        shutil.rmtree(destino)
                    shutil.copytree(os.path.join(wt, "tests", clave), destino)
                    rutas.append(os.path.join("tests", clave))
                if hay_svc:
                    os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
                    shutil.copy2(svc, os.path.join(dst, "tests", "services.json"))
                    rutas.append(os.path.join("tests", "services.json"))
                self.git(dst, "add", "--", *rutas)
                if self.git(dst, "diff", "--cached", "--quiet", check=False).returncode == 0:
                    continue
                self.git(dst, "commit", "-m", "test: casos de prueba de %s" % clave)
                casos = json.load(open(os.path.join(destino, "cases.json"), encoding="utf-8")) if hay_casos else []
                n = {t: sum(1 for c in casos if c.get("type") == t) for t in ("qa", "e2e")}
                guardados.append({"repo": nombre, "commit": self.git(dst, "rev-parse", "--short", "HEAD").stdout.strip(),
                                  "qa": n["qa"], "e2e": n["e2e"]})
            except Error as e:
                avisos.append("%s: no se pudieron guardar los casos (%s)" % (nombre, str(e).strip().splitlines()[0][:200]))
        if guardados or avisos:
            linea = "Tests guardados (%s): %s%s" % (origen.upper(), "; ".join(
                "%s @ %s (%d qa, %d e2e)" % (g["repo"], g["commit"], g["qa"], g["e2e"]) for g in guardados) or "ninguno",
                "".join("\n- ⚠️ " + a for a in avisos))
            self.modificar(clave, secs_append={"Resultado": linea})
            self.log("Tests guardados", "sistema", "nota", clave, clave, "-", linea.replace("\n", " "))
        return {"guardados": guardados, "avisos": avisos}

    def guardar_smoke(self, copia):
        """Guarda tests/smoke/ (y tests/services.json) de una copia de trabajo en la rama `smoke-tests` del
        repo (sale de su rama base si no existe), con las mismas validaciones que los casos de una tarea."""
        import e2e as e2e_mod
        copia = os.path.realpath(os.path.expanduser(copia))
        repo_path = os.path.dirname(self.git(copia, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip().rstrip("/"))
        nombre = next((n for n, r in self.cfg["repos"].items() if os.path.realpath(r["path"]) == repo_path), None)
        if nombre is None:
            raise Error("%s no es una copia de ningun repo de autopilot.env" % copia)
        r = dict(self.cfg["repos"][nombre], nombre=nombre)
        secretos = [v for v in e2e_mod.cuentas(self.cfg).values() if len(v) >= 4]
        probs = self.validar_casos(copia, "smoke", secretos)
        hay_casos = os.path.isfile(os.path.join(copia, "tests", "smoke", "cases.json"))
        hay_svc = os.path.isfile(os.path.join(copia, "tests", "services.json"))
        if not hay_casos and not hay_svc:
            probs.append("no hay tests/smoke/cases.json ni tests/services.json en %s" % copia)
        if probs:
            raise Error("no se guardan las pruebas de humo: " + "; ".join(probs))
        existe = lambda ref: self.git(r["path"], "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
        dst = cache_kit("smoke", nombre)
        if os.path.isdir(dst):
            self.git(r["path"], "worktree", "remove", "--force", dst, check=False)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if existe("refs/heads/smoke-tests"):
            self.git(r["path"], "worktree", "add", dst, "smoke-tests")
        else:
            base = r["base"] if existe("refs/heads/%s" % r["base"]) else "origin/%s" % r["base"]
            self.git(r["path"], "worktree", "add", "--no-track", "-b", "smoke-tests", dst, base)
        try:
            destino = os.path.join(dst, "tests", "smoke")
            rutas = []
            if hay_casos:
                if os.path.isdir(destino):
                    shutil.rmtree(destino)
                shutil.copytree(os.path.join(copia, "tests", "smoke"), destino)
                rutas.append(os.path.join("tests", "smoke"))
            if hay_svc:
                os.makedirs(os.path.join(dst, "tests"), exist_ok=True)
                shutil.copy2(os.path.join(copia, "tests", "services.json"), os.path.join(dst, "tests", "services.json"))
                rutas.append(os.path.join("tests", "services.json"))
            self.git(dst, "add", "--", *rutas)
            if self.git(dst, "diff", "--cached", "--quiet", check=False).returncode == 0:
                return {"repo": nombre, "rama": "smoke-tests", "commit": None, "nota": "sin cambios"}
            self.git(dst, "commit", "-m", "test: pruebas de humo")
            return {"repo": nombre, "rama": "smoke-tests", "commit": self.git(dst, "rev-parse", "--short", "HEAD").stdout.strip()}
        finally:
            self.git(r["path"], "worktree", "remove", "--force", dst, check=False)

    def avisos_e2e(self):
        cfg = self.cfg["e2e"]
        out = []
        if cfg["invalido"] is not None:
            out.append("E2E=%s no es valido: usa true o false. Se usa false (sin etapa E2E)" % cfg["invalido"])
        pendientes = [c for e, c, _ in self.archivos() if e == "e2e"] if os.path.isdir(self.dir) else []
        if not cfg["activo"]:
            if pendientes:
                out.append("hay tareas en e2e (%s) pero E2E=false: nadie las va a probar. Activa E2E=true o "
                           "muevelas a done a mano" % ", ".join(pendientes))
            return out
        import e2e as e2e_mod
        falta = e2e_mod.herramientas_faltantes()
        if falta:
            out.append("E2E=true pero faltan herramientas E2E: %s. Corre ~/.local/share/autopilot-kit/e2e-setup.sh "
                       "(sin eso las tareas quedaran NO CERTIFICABLE en E2E)" % ", ".join(falta))
        for n, a in sorted(cfg["api"].items()):
            if "invalido" in a:
                out.append("E2E_API.%s invalido: usa <archivo>|<regex de la linea>|<reemplazo con {API}>" % n)
        for n, r in sorted(self.cfg["repos"].items()):
            if not os.path.isdir(r["path"]):
                continue
            nombre = n or os.path.basename(r["path"])
            tipo = e2e_mod.tipo_repo(r["path"])
            if tipo == "flutter" and nombre not in cfg["api"]:
                out.append("%s (Flutter): falta E2E_API.%s. Sin eso el E2E no puede apuntar la app al backend "
                           "local y la deja NO CERTIFICABLE" % (nombre, nombre))
            if tipo == "web" and nombre not in cfg["api"] and any(nombre in fs for fs in cfg["clients"].values()):
                out.append("%s (web): sin E2E_API.%s=env:<VARIABLES DE URL> usara la API de su %s, no el backend "
                           "local de la tarea" % (nombre, nombre, entorno.archivo_e2e(r["path"])))
            if tipo in ("backend", "web"):
                import entorno
                archivo_env = entorno.archivo_e2e(r["path"])
                v = entorno.validar(r["path"], archivo_env, copia=True)
                if v["estado"] != "ok":
                    out.append("%s: %s para E2E (%s). %s" % (nombre, archivo_env, v["estado"], v.get("recomendacion", "")))
        if not e2e_mod.cuentas(self.cfg):
            out.append("E2E=true pero no hay cuentas de prueba: crea %s junto a autopilot.env con variables "
                       "E2E_* (p. ej. E2E_<ROL>_USER / E2E_<ROL>_PASSWORD; solo cuentas de QA)" % e2e_mod.ARCHIVO_CUENTAS)
        return out

    # -- git
    def git(self, repo, *args, check=True):
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise Error("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:300]))
        return r

    @staticmethod
    def coder_worktree_path(repo, clave):
        nombre = repo["nombre"] or os.path.basename(repo["path"])
        return cache_kit("coder", "%s-%s" % (nombre, clave))

    def _rama_en(self, r, clave, modo):
        """Deja la rama <clave> del repo `r` lista en el WORKTREE del coder (nunca en la copia
        principal del humano, que no cambia de rama). modo: nueva | existente | nueva-o-existente.
        Si el worktree ya existe (bug-fix, o una tarea que volvio de 'en espera'), se reusa."""
        repo, base = r["path"], r["base"]
        if not base:
            raise Error("falta la rama base en autopilot.env (%s): define desde que rama se crean las ramas"
                        % ("REPO.%s" % r["nombre"] if r["nombre"] else "BASE_BRANCH"))
        if self.git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
            raise Error("%s no es un repositorio git" % repo)
        wt = self.coder_worktree_path(r, clave)
        nombre = os.path.basename(repo)
        if os.path.isdir(wt):
            actual = self.git(wt, "branch", "--show-current", check=False).stdout.strip()
            if actual != clave:
                raise Error("%s: el worktree %s esta en '%s', no en %s" % (nombre, wt, actual or "HEAD separado", clave))
            return wt
        existe = lambda ref: self.git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
        # Donde esta abierta la rama (git no deja abrirla dos veces con nombre)
        lista = self.git(repo, "worktree", "list", "--porcelain").stdout
        for bloque in lista.strip().split("\n\n"):
            if "branch refs/heads/%s" % clave in bloque.split("\n"):
                donde = bloque.split("\n")[0][len("worktree "):]
                raise Error("%s: la rama %s esta abierta en %s. Cambia esa copia a otra rama y reencola la tarea"
                            % (nombre, clave, donde))
        if modo == "nueva-o-existente":
            modo = "existente" if existe("refs/heads/%s" % clave) else "nueva"
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        if modo == "nueva":
            if existe("refs/heads/%s" % base):
                origen = base
            elif existe("refs/remotes/origin/%s" % base):
                origen = "origin/%s" % base
            else:
                raise Error("%s: no existe la rama base '%s' (ni local ni origin/%s)" % (nombre, base, base))
            if existe("refs/heads/%s" % clave):
                propios = self.git(repo, "rev-list", "--count", "%s..%s" % (origen, clave)).stdout.strip()
                if propios != "0":
                    raise Error("%s: la rama %s ya existe con %s commit(s) que no estan en %s; no se recrea "
                                "para no pisar trabajo previo" % (nombre, clave, propios, origen))
                # Sin commits propios (un intento que se detuvo antes de commitear): se reusa en la punta de la base.
                self.git(repo, "worktree", "add", "--no-track", "-B", clave, wt, origen)
            else:
                self.git(repo, "worktree", "add", "--no-track", "-b", clave, wt, origen)
        elif modo == "existente":
            if not existe("refs/heads/%s" % clave):
                raise Error("%s: la rama %s no existe" % (nombre, clave))
            self.git(repo, "worktree", "add", wt, clave)
        else:
            raise Error("modo invalido: %s (nueva|existente)" % modo)
        return wt

    def _info_rama(self, r, clave):
        wt = self.coder_worktree_path(r, clave)
        return {"rama": clave, "base": r["base"], "repo": r["nombre"] or os.path.basename(r["path"]),
                "repo_path": r["path"], "worktree": wt,
                "head": self.git(wt, "rev-parse", "--short", "HEAD").stdout.strip()}

    def coder_worktree_borrar(self, clave, forzar=True):
        """Quita los worktrees del coder de la tarea y libera sus reservas de archivos."""
        clave = clave.lower()
        borrados, conservados = [], []
        for r in self.repos_de_tarea(self.leer(clave)[2]):
            wt = self.coder_worktree_path(r, clave)
            nombre = r["nombre"] or os.path.basename(r["path"])
            if os.path.isdir(wt):
                sucio = self.git(wt, "status", "--porcelain", check=False).stdout.strip()
                if sucio and not forzar:
                    conservados.append(wt)
                    continue
                matar_procesos_en(wt)
                self.git(r["path"], "worktree", "remove", "--force", wt)
                borrados.append(wt)
            self.git(r["path"], "worktree", "prune", check=False)
            liberar(nombre, clave)
        return {"borrados": borrados, "conservados_con_cambios": conservados}

    def _cerrar_coder(self, clave, estado):
        """done -> se borra el worktree del coder; stopped -> se borra si no tiene cambios sin commitear
        (si los tiene se conserva para que el humano los vea). En ambos casos se liberan las reservas."""
        try:
            r = self.coder_worktree_borrar(clave, forzar=(estado != "stopped"))
        except Error:
            return
        for wt in r["conservados_con_cambios"]:
            self.modificar(clave, secs_append={"Motivo de stopped": "Cambios sin commitear conservados en %s" % wt})

    def solapes(self, clave):
        """Archivos que la tarea cambio (o reservo) y que tambien cambio o reservo otra tarea activa del
        mismo repo: posible conflicto al mergear."""
        clave = clave.lower()
        out = []
        activas = {t["id"]: t for t in self.todas() if t["estado"] not in CERRADAS and t["id"] != clave}
        for r in self.repos_de_tarea(self.leer(clave)[2]):
            nombre = r["nombre"] or os.path.basename(r["path"])
            mios = set(self._cambiados(r, clave)) | set(reservas_de(nombre, clave))
            for otra in activas:
                suyos = set(self._cambiados(r, otra)) | set(reservas_de(nombre, otra))
                comunes = sorted(mios & suyos)
                if comunes:
                    out.append({"repo": nombre, "con": otra, "archivos": comunes})
        return out

    def repos_modificados(self, clave):
        """Desde git (no desde lo que dice el agente): por cada repo de la tarea, commits base..rama
        y archivos cambiados. Un repo de la tarea sin commits aparece con commits vacios."""
        clave = clave.lower()
        out = []
        for r in self.repos_de_tarea(self.leer(clave)[2]):
            nombre = r["nombre"] or os.path.basename(r["path"])
            existe = lambda ref: self.git(r["path"], "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
            base = r["base"] if existe("refs/heads/%s" % r["base"]) else "origin/%s" % r["base"]
            item = {"repo": nombre, "rama": clave, "base": r["base"], "commits": [], "archivos": []}
            if existe("refs/heads/%s" % clave) and existe(base):
                log = self.git(r["path"], "log", "--format=%h %s", "%s..%s" % (base, clave), check=False).stdout
                item["commits"] = [l for l in log.splitlines() if l.strip()]
                item["archivos"] = self.git(r["path"], "diff", "--name-only", "%s...%s" % (base, clave),
                                            check=False).stdout.split()
            out.append(item)
        return out

    def _escribir_repos_modificados(self, clave):
        """Seccion '## Repos modificados' (se reemplaza cada vez que la tarea pasa a qa) y aviso si no
        coincide con el bloque REPOS MODIFICADOS que declaro el coder en su ultima nota."""
        datos = self.repos_modificados(clave)
        filas = ["| Repo | Rama | Base | Commits | Archivos |", "|---|---|---|---|---|"]
        detalle = []
        for d in datos:
            filas.append("| %s | %s | %s | %s | %s |" % (d["repo"], d["rama"], d["base"],
                                                    len(d["commits"]) or "sin cambios", len(d["archivos"]) or "-"))
            if d["commits"]:
                detalle.append("**%s** (`%s`, desde `%s`):\n\n%s\n\nArchivos: %s" % (
                    d["repo"], d["rama"], d["base"], "\n".join("- `%s`" % c for c in d["commits"]),
                    ", ".join("`%s`" % f for f in d["archivos"][:40]) + (" …" if len(d["archivos"]) > 40 else "")))
        notas = self.leer(clave)[4].get("Notas del desarrollador", "")
        ultima = notas.split("### Intento")[-1] if notas else ""
        bloque = re.search(r"REPOS MODIFICADOS:?\s*\n((?:\s*[-*].*\n?)+)", ultima)
        declarados = set()
        if bloque:
            for l in bloque.group(1).splitlines():
                m = re.match(r"\s*[-*]\s*`?([\w.\-]+)`?\s*[—–-]+\s*rama\b", l)  # "- <repo> — rama ..."
                if m:
                    declarados.add(m.group(1))
        con_cambios = {d["repo"] for d in datos if d["commits"]}
        avisos = []
        if not bloque:
            avisos.append("⚠️ El coder no declaró el bloque REPOS MODIFICADOS en sus notas.")
        else:
            if declarados - con_cambios:
                avisos.append("⚠️ No coincide con lo que declaró el coder: declaró %s pero no tienen commits en la rama."
                              % ", ".join(sorted(declarados - con_cambios)))
            if con_cambios - declarados:
                avisos.append("⚠️ No coincide con lo que declaró el coder: hay commits en %s y no los declaró."
                              % ", ".join(sorted(con_cambios - declarados)))
        texto = "\n".join(filas) + ("\n\n" + "\n\n".join(detalle) if detalle else "") + \
                ("\n\n" + "\n".join(avisos) if avisos else "") + "\n\n_Calculado desde git al pasar a qa (%s)._" % ahora()
        self.modificar(clave, secs_set={"Repos modificados": texto})
        return datos

    def _cambiados(self, r, clave):
        existe = lambda ref: self.git(r["path"], "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
        base = r["base"] if existe("refs/heads/%s" % r["base"]) else "origin/%s" % r["base"]
        if not existe("refs/heads/%s" % clave) or not existe(base):
            return []
        cambios = self.git(r["path"], "diff", "--name-only", "%s...%s" % (base, clave), check=False).stdout.split()
        wt = self.coder_worktree_path(r, clave)
        if os.path.isdir(wt):  # lo que todavia no se commiteo tambien cuenta
            cambios += [l[3:] for l in self.git(wt, "status", "--porcelain", check=False).stdout.splitlines()]
        return cambios

    def esperar(self, clave, otra):
        """El coder choco con archivos de `otra`: la tarea vuelve a la cola (new o bug-fix) y el watcher no la
        ofrece hasta que `otra` termine. Conserva su worktree y su rama para retomarla."""
        clave, otra = clave.lower(), otra.lower()
        meta = self.leer(clave)[2]
        destino = "bug-fix" if int(meta.get("intento") or 0) > 0 else "new"
        with self.lock():
            estado, path = self.buscar(clave)
            dst = os.path.join(self.dir, destino, os.path.basename(path))
            os.rename(path, dst)
            meta, titulo, secs = parsear(open(dst, encoding="utf-8").read())
            meta.pop("sesion", None)
            meta["espera"] = otra
            meta["actualizado"] = ahora()
            escribir_atomico(dst, serializar(meta, titulo, secs))
        self.avisar("⏸️ %s en espera: comparte archivos con %s; se retoma cuando esa termine" % (clave, otra))
        self.log("Tarea en espera", "sistema", "nota", clave, clave, "-",
                 "Choca con archivos de %s: vuelve a %s hasta que %s termine" % (otra, destino, otra))
        return {"tarea": clave, "estado": destino, "espera": otra}

    def preparar_rama(self, clave, modo, repo=None):
        """Deja los repos de la tarea parados en su rama <clave>.

        Sin repo (el orquestador):
          modo=nueva      crea <clave> en el repo principal desde su rama base. Si ya existe, error.
          modo=existente  cambia a <clave> en TODOS los repos de la tarea (ciclo de bug-fix).
          Si falla, la tarea pasa a stopped con el motivo y se lanza Error.
        Con repo=<carpeta> distinta de la principal (el coder, en un workspace):
          crea <clave> en ese repo desde SU rama base (o la reusa si ya existe) y la registra en
          repos_extra. Si falla NO pasa la tarea a stopped: el error vuelve al coder.
        Nunca hace push, merge, rebase ni borra ramas.
        """
        clave = clave.lower()
        meta = self.leer(clave)[2]
        principal = self.repo_de(meta.get("repo"))
        if repo and repo != principal["nombre"]:
            if not self.cfg["workspace"]:
                raise Error("--repo solo aplica en un workspace (autopilot.env con REPO.<carpeta>=...)")
            if repo not in self.cfg["repos"]:
                raise Error("el repo '%s' no esta declarado en autopilot.env. Repos: %s. Pide al humano "
                            "que lo agregue con /autopilot-init." % (repo, ", ".join(sorted(self.cfg["repos"]))))
            r = self.repo_de(repo)
            self._rama_en(r, clave, "nueva-o-existente")
            extra = [x.strip() for x in (meta.get("repos_extra") or "").split(",") if x.strip()]
            if repo not in extra:
                self.modificar(clave, meta_set={"repos_extra": ", ".join(extra + [repo])})
                self.log("Rama en repo adicional", "agente", "nota", clave, clave, "-",
                         "%s: rama %s desde %s" % (repo, clave, r["base"]))
            return self._info_rama(r, clave)
        try:
            repos = [principal] if modo == "nueva" else self.repos_de_tarea(meta)
            for r in repos:
                self._rama_en(r, clave, modo)
        except Error as e:
            self.modificar(clave, "stopped", secs_set={"Motivo de stopped": str(e)})
            self.log("No se pudo preparar la rama", "sistema", "Stopped", clave, clave, "-", str(e))
            raise
        self.modificar(clave, meta_set={"rama": clave})
        info = self._info_rama(principal, clave)
        if len(repos) > 1:
            info["repos"] = [self._info_rama(r, clave) for r in repos]
        return info


# ----------------------------------------------------------------- CLI
USO = """uso: wi.sh <env> <comando> [args]
  init                                   crea las carpetas del board y log.md
  in-progress|qa|validando|bugfix|done|new <clave>
  reviewed   <clave>                     done -> reviewed: el humano ya reviso la tarea
  stopped    <clave> <motivo>
  rama       <clave> nueva|existente [--repo <carpeta>]
                                         crea/cambia a la rama <clave> desde la base de su repo.
                                         --repo (workspace): abre la MISMA rama en otro repo
                                         declarado y lo suma a la tarea (lo usa el coder)
  repos      <clave>                     repos de la tarea (principal + extra) en JSON
  repos-modificados <clave>              desde git: commits y archivos por repo (JSON). Al pasar a qa
                                         se escribe en la seccion '## Repos modificados' de la tarea
  resultado  <clave> <texto>
  motivo     <clave> <texto>
  feedback   <clave> <texto>             agrega al historial de Feedback de QA
  criterio   <clave> <texto>
  intentos   <clave> <n>
  certificar <clave> <intento_nuevo>     qa -> validando, fija Intento
  aprobar    <clave>                     validando -> done (con E2E=true: -> e2e, la cola de pruebas E2E)
  rechazar   <clave> <feedback>          validando -> bug-fix
  reqa       <clave>                     -> qa, Intento a 0 (conserva el historial)
  probar-e2e <clave>                     e2e -> probando-e2e (ocupa el puesto e2e)
  e2e-worktree <clave>                   copias para el E2E: repos de la tarea (su rama) + los que
                                         hacen falta para el flujo real (E2E_CLIENTS, en su base)
  e2e-worktree-borrar <clave>            (mata lo que haya quedado corriendo: backend, web, emulador)
  reporte-e2e <clave> <texto|-> [--imagenes <dir>]...  reporte del E2E con sus capturas
  validar-e2e <clave>                    revisa el ultimo Reporte E2E (JSON): criterios CUMPLE con capturas
  aprobar-e2e <clave>                    probando-e2e -> done, SOLO si validar-e2e da ok
  rechazar-e2e <clave> <feedback>        probando-e2e -> bug-fix (Feedback de E2E)
  re-e2e     <clave>                     -> e2e otra vez (p. ej. tras resolver un NO CERTIFICABLE)
  telegram-setup                         conecta el bot del autopilot a tu chat (interactivo, en tu terminal)
  notify-test                            manda un mensaje de prueba por Telegram
  notify     <texto> [--alert]           manda un aviso por Telegram (respeta TELEGRAM=true)
  smoke-save <copia>                     guarda tests/smoke/ de una copia de trabajo en la rama smoke-tests
                                         del repo (pruebas de humo: no son de una tarea)
  health     [<clave>|smoke|--all] [--web|--android] [--deep]
                                         health check E2E: que falta ANTES de correr. Alias: health-check
  test       <clave>|smoke|--all [--qa|--e2e] [--web|--android] [--ref <rama>]
                                         vuelve a correr los casos guardados en los repos
                                         (tests/<clave>/cases.json); --all = regresion en las ramas base.
                                         Reporte en <workspace>/test-results/. Alias: run-tests
  add-task   <task|bug> <numero> <prioridad> <titulo> <descripcion> <criterio> [repo]
                                         (en un workspace, repo es obligatorio: la carpeta del repo)
  check                                  avisos de configuracion (ramas base vacias, repos faltantes,
                                         herramientas, .env.autopilot)
  entorno    <repo|clave>                valida el .env.autopilot (local/QA) sin mostrar valores
  log        <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
  query      [estado]                    JSON con las tareas
  plan       [--recuperar]               lo que usa el watcher (--recuperar: solo al iniciar)
  sesion     <clave> <ses_id>            registra la sesion de OpenCode que trabaja la tarea
  notas-dev  <clave> <texto|-> [--imagenes <dir>]...   notas del coder (- = stdin)
  reporte-qa <clave> <texto|-> [--imagenes <dir>]...   reporte del QA (- = stdin)
                                         Las imagenes mencionadas en el texto (y las de --imagenes)
                                         se copian a adjuntos/<clave>/ y quedan como ![..](..) en el .md
  qa-worktree        <clave>             copia de trabajo aislada para el QA (en la punta de la rama)
  coder-worktree-borrar <clave>          quita los worktrees del coder y libera sus reservas
  reservar   <clave> <archivo>...        reserva archivos para la tarea (ruta en su worktree o relativa
                                         al repo principal); falla si otra tarea activa los tiene
  solapes    <clave>                     archivos que la tarea comparte con otras activas (JSON)
  esperar    <clave> <otra>              choco con <otra>: vuelve a la cola hasta que <otra> termine
  qa-worktree-borrar <clave>

<clave> = task-<numero> | bug-<numero>   (es tambien el nombre de la rama)"""

MOVER = {"in-progress": "in-progress", "qa": "qa", "validando": "validando",
         "bugfix": "bug-fix", "done": "done", "probar-e2e": "probando-e2e"}


def main(argv):
    if len(argv) < 2:
        print(USO, file=sys.stderr)
        return 1
    env, cmd, a = argv[0], argv[1], argv[2:]
    b = Board(cargar_config(env or None))

    def need(n):
        if len(a) < n:
            raise Error("faltan argumentos para '%s'.\n%s" % (cmd, USO))

    def intento_actual(clave):
        try:
            return int(b.leer(clave)[2].get("intento") or 0)
        except ValueError:
            return 0

    if cmd == "init":
        b.init()
        print(b.dir)
        return 0
    if cmd == "entorno":
        need(1)
        import entorno
        objetivo = a[0]
        if re.match(r"^(task|bug)-\d+$", objetivo.lower()):
            objetivo = [r["path"] for r in b.repos_de_tarea(b.leer(objetivo)[2])]
        elif objetivo in b.cfg["repos"]:
            objetivo = [b.cfg["repos"][objetivo]["path"]]
        else:
            objetivo = [objetivo]
        res = [entorno.validar(x) for x in objetivo]
        print(json.dumps(res if len(res) > 1 else res[0], ensure_ascii=False, indent=2))
        return 0 if all(x["estado"] == "ok" for x in res) else 3
    if cmd in ("telegram-setup", "notify-test", "notify"):
        import telegram
        return telegram.main([env, {"telegram-setup": "setup", "notify-test": "test", "notify": "send"}[cmd]] + a)
    if cmd == "health":
        import salud
        return salud.main([env] + a)
    if cmd == "test":
        import pruebas
        return pruebas.main([env] + a)
    if cmd == "check":
        for a_ in b.avisos():
            print("AVISO: " + a_)
        return 0

    b.verificar()
    if cmd in MOVER:
        need(1); b.modificar(a[0], MOVER[cmd])
    elif cmd == "reviewed":
        need(1)
        if b.buscar(a[0])[0] not in ("done", "reviewed"):
            raise Error("solo una tarea en done pasa a reviewed (%s esta en %s)" % (a[0], b.buscar(a[0])[0]))
        b.modificar(a[0], "reviewed")
        b.log("Revisada por el humano", "humano", "nota", a[0].lower(), a[0].lower(), "-", "done -> reviewed")
    elif cmd == "new":
        need(1); b.modificar(a[0], "new", secs_set={"Motivo de stopped": ""})
    elif cmd == "stopped":
        need(2); b.modificar(a[0], "stopped", secs_set={"Motivo de stopped": a[1]})
    elif cmd == "rama":
        need(2)
        repo = a[a.index("--repo") + 1] if "--repo" in a and a.index("--repo") + 1 < len(a) else None
        print(json.dumps(b.preparar_rama(a[0], a[1], repo), ensure_ascii=False)); return 0
    elif cmd == "repos-modificados":
        need(1); print(json.dumps(b.repos_modificados(a[0]), ensure_ascii=False, indent=2)); return 0
    elif cmd == "repos":
        need(1)
        t = next((t for t in b.todas() if t["id"] == a[0].lower()), None)
        if not t:
            raise Error("no existe la tarea %s" % a[0])
        print(json.dumps(t["repos"], ensure_ascii=False, indent=2)); return 0
    elif cmd == "resultado":
        need(2); b.modificar(a[0], secs_set={"Resultado": a[1]})
    elif cmd == "motivo":
        need(2); b.modificar(a[0], secs_set={"Motivo de stopped": a[1]})
    elif cmd == "feedback":
        need(2); b.modificar(a[0], secs_append={"Feedback de QA": a[1]})
    elif cmd == "criterio":
        need(2); b.modificar(a[0], secs_set={"Criterio de aceptación": a[1]})
    elif cmd == "intentos":
        need(2); b.modificar(a[0], meta_set={"intento": str(int(a[1]))})
    elif cmd == "certificar":
        need(2); b.modificar(a[0], "validando", meta_set={"intento": str(int(a[1]))})
    elif cmd == "aprobar":
        need(1)
        g = b.guardar_tests(a[0], "qa")
        n = intento_actual(a[0])
        destino = "e2e" if b.cfg["e2e"]["activo"] else "done"
        b.modificar(a[0], destino, secs_append={
            "Feedback de QA": "### Intento %d — APROBADO (%s)\n\nCertificado sin observaciones.%s"
                              % (n, ahora(), " Pasa a pruebas E2E." if destino == "e2e" else "")})
        print("ok -> %s%s" % (destino, "".join("\ntests guardados: %s @ %s" % (x["repo"], x["commit"])
                                               for x in g["guardados"]) + "".join("\nAVISO: " + x for x in g["avisos"])))
        return 0
    elif cmd == "aprobar-e2e":
        need(1)
        v = b.validar_e2e(a[0])
        if not v["ok"]:
            raise Error("no se puede aprobar en E2E: %s" % "; ".join(v["problemas"]))
        g = b.guardar_tests(a[0], "e2e")
        for x in g["guardados"]:
            print("tests guardados: %s @ %s" % (x["repo"], x["commit"]))
        for x in g["avisos"]:
            print("AVISO: " + x)
        b.modificar(a[0], "done", secs_append={
            "Feedback de E2E": "### Intento %d — APROBADO E2E (%s)\n\nProbado de punta a punta: %s."
                               % (intento_actual(a[0]), ahora(), ", ".join(
                                   "%s (%d captura/s)" % (c["criterio"], c["capturas"]) for c in v["criterios"]))})
    elif cmd == "rechazar-e2e":
        need(2)
        b.modificar(a[0], "bug-fix", secs_append={
            "Feedback de E2E": "### Intento %d — RECHAZADO EN E2E (%s)\n\n%s" % (intento_actual(a[0]), ahora(), a[1])})
    elif cmd == "re-e2e":
        need(1)
        b.modificar(a[0], "e2e", secs_set={"Motivo de stopped": ""}, secs_append={
            "Feedback de E2E": "### Re-E2E manual (%s)\n\nDe vuelta a la cola de pruebas E2E." % ahora()})
    elif cmd == "validar-e2e":
        need(1)
        v = b.validar_e2e(a[0])
        print(json.dumps(v, ensure_ascii=False, indent=2))
        return 0 if v["ok"] else 4
    elif cmd == "rechazar":
        need(2)
        n = intento_actual(a[0])
        b.modificar(a[0], "bug-fix", secs_append={
            "Feedback de QA": "### Intento %d — RECHAZADO (%s)\n\n%s" % (n, ahora(), a[1])})
    elif cmd == "reqa":
        need(1)
        b.modificar(a[0], "qa", meta_set={"intento": "0"}, secs_append={
            "Feedback de QA": "### Re-QA manual (%s)\n\nContador de intentos reiniciado." % ahora()})
    elif cmd == "add-task":
        need(6)
        print(b.crear(a[0], a[1], a[2], a[3], a[4], a[5], a[6] if len(a) > 6 else ""))
        return 0
    elif cmd == "log":
        need(3)
        a += ["-"] * (7 - len(a))
        b.log(a[0], a[1], a[2], a[3], a[4], a[5], a[6])
    elif cmd == "query":
        ts = b.todas()
        if a:
            ts = [t for t in ts if t["estado"] == a[0]]
        print(json.dumps(ts, ensure_ascii=False, indent=2))
        return 0
    elif cmd == "sesion":
        need(2); b.modificar(a[0], meta_set={"sesion": a[1]})
    elif cmd in ("notas-dev", "reporte-qa", "reporte-e2e"):
        need(2)
        texto = sys.stdin.read() if a[1] == "-" else a[1]
        if not texto.strip():
            raise Error("texto vacio para %s" % cmd)
        carpetas = [a[i + 1] for i, x in enumerate(a) if x == "--imagenes" and i + 1 < len(a)]
        seccion = {"notas-dev": "Notas del desarrollador", "reporte-qa": "Reporte de QA",
                   "reporte-e2e": "Reporte E2E"}[cmd]
        n = intento_actual(a[0])
        sub = "%s-intento%d" % ({"notas-dev": "coder", "reporte-qa": "qa", "reporte-e2e": "e2e"}[cmd], n)
        texto = b.incrustar_imagenes(a[0].lower(), b.enlazar_videos(a[0].lower(), texto, sub), carpetas, sub)
        b.modificar(a[0], secs_append={seccion: "### Intento %d (%s)\n\n%s" % (n, ahora(), texto)})
    elif cmd == "coder-worktree-borrar":
        need(1); print(json.dumps(b.coder_worktree_borrar(a[0]), ensure_ascii=False)); return 0
    elif cmd == "reservar":
        need(2)
        clave = a[0].lower()
        principal = b.repos_de_tarea(b.leer(clave)[2])[0]
        choques = []
        for f in a[1:]:
            if os.path.isabs(os.path.expanduser(f)) and reservar_ruta(f) is None \
                    and os.path.realpath(os.path.expanduser(f)).startswith(os.path.realpath(cache_kit("coder"))):
                continue
            nombre = principal["nombre"] or os.path.basename(principal["path"])
            choques += reservar(nombre, clave, [f])
        if choques:
            print(json.dumps({"choques": [{"archivo": x, "con": o} for x, o in choques]}, ensure_ascii=False))
            return 4
        print("ok")
        return 0
    elif cmd == "solapes":
        need(1); print(json.dumps(b.solapes(a[0]), ensure_ascii=False, indent=2)); return 0
    elif cmd == "esperar":
        need(2); print(json.dumps(b.esperar(a[0], a[1]), ensure_ascii=False)); return 0
    elif cmd == "qa-worktree":
        need(1); print(json.dumps(b.qa_worktree(a[0]), ensure_ascii=False)); return 0
    elif cmd == "qa-worktree-borrar":
        need(1); print(json.dumps(b.qa_worktree_borrar(a[0]), ensure_ascii=False)); return 0
    elif cmd == "smoke-save":
        need(1); print(json.dumps(b.guardar_smoke(a[0]), ensure_ascii=False)); return 0
    elif cmd == "e2e-worktree":
        need(1); print(json.dumps(b.e2e_worktree(a[0]), ensure_ascii=False, indent=2)); return 0
    elif cmd == "e2e-worktree-borrar":
        need(1); print(json.dumps(b.e2e_worktree_borrar(a[0]), ensure_ascii=False)); return 0
    elif cmd == "plan":
        print(json.dumps(b.plan(recuperar="--recuperar" in a), ensure_ascii=False))
        return 0
    else:
        print("comando desconocido: %s\n%s" % (cmd, USO), file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Error as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(3)
