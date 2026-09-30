#!/usr/bin/env python3
"""
init.py — Prepara un proyecto (un repo) o un workspace (carpeta con varios repos).

Lo usan /autopilot-init (desde el agente) e install.sh --init. Detecta el modo solo:
  - la carpeta es un repo git              -> modo un repo
  - la carpeta contiene repos git adentro  -> modo workspace (board unico en la carpeta)

uso:
  init.py <carpeta> --detect                    JSON: modo, repos, ramas, base sugerida
  init.py <carpeta> [--base <rama>]             modo un repo
  init.py <carpeta> [--base <repo>=<rama>]...   modo workspace (una por repo)

Que hace:
  - crea autopilot.env si no existe. --base actualiza la rama base aunque el archivo ya exista.
  - crea el board .workitems/
  - nada entra al repo: en modo un repo ignora lo del kit en .git/info/exclude
  - prohibe push/merge al agente principal (OpenCode / Claude Code, los que esten instalados)
  - reporta avisos: ramas base vacias o inexistentes, herramientas y .env.autopilot
  - propone la config E2E (E2E_CLIENTS, E2E_PLATFORMS, E2E_API) con E2E=false; si autopilot.env ya
    existia y no tiene E2E=, le agrega ese bloque al final
"""
import json
import os
import re
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import workitems as wi  # noqa: E402

PREFERIDAS = ["develop", "dev", "main", "master"]
IGNORAR = [".workitems/", "autopilot.env", "*.secrets.env", ".claude/settings.local.json",
           ".env.autopilot", ".env.autopilot.e2e", "cuentas-e2e.env", "test-results/"]


def git(path, *args):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def es_repo(path):
    return git(path, "rev-parse", "--show-toplevel") == os.path.realpath(path)


def info_repo(path):
    ramas = sorted({l.strip()[len("origin/"):] for l in (git(path, "branch", "-r", "--format=%(refname:short)") or "").splitlines()
                    if l.strip().startswith("origin/") and l.strip() != "origin/HEAD" and l.strip() != "origin"})
    locales = (git(path, "branch", "--format=%(refname:short)") or "").split()
    head_remoto = (git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "").replace("origin/", "")
    sugerida = next((b for b in PREFERIDAS if b in ramas or b in locales), head_remoto or None)
    return {"nombre": os.path.basename(os.path.abspath(path)), "path": os.path.abspath(path),
            "rama_actual": git(path, "branch", "--show-current"), "ramas_remotas": ramas,
            "sugerida": sugerida,
            "sucio": bool(git(path, "status", "--porcelain", "--untracked-files=no"))}


def detectar(carpeta):
    carpeta = os.path.abspath(carpeta)
    if es_repo(carpeta):
        return {"modo": "repo", "carpeta": carpeta, "repos": [info_repo(carpeta)]}
    subs = [os.path.join(carpeta, d) for d in sorted(os.listdir(carpeta))
            if not d.startswith(".") and os.path.isdir(os.path.join(carpeta, d)) and es_repo(os.path.join(carpeta, d))]
    if not subs:
        raise wi.Error("%s no es un repo git ni contiene repos git" % carpeta)
    return {"modo": "workspace", "carpeta": carpeta, "repos": [info_repo(s) for s in subs]}


# ----------------------------------------------------------------- .env
def set_linea(path, clave, valor):
    """Fija clave=valor en un .env, reemplazando la linea si existe o agregandola al final."""
    lineas = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    hecho = False
    for i, l in enumerate(lineas):
        if l.split("=", 1)[0].strip() == clave:
            lineas[i], hecho = "%s=%s" % (clave, valor), True
    if not hecho:
        lineas.append("%s=%s" % (clave, valor))
    open(path, "w", encoding="utf-8").write("\n".join(lineas) + "\n")


def env_autopilot(det, bases):
    L = ["# autopilot.env — generado por /autopilot-init. Editable a mano.", ""]
    if det["modo"] == "repo":
        L += ["# Rama desde la que se crea la rama de cada workitem (task-<n> / bug-<n>). OBLIGATORIA.",
              "BASE_BRANCH=%s" % bases.get("", "")]
    else:
        L += ["# Workspace: un repo por linea, REPO.<carpeta>=<rama base>. OBLIGATORIA para cada repo.",
              "# Cada tarea del board indica su repo (repo: <carpeta>) y su rama se crea dentro de ese repo.",
              "# Para sacar un repo del sistema, borra su linea."]
        L += ["REPO.%s=%s" % (r["nombre"], bases.get(r["nombre"], "")) for r in det["repos"]]
    L += ["", "# Carpeta del board. Vacio = .workitems/ junto a este archivo.", "WORKITEMS_DIR=",
          "", "# Segundos entre lecturas del board.", "POLL_INTERVAL=5",
          "", "# Paralelismo: false = 1 coder y 1 QA a la vez. true = hasta MAX_CODERS y MAX_QA, cada uno con un",
          "# workitem distinto, en su propia copia del repo; dos workitems nunca tocan el mismo archivo.",
          "# Cada agente gasta tokens y memoria (Flutter ~1,5-2 GB por analisis/test).",
          "PARALLEL=false", "MAX_CODERS=2", "MAX_QA=2",
          "", "# Vigilante (lo corre el watcher cada WATCHDOG_INTERVAL s, sin tokens): mata procesos huerfanos",
          "# y los colgados HUNG_MINUTES sin usar CPU; avisa de tareas sin actividad STALE_MINUTES.",
          "# COMMAND_TIMEOUT: tiempo maximo (s) de lo que corre por aenv.sh.",
          "WATCHDOG=true", "WATCHDOG_INTERVAL=60", "HUNG_MINUTES=10", "STALE_MINUTES=45", "COMMAND_TIMEOUT=900",
          "", "# Telegram: avisos (y comandos /estado, /reqa, /pausa... desde el chat). Bot propio del autopilot:",
          "# wi.sh autopilot.env telegram-setup. ALERTS_ONLY=true: solo lo que necesita tu intervencion.",
          "TELEGRAM=false", "TELEGRAM_ALERTS_ONLY=false",
          "", "# Cadena detenida: avisa por Telegram si el autopilot queda parado esperandote",
          "# (sin puestos ocupados y pendiente que solo el humano destraba). CADENA_MIN: minutos de",
          "# espera antes de avisar; CADENA_REAVISO_MIN: cada cuanto re-avisar mientras siga parado.",
          "CADENA_MIN=20", "CADENA_REAVISO_MIN=240"]
    return "\n".join(L) + "\n" + bloque_e2e(det)


RE_BASEURL = re.compile(r"^((?:final|const|var|late final|static (?:final|const))\s+(?:String\s+)?"
                        r"(?:baseUrl|baseURL|apiUrl|apiURL|kBaseUrl)\s*=)\s*(.+);\s*$")


def api_flutter(path):
    """Sugerencia de E2E_API para una app Flutter: la linea `final baseUrl = ...;` de lib/."""
    for raiz, dirs, files in os.walk(os.path.join(path, "lib")):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.endswith(".dart"):
                continue
            ruta = os.path.join(raiz, f)
            for l in open(ruta, encoding="utf-8", errors="replace"):
                m = RE_BASEURL.match(l.rstrip("\n"))
                if m:
                    pre = m.group(1)
                    return "%s|^%s .*;$|%s \"{API}\";" % (os.path.relpath(ruta, path), re.escape(pre).replace("\\ ", " "), pre)
    return None


def vars_url_web(path):
    """Variables de un front web (en sus .env) que apuntan al backend: VITE_API_URL, VITE_WEBSOCKET_URL..."""
    import entorno
    claves = set()
    for n in (".env", ".env.local", ".env.autopilot"):
        claves |= set(entorno.leer(os.path.join(path, n)))
    return sorted(k for k in claves if re.search(r"(API|BACKEND|SERVER|SOCKET|WS).*(URL|URI|HOST)|BASE_URL", k, re.I))


def bloque_e2e(det):
    """Config E2E sugerida (apagada): que front consume que backend, plataformas y como apuntar las apps."""
    import e2e
    tipos = {r["nombre"]: e2e.tipo_repo(r["path"]) for r in det["repos"]}
    backs = [n for n, t in tipos.items() if t == "backend"]
    fronts = [n for n, t in tipos.items() if t in ("flutter", "web")]
    L = ["", "# ---- Pruebas E2E (agente e2e-tester, despues del QA). Antes de activar: e2e-setup.sh y las cuentas",
         "# de prueba (E2E_<ROL>_USER / E2E_<ROL>_PASSWORD) en cuentas-e2e.env junto a este archivo (NO aqui:",
         "# este archivo no lleva contrasenas). Los backends usan su .env.autopilot (base de QA). Ver README.",
         "E2E=false", "MAX_E2E=1", "E2E_COMMAND_TIMEOUT=2400"]
    if det["modo"] == "workspace" and backs:
        L.append("# Que frontends consumen cada backend (revisalo: se dedujo por el nombre).")
        usados = set()
        for b in backs:
            base = re.sub(r"[_-](BE|be|backend|Backend|api|API)$", "", b)
            fs = [f for f in fronts if f == base]
            usados |= set(fs)
            L.append("E2E_CLIENTS.%s=%s" % (b, ",".join(fs)))
        sueltos = [f for f in fronts if f not in usados]
        if sueltos:
            L.append("# Sin backend deducido (agregalos al E2E_CLIENTS que corresponda): %s" % ", ".join(sueltos))
    for f in fronts:
        plats = "web"
        if tipos[f] == "flutter":
            main = os.path.join(next(r["path"] for r in det["repos"] if r["nombre"] == f), "lib", "main.dart")
            txt = open(main, encoding="utf-8", errors="replace").read() if os.path.isfile(main) else ""
            # Firebase sin opciones de web: la app no arranca en navegador -> solo android
            plats = "android" if re.search(r"Firebase\.initializeApp\(\s*\)", txt) else "web,android"
        L.append("E2E_PLATFORMS.%s=%s" % (f, plats))
    L.append("# Internet abierto en navegador y emulador; se bloquean los servidores de produccion detectados en")
    L.append("# los .env y el config de la app. Otros a mano: E2E_BLOCK_HOSTS=host1,host2")
    for r in det["repos"]:
        if tipos[r["nombre"]] == "flutter":
            api = api_flutter(r["path"])
            L.append("E2E_API.%s=%s" % (r["nombre"], api) if api else
                     "# E2E_API.%s=<archivo>|<regex de la linea de la URL>|<reemplazo con {API}>" % r["nombre"])
        elif tipos[r["nombre"]] == "web":
            vs = vars_url_web(r["path"])
            L.append("E2E_API.%s=env:%s" % (r["nombre"], ",".join(vs)) if vs else
                     "# E2E_API.%s=env:<variables de URL del backend, p. ej. VITE_API_URL>" % r["nombre"])
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------- clientes
def clientes_instalados():
    home = os.path.expanduser("~")
    out = []
    if os.path.isdir(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "opencode")):
        out.append("opencode")
    if os.path.isdir(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")):
        out.append("claude")
    return out


def init(carpeta, bases):
    det = detectar(carpeta)
    raiz, hecho, avisos = det["carpeta"], [], []
    nombres = {r["nombre"] for r in det["repos"]}
    for k in bases:
        if det["modo"] == "workspace" and k not in nombres:
            raise wi.Error("--base %s=...: no hay un repo '%s' en %s. Repos: %s" % (k, k, raiz, ", ".join(sorted(nombres))))

    ap = os.path.join(raiz, "autopilot.env")
    if not os.path.exists(ap):
        open(ap, "w", encoding="utf-8").write(env_autopilot(det, bases))
        hecho.append("autopilot.env creado")
    else:
        hecho.append("autopilot.env ya existia (solo se actualizan las ramas base indicadas)")
        for k, v in bases.items():
            set_linea(ap, "REPO.%s" % k if k else "BASE_BRANCH", v)
        if not re.search(r"(?m)^\s*TELEGRAM\s*=", open(ap, encoding="utf-8").read()):
            with open(ap, "a", encoding="utf-8") as f:
                f.write("\n# Telegram: avisos (y comandos /estado, /reqa, /pausa... desde el chat). Bot propio del autopilot:\n"
                        "# wi.sh autopilot.env telegram-setup. ALERTS_ONLY=true: solo lo que necesita tu intervencion.\n"
                        "TELEGRAM=false\nTELEGRAM_ALERTS_ONLY=false\n")
            hecho.append("autopilot.env: agregado TELEGRAM=false (avisos por Telegram, apagados)")
        if not re.search(r"(?m)^\s*E2E\s*=", open(ap, encoding="utf-8").read()):
            with open(ap, "a", encoding="utf-8") as f:
                f.write(bloque_e2e(det))
            hecho.append("autopilot.env: agregada la config E2E sugerida (E2E=false; revisala antes de activar)")
    for k, v in bases.items():
        hecho.append("rama base %s= %s" % ("REPO.%s" % k if k else "BASE_BRANCH", v))

    b = wi.Board(wi.cargar_config(ap))
    b.init()
    hecho.append("board en %s" % b.dir)

    # Nada del kit entra al repo: en modo un repo, exclude local (no el .gitignore del equipo).
    # En un workspace la carpeta padre no es un repo y dentro de los repos no se escribe nada.
    ignorar = list(IGNORAR)
    render = os.path.join(KIT, "render.py")
    for c in clientes_instalados():
        if c == "opencode" and det["modo"] == "repo" and \
                subprocess.run(["git", "-C", raiz, "ls-files", "--error-unmatch", "opencode.json"],
                               capture_output=True).returncode == 0:
            avisos.append("opencode.json esta versionado: no se toca; en OpenCode el bloqueo de push/merge "
                          "queda solo en los subagentes")
            continue
        if c == "opencode":
            ignorar.append("opencode.json")
        subprocess.run([sys.executable, render, "project", c, raiz, KIT], check=True, capture_output=True)
        hecho.append("%s: push/merge prohibidos al agente principal" % c)
    if det["modo"] == "repo":
        ex = git(raiz, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
        os.makedirs(os.path.dirname(ex), exist_ok=True)
        actual = open(ex).read().splitlines() if os.path.exists(ex) else []
        nuevos = [p for p in ignorar if p not in actual]
        if nuevos:
            open(ex, "a").write("".join(p + "\n" for p in nuevos))
            hecho.append("ignorado solo en esta copia (.git/info/exclude): %s" % ", ".join(nuevos))

    for aviso in b.avisos():
        avisos.append(aviso)
    for nombre, r in sorted(b.cfg["repos"].items()):
        if r["base"] and os.path.isdir(r["path"]) and not (
                git(r["path"], "rev-parse", "--verify", "--quiet", "refs/heads/" + r["base"]) or
                git(r["path"], "rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + r["base"])):
            avisos.append("%s: la rama '%s' no existe (ni local ni en origin)" % (nombre or "repo", r["base"]))
    for r in det["repos"]:
        if r["sucio"]:
            avisos.append("%s tiene cambios sin commitear en tu copia (no afecta al autopilot, que trabaja en su "
                          "propia copia; es solo informativo)"
                          % r["nombre"])
    return {"modo": det["modo"], "carpeta": raiz, "hecho": hecho, "avisos": avisos}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    carpeta, resto = argv[0], argv[1:]
    try:
        if "--detect" in resto:
            print(json.dumps(detectar(carpeta), ensure_ascii=False, indent=2))
            return 0
        bases, i = {}, 0
        while i < len(resto):
            if resto[i] == "--base" and i + 1 < len(resto):
                k, sep, v = resto[i + 1].partition("=")
                bases.update({k.strip(): v.strip()} if sep else {"": k.strip()})
                i += 2
            elif resto[i] == "--sin-azure":  # compatibilidad: el init ya no crea nada de integraciones
                i += 1
            else:
                raise wi.Error("argumento desconocido: %s" % resto[i])
        det_modo = detectar(carpeta)["modo"]
        if det_modo == "repo" and any(bases):
            raise wi.Error("es un repo unico: usa --base <rama> (sin repo=)")
        if det_modo == "workspace" and "" in bases:
            raise wi.Error("es un workspace: usa --base <repo>=<rama> para cada repo")
        print(json.dumps(init(carpeta, bases), ensure_ascii=False, indent=2))
        return 0
    except wi.Error as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
