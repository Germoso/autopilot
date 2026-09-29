#!/usr/bin/env python3
"""
render.py — Genera la configuracion de cada cliente desde una sola fuente.

Fuente unica:  agents/*.md  (frontmatter neutro: name, description, role)
Salida:
  opencode  <cfg>/agents/<name>.md    permisos de bash por patron (permission.bash)
            <cfg>/commands/<cmd>.md   /autopilot y /azure-sync
  claude    <cfg>/agents/<name>.md    hook PreToolUse -> git-guard.sh <role>
            (sin commands: en Claude Code las skills ya son /autopilot y /azure-sync)

Todo archivo generado lleva la marca MARCA en el frontmatter; uninstall solo
borra archivos con esa marca.

uso:
  render.py install   <opencode|claude> <cfg_dir> <kit_dir>
  render.py uninstall <opencode|claude> <cfg_dir>
  render.py project   <opencode|claude> <proyecto> <kit_dir>   protege push/merge en el proyecto
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
MARCA = "# generado por autopilot-kit (install.sh). No editar: se regenera."

# Comandos de git prohibidos por rol. Mismo criterio que lib/git-guard.sh.
BASE = ["git push", "git merge", "git pull", "gh pr merge"]
DENY = {
    "worker": BASE + ["git rebase", "git branch -d", "git branch -D", "git branch --delete",
                      "git reset --hard", "git switch", "git checkout -b", "git checkout -B"],
    "qa": BASE + ["git rebase", "git commit", "git add", "git switch", "git checkout", "git reset",
                  "git stash", "git cherry-pick", "git revert", "git branch -d", "git branch -D",
                  "git branch --delete"],
}

COMANDOS = {
    "autopilot": "Enciende el watcher del sistema autonomo sobre el board de workitems de este proyecto",
    "azure-sync": "Importa Work Items de Azure DevOps al board de workitems como new (aditivo, con dedup)",
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
    out = [MARCA, "description: " + q(meta["description"]), "mode: subagent", "permission:",
           "  edit: " + ("deny" if role == "qa" else "allow"), "  bash:", '    "*": allow']
    # OpenCode evalua en orden y gana la ultima regla que coincide: primero allow, despues deny.
    for c in DENY[role]:
        for p in patrones(c):
            out.append("    %s: deny" % q(p))
    return out


def front_claude(meta, kit):
    role = meta["role"]
    no = ["mcp__azure-devops"] + (["Edit", "Write", "NotebookEdit"] if role == "qa" else [])
    guard = "%s %s" % (shlex.quote(os.path.join(kit, "git-guard.sh")), role)
    return [MARCA, "name: " + meta["name"], "description: " + q(meta["description"]),
            "disallowedTools: " + ", ".join(no),
            "hooks:", "  PreToolUse:", '    - matcher: "Bash"', "      hooks:",
            "        - type: command", "          command: " + q(guard)]


def escribir(path, front, cuerpo):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and MARCA not in open(path, encoding="utf-8").read():
        print("  = %s ya existe y no es del kit, no se toco" % path)
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(front) + "\n---\n" + cuerpo)
    print("  + %s" % path)


def install(cliente, cfg, kit):
    for src in sorted(glob.glob(os.path.join(KIT_SRC, "agents", "*.md"))):
        meta, cuerpo = leer_agente(src)
        front = front_opencode(meta) if cliente == "opencode" else front_claude(meta, kit)
        escribir(os.path.join(cfg, "agents", meta["name"] + ".md"), front, cuerpo)
    if cliente == "opencode":
        for nombre, desc in COMANDOS.items():
            cuerpo = ("Carga la skill `%s` y sigue su seccion \"Arranque\" en ESTE proyecto, "
                      "paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n" % nombre)
            escribir(os.path.join(cfg, "commands", nombre + ".md"),
                     [MARCA, "description: " + q(desc)], cuerpo)


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
    if cliente == "claude":
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
