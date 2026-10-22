#!/usr/bin/env python3
"""
render.py — Genera la configuracion de cada cliente desde una sola fuente.

Fuente unica:  agents/*.md  (frontmatter neutro: name, description, role)
Salida:
  opencode  <cfg>/agents/<name>.md    permisos de bash por patron (permission.bash)
            <cfg>/commands/<cmd>.md   /autopilot-init, /autopilot-plan y /autopilot
  claude    <cfg>/agents/<name>.md    agente en segundo plano (background: true)
            (sin commands: en Claude Code las skills ya son esos comandos)
  pi        <cfg>/agents/<name>.md    frontmatter de pi (async, tools)
            (sin commands: en pi las skills ya son esos comandos, /skill:<nombre>)

Los bloqueos reales (push/merge, ramas, ambientes, .env*) se expresan como
reglas de permiso de bash segun el cliente; la regla "nunca contra produccion"
se apoya ademas en aenv.sh/entorno.py del kit (la ejecuta el propio agente).

Todo archivo generado lleva la marca MARCA en el frontmatter; uninstall solo
borra archivos con esa marca.

uso:
  render.py install   <opencode|claude|pi> <cfg_dir> <kit_dir>
  render.py uninstall <opencode|claude|pi> <cfg_dir>
"""
import glob
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
MARCA = "# generado por autopilot-kit (install.sh). No editar: se regenera."

# Comandos de git prohibidos por rol. Solo hay un rol: coder.
BASE = ["git push", "git merge", "git pull", "gh pr merge"]
DENY = {
    "coder": BASE + ["git rebase", "git branch -d", "git branch -D", "git branch --delete",
                      "git reset --hard", "git switch", "git checkout -b", "git checkout -B"],
}

# Nunca contra produccion (reforzado por aenv.sh/entorno.py en tiempo de corrida):
# lo que se conecta a un ambiente solo pasa envuelto en aenv.sh. OpenCode gana la ultima regla.
AMBIENTE_DENY = ["npm run *", "npm start*", "npm test*", "npm t *", "npm exec *", "npx *", "yarn *", "pnpm *",
                 "node *", "nest *", "jest*", "vitest*", "ts-node *", "tsx *", "prisma *", "typeorm *",
                 "sequelize *", "knex *", "nodemon *", "*migrat*", "*seed*", "flutter run*", "flutter drive*",
                 "fvm flutter run*", "fvm flutter drive*", "*integration_test*", "curl http*", "wget http*",
                 "*> .env*", "*>.env*", "cp *.env*", "mv *.env*", "sed *.env*", "tee *.env*"]
AMBIENTE_ALLOW = ["npm run build*", "npm run lint*", "npm run format*", "npm run typecheck*", "npx tsc*",
                  "npx eslint*", "npx prettier*", "yarn install*", "yarn build*", "yarn lint*", "pnpm install*",
                  "curl http://localhost*", "curl http://127.0.0.1*", "*aenv.sh *", "orca worktree create*"]

COMANDOS = {
    "autopilot-init": "Prepara esta carpeta (repo o workspace de varios repos) para el autopilot: autopilot.env y board (la rama base la define Orca)",
    "autopilot-plan": "Convierte una idea o un documento en tareas del board: brainstorming hasta tenerlo claro, desglose y alta",
    "autopilot": "Arranca el sistema autonomo sobre el board de workitems de este proyecto (usa Orca para ejecutar a los coders)",
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


def front_opencode(meta):
    role = meta["role"]
    out = [MARCA, "description: " + q(meta["description"]), "mode: subagent", "permission:"]
    out += ["  edit:", '    "*": allow']
    # Nadie escribe .env* (salvo .env.example): los ambientes los define el humano. Va al final: gana.
    out += ['    "**/.env*": deny', '    "**/.env.example": allow']
    out += ["  external_directory:", '    "*": deny']
    out += ["  doom_loop: deny"]
    out += ["  bash:", '    "*": allow']
    for c in DENY[role]:
        for p in patrones(c):
            out.append("    %s: deny" % q(p))
    out += ["    %s: deny" % q(p) for p in AMBIENTE_DENY]
    out += ["    %s: allow" % q(p) for p in AMBIENTE_ALLOW]
    for c in DENY[role]:                                       # push/merge siguen prohibidos aun con aenv.sh
        for p in patrones(c):
            out.append("    %s: deny" % q("*aenv.sh* " + p))
    return out


def front_claude(meta):
    out = [MARCA, "name: " + meta["name"], "description: " + q(meta["description"]),
           # El coder trabaja en paralelo: el principal no lo espera, Claude Code le avisa al terminar.
           "background: true"]
    return out


def front_pi(meta):
    out = [MARCA, "name: " + meta["name"], "description: " + q(meta["description"]),
           "role: " + meta["role"],
           # pi corre los subagentes en segundo plano por defecto: el orquestador no los espera.
           "async: true",
           # Solo estas herramientas. Sin 'subagent': el agente no lanza subagentes.
           "tools: read, bash, edit, write, grep, find, ls"]
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
    for src in sorted(glob.glob(os.path.join(os.path.dirname(AQUI), "agents", "*.md"))):
        meta, cuerpo = leer_agente(src)
        actuales.add(meta["name"] + ".md")
        if cliente == "opencode":
            front = front_opencode(meta)
        elif cliente == "claude":
            front = front_claude(meta)
        else:
            front = front_pi(meta)
        escribir(os.path.join(cfg, "agents", meta["name"] + ".md"), front, cuerpo)
    # Agentes que el kit instalo antes y ya no existen: se borran (solo con marca).
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


# ----------------------------------------------------------------------
# Instalacion LOCAL (por proyecto). El kit vive en <proy>/.autopilot/ y
# cada cliente enruta dentro de la propia carpeta del proyecto. Nada global.
# ----------------------------------------------------------------------

def inyectar_k(cuerpo, kit):
    # K apunta al kit LOCAL del proyecto: lo usa el coder para $K/aenv.sh.
    return 'K="%s"\n\n' % kit + cuerpo


def local_instalar_agente(proy, kit):
    # Agente fuente (canonica) en .autopilot/agents: la usa el orquestador para
    # lanzar al coder via subagente SIN depender de agentes globales.
    for src in sorted(glob.glob(os.path.join(os.path.dirname(AQUI), "agents", "*.md"))):
        meta, cuerpo = leer_agente(src)
        escribir(os.path.join(proy, ".autopilot", "agents", meta["name"] + ".md"),
                 front_pi(meta), inyectar_k(cuerpo, kit))


def local_install(cliente, proy, kit):
    local_instalar_agente(proy, kit)
    if cliente == "opencode":
        for src in sorted(glob.glob(os.path.join(os.path.dirname(AQUI), "agents", "*.md"))):
            meta, cuerpo = leer_agente(src)
            escribir(os.path.join(proy, ".opencode", "agent", meta["name"] + ".md"),
                     front_opencode(meta), inyectar_k(cuerpo, kit))
        for nombre, desc in COMANDOS.items():
            cuerpo = ('Carga la skill `%s` y sigue su seccion "Arranque" en ESTE proyecto, '
                      "paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n" % nombre)
            escribir(os.path.join(proy, ".opencode", "command", nombre + ".md"),
                     [MARCA, "description: " + q(desc)], cuerpo)
    elif cliente == "claude":
        for src in sorted(glob.glob(os.path.join(os.path.dirname(AQUI), "agents", "*.md"))):
            meta, cuerpo = leer_agente(src)
            escribir(os.path.join(proy, ".claude", "agents", meta["name"] + ".md"),
                     front_claude(meta), inyectar_k(cuerpo, kit))
    # pi: skills en .pi/skills (lo copia install.sh) y agente via .autopilot/agents (embed).


def local_uninstall(cliente, proy):
    quita = []
    if cliente == "opencode":
        quita += [os.path.join(proy, ".opencode", "agent")]
        quita += [os.path.join(proy, ".opencode", "command")]
    elif cliente == "claude":
        quita += [os.path.join(proy, ".claude", "agents")]
    for raiz in quita:
        for p in glob.glob(os.path.join(raiz, "*.md")):
            if MARCA in open(p, encoding="utf-8").read():
                os.remove(p)
                print("  - %s" % p)
    # agente fuente canónico: se quita una sola vez
    p = os.path.join(proy, ".autopilot", "agents", "coder.md")
    if os.path.exists(p) and MARCA in open(p, encoding="utf-8").read():
        os.remove(p)
        print("  - %s" % p)


def main(a):
    if len(a) >= 4 and a[0] == "install":
        install(a[1], a[2], a[3])
    elif len(a) >= 3 and a[0] == "uninstall":
        uninstall(a[1], a[2])
    elif len(a) >= 4 and a[0] == "local-install":
        local_install(a[1], a[2], a[3])
    elif len(a) >= 3 and a[0] == "local-uninstall":
        local_uninstall(a[1], a[2])
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))