#!/usr/bin/env python3
"""
init.py — Prepara un proyecto (un repo) o un workspace (carpeta con varios repos).

Lo usan /autopilot-init (desde el agente) e install.sh --init. Detecta el modo solo:
  - la carpeta es un repo git              -> modo un repo
  - la carpeta contiene repos git adentro  -> modo workspace (board unico en la carpeta)

uso:
  init.py <carpeta> --detect                    JSON: modo, repos, ramas, base sugerida, Azure
  init.py <carpeta> [--base <rama>]             modo un repo
  init.py <carpeta> [--base <repo>=<rama>]...   modo workspace (una por repo)
          [--sin-azure]                         no crea azure-sync.env

Que hace:
  - crea autopilot.env y azure-sync.env si no existen (Azure deducido del remoto de cada repo,
    sprint = @current). --base actualiza la rama base aunque el archivo ya exista.
  - crea el board .workitems/
  - nada entra al repo: en modo un repo ignora lo del kit en .git/info/exclude
  - prohibe push/merge al agente principal (OpenCode / Claude Code, los que esten instalados)
  - reporta avisos: ramas base vacias o inexistentes, cambios sin commitear
"""
import json
import os
import re
import shutil
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import workitems as wi  # noqa: E402

PREFERIDAS = ["develop", "dev", "main", "master"]
IGNORAR = [".workitems/", "autopilot.env", "azure-sync.env", "*.secrets.env", ".claude/settings.local.json"]
RE_AZURE = re.compile(r"dev\.azure\.com/([^/]+)/([^/]+)/_git/|([^/.]+)\.visualstudio\.com/([^/]+)/_git/")


def git(path, *args):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def es_repo(path):
    return git(path, "rev-parse", "--show-toplevel") == os.path.realpath(path)


def info_repo(path):
    remoto = git(path, "remote", "get-url", "origin") or ""
    ramas = sorted({l.strip()[len("origin/"):] for l in (git(path, "branch", "-r", "--format=%(refname:short)") or "").splitlines()
                    if l.strip().startswith("origin/") and l.strip() != "origin/HEAD" and l.strip() != "origin"})
    locales = (git(path, "branch", "--format=%(refname:short)") or "").split()
    head_remoto = (git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "").replace("origin/", "")
    sugerida = next((b for b in PREFERIDAS if b in ramas or b in locales), head_remoto or None)
    m = RE_AZURE.search(remoto)
    azure = None
    if m:
        org, proyecto = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        azure = {"org": org, "project": re.sub(r"%20", " ", proyecto)}
    return {"nombre": os.path.basename(os.path.abspath(path)), "path": os.path.abspath(path),
            "rama_actual": git(path, "branch", "--show-current"), "ramas_remotas": ramas,
            "sugerida": sugerida, "azure": azure,
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
          "", "# Segundos entre lecturas del board.", "POLL_INTERVAL=5", ""]
    return "\n".join(L)


def env_azure(det):
    fuentes = [r for r in det["repos"] if r["azure"]]
    if not fuentes:
        return None
    org = fuentes[0]["azure"]["org"]
    L = ["# azure-sync.env — generado por /autopilot-init desde los remotos de git. Editable a mano.",
         "# El PAT NO va aqui: azure-sync.secrets.env, AZURE_DEVOPS_PAT, o el del MCP",
         "# (~/.config/autopilot-kit/ado-mcp.secrets.env).", "",
         "AZURE_ORG=%s" % org, ""]
    if det["modo"] == "repo":
        L += ["# Sprint: ruta (Proyecto\\Sprint X) o @current = sprint actual del equipo '<Proyecto> Team'",
              "# (@current:<Equipo> para otro equipo).",
              "AZURE_PROJECT=%s" % fuentes[0]["azure"]["project"], "AZURE_ITERATION=@current"]
    else:
        L += ["# Una fuente por repo: SYNC.<carpeta>=<proyecto de Azure>|<sprint>",
              "# Sprint: ruta (Proyecto\\Sprint X) o @current = sprint actual del equipo '<Proyecto> Team'",
              "# (@current:<Equipo> para otro). Para no importar de un repo, borra su linea."]
        L += ["SYNC.%s=%s|@current" % (r["nombre"], r["azure"]["project"]) for r in fuentes]
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


def init(carpeta, bases, sin_azure=False):
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
    for k, v in bases.items():
        hecho.append("rama base %s= %s" % ("REPO.%s" % k if k else "BASE_BRANCH", v))

    az = os.path.join(raiz, "azure-sync.env")
    if not sin_azure and not os.path.exists(az):
        contenido = env_azure(det)
        if contenido:
            open(az, "w", encoding="utf-8").write(contenido)
            hecho.append("azure-sync.env creado (sprint @current)")
        else:
            avisos.append("ningun repo tiene remoto de Azure DevOps: no se creo azure-sync.env")

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
    if os.path.exists(os.path.join(raiz, "azure-sync.env")) and not shutil.which("ffmpeg"):
        avisos.append("falta ffmpeg: los videos de los work items se descargan pero sin fotogramas, "
                      "y el agente no los puede ver (sudo apt install ffmpeg)")
    for r in det["repos"]:
        if r["sucio"]:
            avisos.append("%s tiene cambios sin commitear: el autopilot no cambiara de rama ahi hasta resolverlos"
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
            elif resto[i] == "--sin-azure":
                i += 1
            else:
                raise wi.Error("argumento desconocido: %s" % resto[i])
        det_modo = detectar(carpeta)["modo"]
        if det_modo == "repo" and any(bases):
            raise wi.Error("es un repo unico: usa --base <rama> (sin repo=)")
        if det_modo == "workspace" and "" in bases:
            raise wi.Error("es un workspace: usa --base <repo>=<rama> para cada repo")
        print(json.dumps(init(carpeta, bases, "--sin-azure" in resto), ensure_ascii=False, indent=2))
        return 0
    except wi.Error as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
