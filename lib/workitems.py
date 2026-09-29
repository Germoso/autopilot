#!/usr/bin/env python3
"""
workitems.py — El tablero de workitems en carpetas + Markdown.

Unica implementacion del formato. La usan wi.sh (escritura), watcher.sh
(lectura) y azure-sync.py (alta de tareas). Solo stdlib.

ESTRUCTURA
  $WORKITEMS_DIR/
    new/ in-progress/ qa/ validando/ bug-fix/ stopped/ done/
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

ESTADOS = ["new", "in-progress", "qa", "validando", "bug-fix", "stopped", "done", "reviewed"]
# Tareas que ya no estan activas. `reviewed` = done que el humano ya reviso (lo mueve el humano).
CERRADAS = ("done", "stopped", "reviewed")
PRIO = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
TIPOS = ("task", "bug")
SECCIONES = ["Descripción", "Criterio de aceptación", "Adjuntos", "Notas del desarrollador",
             "Reporte de QA", "Feedback de QA", "Resultado", "Motivo de stopped"]
# Dos puestos que trabajan en paralelo, cada uno con UNA tarea como maximo.
PUESTOS = {"coder": "in-progress", "qa": "validando"}
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
    capacidad = ({"coder": entero("MAX_CODERS", 2), "qa": entero("MAX_QA", 2)} if paralelo
                 else {"coder": 1, "qa": 1})
    return {"workspace": bool(ws), "raiz": raiz, "dir": wdir, "repos": repos,
            "paralelo": paralelo, "capacidad": capacidad,
            "parallel_invalido": None if valor_parallel in ("true", "false") else vals.get("PARALLEL"),
            "vigia": {"activo": vals.get("WATCHDOG", "true").strip().lower() != "false",
                      "intervalo": entero("WATCHDOG_INTERVAL", 60), "hung_min": entero("HUNG_MINUTES", 10),
                      "stale_min": entero("STALE_MINUTES", 45), "timeout": entero("COMMAND_TIMEOUT", 900)}}


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
        for n, r in sorted(self.cfg["repos"].items()):
            etiqueta = "REPO.%s" % n if n else "BASE_BRANCH"
            if not r["base"]:
                out.append("%s vacia: define la rama base" % etiqueta)
            elif not os.path.isdir(r["path"]):
                out.append("%s: no existe la carpeta %s" % (etiqueta, r["path"]))
            else:
                import entorno
                e = entorno.validar(r["path"])
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
            "reporte_qa": secs.get("Reporte de QA", ""),
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
        if estado_nuevo in CERRADAS:
            self._cerrar_coder(clave.lower(), estado_nuevo)
        return path

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
                          "Re-encolar manualmente a new o qa." % t["estado"])
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
        bugfix, qa, nuevas = by("bug-fix"), by("qa"), by("new")
        cap = self.cfg["capacidad"]

        acciones = []
        huecos = cap["coder"] - len(ocupados["coder"])
        for t in [t for t in bugfix if libre(t)] + [t for t in nuevas if libre(t)]:
            if huecos <= 0:
                break
            acciones.append({"puesto": "coder", "tarea": t,
                             "accion": "desarrollar-bugfix" if t["estado"] == "bug-fix" else "desarrollar"})
            huecos -= 1
        for t in qa[:max(0, cap["qa"] - len(ocupados["qa"]))]:
            acciones.append({"puesto": "qa", "accion": "certificar", "tarea": t})
        return {"acciones": acciones, "terminadas": terminadas, "ocupados": ocupados,
                "capacidad": cap, "parallel": self.cfg["paralelo"],
                "en_espera": [{"id": t["id"], "espera": t["espera"]} for t in bugfix + nuevas if not libre(t)],
                "huerfanas_recuperadas": huerfanas, "stopped": [t["id"] for t in by("stopped")],
                "workspace": self.cfg["workspace"], "avisos": self.avisos(),
                "cola": {"bugfix": len(bugfix), "qa": len(qa), "new": len(nuevas)}}

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
  resultado  <clave> <texto>
  motivo     <clave> <texto>
  feedback   <clave> <texto>             agrega al historial de Feedback de QA
  criterio   <clave> <texto>
  intentos   <clave> <n>
  certificar <clave> <intento_nuevo>     qa -> validando, fija Intento
  aprobar    <clave>                     validando -> done
  rechazar   <clave> <feedback>          validando -> bug-fix
  reqa       <clave>                     -> qa, Intento a 0 (conserva el historial)
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
         "bugfix": "bug-fix", "done": "done"}


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
        n = intento_actual(a[0])
        b.modificar(a[0], "done", secs_append={
            "Feedback de QA": "### Intento %d — APROBADO (%s)\n\nCertificado sin observaciones." % (n, ahora())})
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
    elif cmd in ("notas-dev", "reporte-qa"):
        need(2)
        texto = sys.stdin.read() if a[1] == "-" else a[1]
        if not texto.strip():
            raise Error("texto vacio para %s" % cmd)
        carpetas = [a[i + 1] for i, x in enumerate(a) if x == "--imagenes" and i + 1 < len(a)]
        seccion = "Notas del desarrollador" if cmd == "notas-dev" else "Reporte de QA"
        n = intento_actual(a[0])
        texto = b.incrustar_imagenes(a[0].lower(), texto, carpetas,
                                     "%s-intento%d" % ("coder" if cmd == "notas-dev" else "qa", n))
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
