#!/usr/bin/env python3
"""
render.py — Genera la configuracion de cada cliente desde una sola fuente.

Fuente unica:  agents/*.md  (frontmatter neutro: name, description, role)
Salida:
  opencode  <cfg>/agents/<name>.md    permisos de bash por patron (permission.bash)
            <cfg>/commands/<cmd>.md   /autopilot-init, /autopilot-plan, /autopilot y /autopilot-web
  claude    <cfg>/agents/<name>.md    hook PreToolUse -> git-guard.sh <role>
            (sin commands: en Claude Code las skills ya son esos comandos)
  pi        <cfg>/agents/<name>.md    frontmatter de pi (async, tools, subagentOnlyExtensions)
                                      + guard real: extension pi-guard-<role>.mjs del kit, que
                                      intercepta tool_call y cancela lo prohibido (git-guard.sh)
            (sin commands: en pi las skills ya son esos comandos, /skill:<nombre>)

Todo archivo generado lleva la marca MARCA en el frontmatter; uninstall solo
borra archivos con esa marca.

uso:
  render.py install   <opencode|claude|pi> <cfg_dir> <kit_dir>
  render.py uninstall <opencode|claude|pi> <cfg_dir>
  render.py project   <opencode|claude|pi> <proyecto> <kit_dir>   protege push/merge en el proyecto
"""
import glob
import json
import os
import shlex
import shutil
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
KIT_SRC = os.path.dirname(AQUI)
# oc_sesion.py: en el repo esta en lib/; instalado, junto a este archivo.
sys.path[:0] = [AQUI, os.path.join(KIT_SRC, "lib")]
import oc_sesion  # noqa: E402
MARCA = "# generado por autopilot-kit (install.sh). No editar: se regenera."

# Comandos de git prohibidos por rol. Mismo criterio que lib/git-guard.sh.
BASE = ["git push", "git merge", "git pull", "gh pr merge"]
DENY = {
    "coder": BASE + ["git rebase", "git branch -d", "git branch -D", "git branch --delete",
                      "git reset --hard", "git switch", "git checkout -b", "git checkout -B"],
    "qa": BASE + ["git rebase", "git commit", "git add", "git switch", "git checkout", "git reset",
                  "git stash", "git cherry-pick", "git revert", "git branch -d", "git branch -D",
                  "git branch --delete"],
}
DENY["e2e"] = DENY["qa"]

# Nunca contra produccion (mismo criterio que git-guard.sh): lo que se conecta a un ambiente solo
# pasa envuelto en aenv.sh, que valida el .env.autopilot del humano. OpenCode: gana la ultima regla.
AMBIENTE_DENY = ["npm run *", "npm start*", "npm test*", "npm t *", "npm exec *", "npx *", "yarn *", "pnpm *",
                 "node *", "nest *", "jest*", "vitest*", "ts-node *", "tsx *", "prisma *", "typeorm *",
                 "sequelize *", "knex *", "nodemon *", "*migrat*", "*seed*", "flutter run*", "flutter drive*",
                 "fvm flutter run*", "fvm flutter drive*", "*integration_test*", "curl http*", "wget http*",
                 "*> .env*", "*>.env*", "cp *.env*", "mv *.env*", "sed *.env*", "tee *.env*"]
# E2E: apps, emulador y navegador solo via e2e.sh (apunta al backend local y corta la red a produccion).
E2E_DENY = ["flutter build*", "fvm flutter build*", "flutter install*", "fvm flutter install*", "*playwright*",
            "emulator *", "*qemu-system*", "adb *install*", "*aenv.sh*flutter*", "*aenv.sh*playwright*"]
AMBIENTE_ALLOW = ["npm run build*", "npm run lint*", "npm run format*", "npm run typecheck*", "npx tsc*",
                  "npx eslint*", "npx prettier*", "yarn install*", "yarn build*", "yarn lint*", "pnpm install*",
                  "curl http://localhost*", "curl http://127.0.0.1*", "*aenv.sh *"]

COMANDOS = {
    "autopilot-init": "Prepara esta carpeta (repo o workspace de varios repos) para el autopilot: rama base y board",
    "autopilot-plan": "Convierte una idea o un documento en tareas del board: brainstorming hasta tenerlo claro, desglose y alta",
    "autopilot": "Enciende el watcher del sistema autonomo sobre el board de workitems de este proyecto",
    "autopilot-web": "Arranca y gestiona la app web del autopilot (tablero en el navegador): la levanta desacoplada, detecta si ya corre, la detiene o la rearranca (lan, puerto)",
}


def leer_agente(path):
    txt = open(path, encoding="utf-8").read()
    assert txt.startswith("---\n"), path
    fin = txt.index("\n---\n", 4)
    meta = {}
    for line in txt[4:fin].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, txt[fin + 5:].lstrip("\n")


def q(s):
    return json.dumps(s, ensure_ascii=False)  # string YAML valido (JSON es YAML)


def patrones(cmd):
    return [cmd, cmd + " *"]


def qa_dir(puesto="qa"):
    """Carpeta de las copias de trabajo del QA o del E2E (misma que workitems.Board.*_worktree_path)."""
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache, "autopilot-kit", puesto)


def front_opencode(meta):
    role = meta["role"]
    out = [MARCA, "description: " + q(meta["description"]), "mode: subagent", "permission:"]
    if role in ("qa", "e2e"):
        # Solo escribe pruebas temporales y capturas en sus copias de trabajo; nada mas.
        out += ["  edit:", '    "*": deny', "    %s: allow" % q(qa_dir(role) + "/**"),
                "    %s: deny" % q(qa_dir(role) + "/.api/**")]
    else:
        out += ["  edit:", '    "*": allow']
    # Nadie escribe .env* (salvo .env.example): los ambientes los define el humano. Va al final: gana.
    out += ['    "**/.env*": deny', '    "**/cuentas-e2e.env": deny'] + (['    "**/.env.example": allow'] if role == "coder" else [])
    # Nunca preguntar (nadie mira la sesion): fuera del proyecto solo lo suyo, el resto se deniega.
    # Mismas reglas que oc_sesion.reglas(), que ademas las fija en cada sesion que lanza el autopilot.
    out += ["  external_directory:", '    "*": deny']
    for d in oc_sesion.directorios_permitidos(role):
        out += ["    %s: allow" % q(d), "    %s: allow" % q(d + "/**")]
    out += ["  doom_loop: deny"]
    out += ["  bash:", '    "*": allow']
    # OpenCode evalua en orden y gana la ultima regla que coincide: primero allow, despues deny.
    for c in DENY[role]:
        for p in patrones(c):
            out.append("    %s: deny" % q(p))
    out += ["    %s: deny" % q(p) for p in AMBIENTE_DENY]
    if role == "e2e":
        out += ["    %s: deny" % q(p) for p in E2E_DENY]
    out += ["    %s: allow" % q(p) for p in AMBIENTE_ALLOW + (["*e2e.sh *"] if role == "e2e" else [])]
    if role == "e2e":  # aenv.sh no sirve para saltarse e2e.sh (va despues del allow: gana)
        out += ["    %s: deny" % q(p) for p in E2E_DENY if "aenv.sh" in p]
    for c in DENY[role]:                                       # push/merge siguen prohibidos aun con aenv.sh
        for p in patrones(c):
            out.append("    %s: deny" % q("*aenv.sh* " + p))
            if role == "e2e":
                out.append("    %s: deny" % q("*e2e.sh* " + p))
    return out


def front_claude(meta, kit):
    role = meta["role"]
    guard = "%s %s" % (shlex.quote(os.path.join(kit, "git-guard.sh")), role)
    out = [MARCA, "name: " + meta["name"], "description: " + q(meta["description"]),
           # El coder y el QA trabajan en paralelo: el principal no los espera, Claude Code le avisa al terminar.
           "background: true",
           "hooks:", "  PreToolUse:", '    - matcher: "Bash"', "      hooks:",
           "        - type: command", "          command: " + q(guard)]
    if role == "coder":
        # El coder escribe codigo, pero nunca archivos .env* (los ambientes los define el humano).
        out += ['    - matcher: "Edit|Write|NotebookEdit"', "      hooks:", "        - type: command",
                "          command: " + q(shlex.quote(os.path.join(kit, "escritura.sh")) + " coder")]
    if role in ("qa", "e2e"):
        # El QA y el E2E escriben pruebas temporales y capturas, pero SOLO en sus copias de trabajo.
        out += ['    - matcher: "Edit|Write|NotebookEdit"', "      hooks:", "        - type: command",
                "          command: " + q(shlex.quote(os.path.join(kit, "escritura.sh")) + " " + role)]
    return out


def front_pi(meta, kit):
    """Frontmatter de pi. Los bloqueos reales van en una extension (pi-guard-<role>.mjs del
    kit) que intercepta tool_call y cancela lo prohibido (misma logica que git-guard.sh y
    escritura.sh, reutilizadas tal cual); se carga SOLO en las sesiones de este agente
    (subagentOnlyExtensions), no en el resto de la sesion del usuario."""
    role = meta["role"]
    guard = os.path.join(kit, "pi-guard-%s.mjs" % role)
    out = [MARCA, "name: " + meta["name"], "description: " + q(meta["description"]),
           "role: " + role,
           # pi corre los subagentes en segundo plano por defecto: el watcher no los espera.
           "async: true",
           # Solo estas herramientas. Sin 'subagent': el agente no lanza subagentes.
           "tools: read, bash, edit, write, grep, find, ls",
           # Guard real (push/merge, aenv.sh, .env*, copias de trabajo): solo en sus sesiones.
           "subagentOnlyExtensions: " + q(guard)]
    return out


def escribir(path, front, cuerpo):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and MARCA not in open(path, encoding="utf-8").read():
        print("  = %s ya existe y no es del kit, no se toco" % path)
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(front) + "\n---\n" + cuerpo)
    print("  + %s" % path)


def install(cliente, cfg, kit):
    actuales = set()
    for src in sorted(glob.glob(os.path.join(KIT_SRC, "agents", "*.md"))):
        meta, cuerpo = leer_agente(src)
        actuales.add(meta["name"] + ".md")
        if cliente == "opencode":
            front = front_opencode(meta)
        elif cliente == "claude":
            front = front_claude(meta, kit)
        else:
            front = front_pi(meta, kit)
        escribir(os.path.join(cfg, "agents", meta["name"] + ".md"), front, cuerpo)
    # Agentes que el kit instalo antes y ya no existen (p. ej. renombrados): se borran.
    # Solo archivos con la marca del kit; nunca uno ajeno.
    for p in glob.glob(os.path.join(cfg, "agents", "*.md")):
        if os.path.basename(p) not in actuales and MARCA in open(p, encoding="utf-8").read():
            os.remove(p)
            print("  - %s (ya no existe en el kit)" % p)
    if cliente == "opencode":
        for nombre, desc in COMANDOS.items():
            cuerpo = ("Carga la skill `%s` y sigue su seccion \"Arranque\" en ESTE proyecto, "
                      "paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n" % nombre)
            escribir(os.path.join(cfg, "commands", nombre + ".md"),
                     [MARCA, "description: " + q(desc)], cuerpo)
        for p in glob.glob(os.path.join(cfg, "commands", "*.md")):  # comandos del kit que ya no existen
            if os.path.basename(p)[:-3] not in COMANDOS and MARCA in open(p, encoding="utf-8").read():
                os.remove(p)
                print("  - %s (ya no existe en el kit)" % p)


def uninstall(cliente, cfg):
    for sub in ("agents", "commands"):
        for p in glob.glob(os.path.join(cfg, sub, "*.md")):
            if MARCA in open(p, encoding="utf-8").read():
                os.remove(p)
                print("  - %s" % p)


def json_merge(path, mutar, backup=True):
    """Merge sobre un JSON existente. En proyectos no hay backup: git ya guarda la historia."""
    cur = {}
    if os.path.exists(path):
        cur = json.load(open(path, encoding="utf-8"))
        if backup:
            shutil.copy2(path, "%s.bak.%s" % (path, time.strftime("%Y%m%d-%H%M%S")))
    mutar(cur)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write("\n")


def project(cliente, proj, kit):
    """Prohibe push/merge tambien al agente principal (el orquestador) en ese proyecto."""
    if cliente == "pi":
        # Pi no tiene permisos por comando por proyecto: se instala la extension guard en
        # .pi/extensions/ del proyecto (ambient en esa carpeta) con modo 'todos' (push/merge/
        # pull/gh pr merge y nada que toque un ambiente fuera de aenv.sh).
        dst = os.path.join(proj, ".pi", "extensions", "pi-guard-todos.mjs")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        for nombre in ("pi-guard.mjs", "pi-guard-todos.mjs"):
            destino = os.path.join(os.path.dirname(dst), nombre)
            if os.path.exists(destino):
                os.remove(destino)
            shutil.copy2(os.path.join(kit, nombre), destino)
        print("  + %s (push/merge y ambientes prohibidos al agente principal)" % dst)
        return
    elif cliente == "claude":
        path = os.path.join(proj, ".claude", "settings.local.json")
        guard = "%s todos" % shlex.quote(os.path.join(kit, "git-guard.sh"))

        def mutar(d):
            perms = d.setdefault("permissions", {})
            deny = perms.setdefault("deny", [])
            for c in BASE:
                r = "Bash(%s *)" % c
                if r not in deny:
                    deny.append(r)
            pre = d.setdefault("hooks", {}).setdefault("PreToolUse", [])
            if not any(guard in h.get("command", "") for m in pre for h in m.get("hooks", [])):
                pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": guard}]})
        json_merge(path, mutar, backup=False)
    else:
        path = os.path.join(proj, "opencode.json")

        def mutar(d):
            perm = d.setdefault("permission", {})
            bash = perm.get("bash")
            if isinstance(bash, str):          # "bash": "allow" -> objeto equivalente
                bash = {"*": bash}
            bash = bash or {"*": "allow"}
            for c in BASE:
                for p in patrones(c):
                    bash.pop(p, None)
                    bash[p] = "deny"           # al final: gana la ultima regla
            perm["bash"] = bash
        json_merge(path, mutar, backup=False)
    print("  + %s (push/merge prohibidos)" % path)


def main(a):
    if len(a) >= 4 and a[0] == "install":
        install(a[1], a[2], a[3])
    elif len(a) >= 3 and a[0] == "uninstall":
        uninstall(a[1], a[2])
    elif len(a) >= 4 and a[0] == "project":
        project(a[1], a[2], a[3])
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
