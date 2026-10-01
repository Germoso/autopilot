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
#    coder        + rebase, borrar ramas, reset --hard, switch/checkout -b
#    qa           + commit, add, switch, checkout, reset, stash, rebase, borrar ramas
#    e2e          lo mismo que qa y ademas: apps Flutter (run/drive/build/install/integration_test),
#                 emulador y Playwright SOLO via e2e.sh (que las apunta al backend local y corta
#                 la red a produccion)
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
    "coder": {"rebase"},
    "qa": {"rebase", "commit", "add", "switch", "checkout", "reset", "stash", "cherry-pick", "revert", "am", "apply", "restore", "rm", "mv"},
}
EXTRA["e2e"] = EXTRA["qa"]
AGENTES = ("coder", "qa", "e2e")

def motivo(argv):
    if len(argv) >= 3 and os.path.basename(argv[0]) == "gh" and argv[1:3] == ["pr", "merge"]:
        return "gh pr merge"
    sub, args = sub_git(argv)
    if sub is None:
        return None
    if sub in BASE or sub in EXTRA.get(mode, set()):
        return "git " + sub
    if mode in AGENTES:
        if sub == "branch" and any(a in ("-d", "-D", "--delete", "-m", "-M", "--move") for a in args):
            return "git branch " + " ".join(args)
        if sub == "reset" and "--hard" in args:
            return "git reset --hard"
        if mode == "coder" and sub in ("switch", "checkout") and any(a in ("-b", "-B", "-c", "-C", "--orphan") for a in args):
            return "git %s (crear otra rama)" % sub
        if mode == "coder" and sub == "switch":
            return "git switch (cambiar de rama)"
    return None

# ---- nunca contra produccion: lo que se conecta a un ambiente va SOLO con aenv.sh
NPM_SEGUROS = {"build", "lint", "format", "prettier", "analyze", "typecheck", "type-check", "tsc", "check"}
NPX_SEGUROS = {"tsc", "eslint", "prettier", "biome", "stylelint"}
EJECUTORES = {"node", "nodejs", "nest", "jest", "vitest", "mocha", "ts-node", "tsx", "prisma", "typeorm",
              "sequelize", "sequelize-cli", "knex", "bun", "deno", "nodemon", "pm2", "artisan", "rails"}


def url_no_segura(a):
    return re.match(r"^https?://", a) and not re.search(r"localhost|127\.0\.0\.1|0\.0\.0\.0|qa", a, re.I)


def ambiente(argv):
    """Motivo si el comando puede conectarse a un ambiente sin pasar por aenv.sh; si no, None."""
    while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
        argv = argv[1:]
    for w in ("env", "command", "sudo", "exec", "nohup", "time", "timeout"):
        if argv and argv[0] == w:
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or re.match(r"^\d+[smh]?$", argv[0])):
                argv = argv[1:]
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    if prog in ("aenv.sh", "e2e.sh"):
        return None                                   # envuelto: validan .env.autopilot(.e2e) / API local
    if re.search(r"(^|/)migrat|(^|/)seed", " ".join(argv[:2]), re.I):
        return "migraciones o seeds"
    if prog in ("npm", "yarn", "pnpm"):
        sub = argv[1] if len(argv) > 1 else ""
        if sub in ("run", "run-script") and len(argv) > 2:
            return None if argv[2].split(":")[0] in NPM_SEGUROS else "%s run %s" % (prog, argv[2])
        if sub in ("start", "test", "t", "exec", "x", "dlx", "restart", "stop") or (prog == "yarn" and sub not in (
                "", "install", "add", "remove", "build", "lint", "--version", "-v")):
            return "%s %s" % (prog, sub)
        return None
    if prog in ("npx", "pnpx"):
        return None if len(argv) > 1 and argv[1] in NPX_SEGUROS else "npx %s" % (argv[1] if len(argv) > 1 else "")
    if prog in EJECUTORES:
        return prog
    if prog == "fvm" and len(argv) > 1 and argv[1] == "flutter":
        argv, prog = argv[1:], "flutter"
    if prog in ("flutter", "dart"):
        sub = argv[1] if len(argv) > 1 else ""
        if sub in ("run", "drive", "attach"):
            return "%s %s" % (prog, sub)
        if sub == "test" and any("integration_test" in x for x in argv[2:]):
            return "flutter test integration_test"
        return None
    if prog in ("curl", "wget", "http", "https", "xh"):
        malas = [a for a in argv[1:] if url_no_segura(a)]
        return "%s a una URL que no es local ni QA" % prog if malas else None
    return None


def env_escritura(argv, crudo):
    """Motivo si el comando crea, copia, mueve, edita o borra un archivo .env* (salvo .example)."""
    es_env = lambda x: (re.match(r"^\.env", os.path.basename(x)) or os.path.basename(x) == "cuentas-e2e.env") \
        and not re.search(r"\.(example|sample|template)$", x)
    if argv and os.path.basename(argv[0]) in ("cp", "mv", "ln", "rm", "sed", "tee", "truncate", "install", "rsync") \
            and any(es_env(a) for a in argv[1:] if not a.startswith("-")):
        return "modificar %s" % next(a for a in argv[1:] if es_env(a))
    if re.search(r">>?\s*[^\s;&|]*(\.env|cuentas-e2e\.env)(?!\.(example|sample|template))", crudo):
        return "escribir un archivo .env con una redireccion"
    return None


def sin_envoltorio(argv):
    while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
        argv = argv[1:]
    for w in ("env", "command", "sudo", "exec", "nohup", "time", "timeout"):
        if argv and argv[0] == w:
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or re.match(r"^\d+[smh]?$", argv[0])):
                argv = argv[1:]
    return argv


def e2e_directo(argv):
    """Modo e2e: lo que corre una app, el emulador o el navegador va SOLO por e2e.sh."""
    argv = sin_envoltorio(argv)
    if not argv:
        return None
    prog = os.path.basename(argv[0])
    if prog == "e2e.sh":
        return None
    if prog == "aenv.sh" and "--" in argv:           # aenv.sh es para backends y fronts web, no para esto
        return e2e_directo(argv[argv.index("--") + 1:])
    if prog == "fvm" and len(argv) > 1 and argv[1] == "flutter":
        argv, prog = argv[1:], "flutter"
    sub = argv[1] if len(argv) > 1 else ""
    if prog in ("flutter", "dart") and (sub in ("run", "drive", "build", "install", "attach")
                                        or any("integration_test" in x for x in argv[2:])):
        return "%s %s" % (prog, sub)
    if prog in ("emulator", "qemu-system-x86_64") or re.search(r"playwright", " ".join(argv)):
        return prog if prog != "npx" else "npx playwright"
    if prog == "adb":
        resto = argv[1:]
        while resto and resto[0].startswith("-"):
            resto = resto[2:] if resto[0] in ("-s", "-t", "-H", "-P", "-L") else resto[1:]
        if resto and resto[0] in ("install", "install-multiple", "emu"):
            return "adb %s" % resto[0]
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
        envuelto = sin_envoltorio(argv)
        if envuelto and os.path.basename(envuelto[0]) in ("aenv.sh", "e2e.sh") and "--" in envuelto:
            m = motivo(envuelto[envuelto.index("--") + 1:])   # aenv.sh -- git push: sigue prohibido
            if m: return m
        if mode == "e2e":
            d = e2e_directo(argv)
            if d:
                return ("`%s`: en E2E las apps, el emulador y el navegador se corren SOLO con "
                        "`~/.local/share/autopilot-kit/e2e.sh` (apunta la app al backend local y corta la red a "
                        "cualquier otro servidor). Ver `e2e.sh --help`" % d)
        if mode in AGENTES:
            e = env_escritura(argv, c)
            if e:
                return ("`%s`: los archivos .env* los define el humano (.env.autopilot); ningun agente los crea, "
                        "copia ni edita. Si hace falta otro ambiente, deten la tarea y recomienda que hacer (aenv.sh)" % e)
        amb = ambiente(argv)
        if amb:
            return ("`%s` puede conectarse a un ambiente (BD/API). Nunca contra produccion: ejecutalo con "
                    "`~/.local/share/autopilot-kit/aenv.sh <repo o worktree> -- <comando>`, que solo corre con el "
                    ".env.autopilot que creo el humano apuntando a local/QA. Si aenv.sh no te deja, no insistas: "
                    "deten la tarea y recomienda que hacer" % amb)
    return None

# Sin atribucion de herramienta en commits ni PRs (preferencia del usuario): un `git commit` o
# `gh pr create/edit` cuyo mensaje trae esos trailers se rechaza para que se rehaga sin ellos.
ATRIBUCION = re.compile(r"co-authored-by:\s*claude|claude-session:|generated with \[?claude code", re.I)
if re.search(r"\bgit\b[^;&|]*\bcommit\b|\bgh\s+pr\s+(create|edit)\b", cmd) and ATRIBUCION.search(cmd):
    print("BLOQUEADO por el autopilot: el mensaje trae atribucion de herramienta (Co-Authored-By: Claude, "
          "Claude-Session o Generated with Claude Code). Los commits y PRs van sin datos de autor: "
          "repite el comando sin esas lineas.", file=sys.stderr)
    sys.exit(2)

m = revisar(cmd)
if m:
    if "aenv.sh" in m or "e2e.sh" in m:
        print("BLOQUEADO por el autopilot: " + m, file=sys.stderr)
    else:
        print("BLOQUEADO por el autopilot: %s no esta permitido (modo %s). "
              "Nunca push ni merge; el merge lo hace el humano (o el kit con AUTO_MERGE=true)." % (m, mode),
              file=sys.stderr)
    sys.exit(2)
sys.exit(0)
'
