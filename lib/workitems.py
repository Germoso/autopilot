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

EL BOARD NO VA EN GIT. Si viviera en el repo, cada cambio de rama del worker
cambiaria el tablero. install.sh --init lo agrega al .gitignore.
"""
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import unicodedata

ESTADOS = ["new", "in-progress", "qa", "validando", "bug-fix", "stopped", "done"]
PRIO = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
TIPOS = ("task", "bug")
SECCIONES = ["Descripción", "Criterio de aceptación", "Adjuntos", "Feedback de QA",
             "Resultado", "Motivo de stopped"]
IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"}
CAMPOS = ["id", "tipo", "prioridad", "intento", "rama", "repo", "origen", "actualizado"]

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
    return {"workspace": bool(ws), "raiz": raiz, "dir": wdir, "repos": repos}


# ----------------------------------------------------------------- util
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
        for n, r in sorted(self.cfg["repos"].items()):
            etiqueta = "REPO.%s" % n if n else "BASE_BRANCH"
            if not r["base"]:
                out.append("%s vacia: define la rama base" % etiqueta)
            elif not os.path.isdir(r["path"]):
                out.append("%s: no existe la carpeta %s" % (etiqueta, r["path"]))
        return out

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
                r = self.repo_de(t["repo"])
                t["repo_path"], t["base"] = r["path"], r["base"]
            except Error as err:
                t["repo_error"] = str(err)
            out.append(t)
        return out

    # -- escritura
    def modificar(self, clave, estado_nuevo=None, meta_set=None, secs_set=None, secs_append=None):
        """Mueve (si corresponde) y reescribe una tarea. Primero rename, luego replace."""
        with self.lock():
            estado, path = self.buscar(clave)
            if estado_nuevo and estado_nuevo != estado:
                if estado_nuevo not in ESTADOS:
                    raise Error("estado invalido: %s" % estado_nuevo)
                destino = os.path.join(self.dir, estado_nuevo, os.path.basename(path))
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                os.rename(path, destino)
                path = destino
            meta, titulo, secs = parsear(open(path, encoding="utf-8").read())
            for k, v in (meta_set or {}).items():
                meta[k] = v
            for k, v in (secs_set or {}).items():
                secs[k] = v
            for k, v in (secs_append or {}).items():
                prev = secs.get(k, "").strip()
                secs[k] = (prev + "\n\n" + v).strip() if prev else v
            meta["actualizado"] = ahora()
            escribir_atomico(path, serializar(meta, titulo, secs))
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
        """Lo que el watcher le devuelve al agente. Prioridad: Bug Fix > QA > New."""
        huerfanas = []
        if recuperar:
            for t in self.todas():
                if t["estado"] in ("in-progress", "validando"):
                    motivo = ("Huerfana en %s sin agente activo (recuperada por el watcher). "
                              "Re-encolar manualmente a new o qa." % t["estado"])
                    self.modificar(t["id"], "stopped", secs_set={"Motivo de stopped": motivo})
                    self.log("Watcher recupero tarea huerfana", "watcher", "recuperacion",
                             t["id"], t["rama"], "-", "Estaba en %s sin agente. Marcada stopped." % t["estado"])
                    huerfanas.append(t["id"])

        ts = self.todas()
        orden = lambda t: (PRIO.get(t["prioridad"], 9), int(t["numero"]))
        by = lambda s: sorted([t for t in ts if t["estado"] == s], key=orden)
        bugfix, qa, nuevas = by("bug-fix"), by("qa"), by("new")

        if bugfix:
            accion, elegida = "desarrollar-bugfix", bugfix[0]
        elif qa:
            accion, elegida = "certificar", qa[0]
        elif nuevas:
            accion, elegida = "desarrollar", nuevas[0]
        else:
            accion, elegida = "idle", None
        return {"accion": accion, "tarea": elegida, "huerfanas_recuperadas": huerfanas,
                "stopped": [t["id"] for t in by("stopped")],
                "workspace": self.cfg["workspace"], "avisos": self.avisos(),
                "cola": {"bugfix": len(bugfix), "qa": len(qa), "new": len(nuevas)}}

    # -- git
    def git(self, repo, *args, check=True):
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise Error("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:300]))
        return r

    def preparar_rama(self, clave, modo):
        """Deja el repo parado en la rama de la tarea.

        modo=nueva      crea <clave> desde BASE_BRANCH (obligatoria). Si ya existe, error (no se pisa trabajo).
        modo=existente  cambia a <clave>, que debe existir (ciclo de Bug Fix).

        Si falla, la tarea pasa a stopped con el motivo y se lanza Error.
        Nunca hace push, merge, rebase ni borra ramas.
        """
        clave = clave.lower()
        try:
            r = self.repo_de(self.leer(clave)[2].get("repo"))
            repo, base = r["path"], r["base"]
            if not base:
                raise Error("falta la rama base en autopilot.env (%s): define desde que rama se crean las ramas"
                            % ("REPO.%s" % r["nombre"] if r["nombre"] else "BASE_BRANCH"))
            if self.git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
                raise Error("%s no es un repositorio git" % repo)
            # Solo cuentan archivos rastreados: los untracked (.env, etc.) viajan entre ramas sin problema.
            if self.git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
                raise Error("hay cambios sin commitear en archivos rastreados; no se cambia de rama")
            existe = lambda ref: self.git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
            if modo == "nueva":
                if existe("refs/heads/%s" % clave):
                    raise Error("la rama %s ya existe; no se recrea para no pisar trabajo previo" % clave)
                if existe("refs/heads/%s" % base):
                    origen = base
                elif existe("refs/remotes/origin/%s" % base):
                    origen = "origin/%s" % base
                else:
                    raise Error("no existe la rama base '%s' (ni local ni origin/%s)" % (base, base))
                self.git(repo, "switch", "--no-track", "-c", clave, origen)
            elif modo == "existente":
                if not existe("refs/heads/%s" % clave):
                    raise Error("la rama %s no existe; no se puede continuar el Bug Fix" % clave)
                self.git(repo, "switch", clave)
            else:
                raise Error("modo invalido: %s (nueva|existente)" % modo)
        except Error as e:
            self.modificar(clave, "stopped", secs_set={"Motivo de stopped": str(e)})
            self.log("No se pudo preparar la rama", "sistema", "Stopped", clave, clave, "-", str(e))
            raise
        self.modificar(clave, meta_set={"rama": clave})
        return {"rama": clave, "base": base, "repo": r["nombre"] or os.path.basename(repo), "repo_path": repo,
                "head": self.git(repo, "rev-parse", "--short", "HEAD").stdout.strip()}


# ----------------------------------------------------------------- CLI
USO = """uso: wi.sh <env> <comando> [args]
  init                                   crea las carpetas del board y log.md
  in-progress|qa|validando|bugfix|done|new <clave>
  stopped    <clave> <motivo>
  rama       <clave> nueva|existente     crea/cambia a la rama <clave> (desde BASE_BRANCH)
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
  check                                  avisos de configuracion (ramas base vacias, repos faltantes)
  log        <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
  query      [estado]                    JSON con las tareas
  plan       [--recuperar]               lo que usa el watcher

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
    if cmd == "check":
        for a_ in b.avisos():
            print("AVISO: " + a_)
        return 0

    b.verificar()
    if cmd in MOVER:
        need(1); b.modificar(a[0], MOVER[cmd])
    elif cmd == "new":
        need(1); b.modificar(a[0], "new", secs_set={"Motivo de stopped": ""})
    elif cmd == "stopped":
        need(2); b.modificar(a[0], "stopped", secs_set={"Motivo de stopped": a[1]})
    elif cmd == "rama":
        need(2); print(json.dumps(b.preparar_rama(a[0], a[1]), ensure_ascii=False)); return 0
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
