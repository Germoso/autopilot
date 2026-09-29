#!/usr/bin/env bash
# ============================================================
#  git-guard.sh — bloquea operaciones de git prohibidas
#
#  Hook PreToolUse de Claude Code (matcher: Bash). Lee el JSON del
#  hook por stdin y, si el comando contiene una operacion prohibida,
#  sale con codigo 2: Claude Code cancela el comando y le muestra el
#  motivo al agente.
#
#  Revisa cada subcomando de un comando compuesto (a && b; c | d) y
#  salta las opciones globales de git (-C dir, -c k=v, --git-dir=...).
#
#  uso: git-guard.sh <modo>
#    todos        push, merge, pull (hace merge), gh pr merge
#    worker       + rebase, borrar ramas, reset --hard, switch/checkout -b
#    qa           + commit, add, switch, checkout, reset, stash, rebase, borrar ramas
# ============================================================
MODE="${1:-todos}" exec python3 -c '
import json, os, re, shlex, sys

mode = os.environ.get("MODE", "todos")
try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
except Exception:
    sys.exit(0)  # no es un hook de Bash: no opinamos

def partes(c):
    """Divide en subcomandos por ; & | && || y saltos de linea (fuera de comillas)."""
    try:
        lex = shlex.shlex(c, posix=True, punctuation_chars=";&|\n")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = c.split()
    cur = []
    for t in toks:
        if t and set(t) <= set(";&|\n"):
            if cur: yield cur
            cur = []
        else:
            cur.append(t)
    if cur: yield cur

def sub_git(argv):
    """Si argv es un git, devuelve (subcomando, args) saltando opciones globales."""
    while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):  # VAR=x git ...
        argv = argv[1:]
    for w in ("env", "command", "sudo", "exec", "nohup", "time"):
        if argv and argv[0] == w: argv = argv[1:]
    if not argv or os.path.basename(argv[0]) != "git":
        return None, argv
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        else:
            i += 1
    return (argv[i] if i < len(argv) else ""), argv[i + 1:]

BASE = {"push", "merge", "pull"}
EXTRA = {
    "worker": {"rebase"},
    "qa": {"rebase", "commit", "add", "switch", "checkout", "reset", "stash", "cherry-pick", "revert", "am", "apply", "restore", "rm", "mv"},
}

def motivo(argv):
    if len(argv) >= 3 and os.path.basename(argv[0]) == "gh" and argv[1:3] == ["pr", "merge"]:
        return "gh pr merge"
    sub, args = sub_git(argv)
    if sub is None:
        return None
    if sub in BASE or sub in EXTRA.get(mode, set()):
        return "git " + sub
    if mode in ("worker", "qa"):
        if sub == "branch" and any(a in ("-d", "-D", "--delete", "-m", "-M", "--move") for a in args):
            return "git branch " + " ".join(args)
        if sub == "reset" and "--hard" in args:
            return "git reset --hard"
        if mode == "worker" and sub in ("switch", "checkout") and any(a in ("-b", "-B", "-c", "-C", "--orphan") for a in args):
            return "git %s (crear otra rama)" % sub
        if mode == "worker" and sub == "switch":
            return "git switch (cambiar de rama)"
    return None

def revisar(c, prof=0):
    for argv in partes(c):
        # bash -c "..." / sh -c / eval "...": se revisa lo de adentro
        if prof < 5 and argv and os.path.basename(argv[0]) in ("bash", "sh", "zsh", "dash") and "-c" in argv[1:]:
            i = argv.index("-c")
            if i + 1 < len(argv):
                m = revisar(argv[i + 1], prof + 1)
                if m: return m
        if prof < 5 and argv and argv[0] == "eval":
            m = revisar(" ".join(argv[1:]), prof + 1)
            if m: return m
        m = motivo(argv)
        if m: return m
    return None

m = revisar(cmd)
if m:
    print("BLOQUEADO por el autopilot: %s no esta permitido (modo %s). "
          "Nunca push ni merge; el merge lo hace el humano." % (m, mode), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
'
