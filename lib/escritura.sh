#!/usr/bin/env bash
# ============================================================
#  escritura.sh — que archivos puede escribir cada agente
#
#  Hook PreToolUse de Claude Code (matcher: Edit|Write|NotebookEdit).
#    escritura.sh qa     solo dentro de sus copias de trabajo (~/.cache/autopilot-kit/qa/)
#    escritura.sh coder  cualquier archivo del codigo, MENOS los .env* (salvo .env.example):
#                        los ambientes los define el humano (.env.autopilot), nunca un agente.
#                        Ademas, dentro de su worktree (~/.cache/autopilot-kit/coder/<repo>-<clave>/)
#                        RESERVA el archivo para su tarea; si otra tarea activa ya lo tiene, bloquea:
#                        dos workitems en paralelo nunca tocan el mismo archivo.
#  Una escritura no permitida sale con codigo 2: Claude Code la cancela y muestra el motivo.
# ============================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODO="${1:-coder}" KIT="$DIR" exec python3 -c '
import json, os, re, sys
modo = os.environ.get("MODO", "coder")
try:
    ti = json.load(sys.stdin).get("tool_input", {})
except Exception:
    sys.exit(0)
ruta = ti.get("file_path") or ti.get("notebook_path") or ""
real = os.path.realpath(os.path.expanduser(ruta)) if ruta else ""
nombre = os.path.basename(real)
if re.match(r"^\.env", nombre) and not re.search(r"\.(example|sample|template)$", nombre):
    print("BLOQUEADO por el autopilot: no se crean ni editan archivos %s. Los ambientes los define el "
          "humano (.env.autopilot). Si necesitas otro ambiente, deten la tarea y recomienda que hacer." % nombre,
          file=sys.stderr)
    sys.exit(2)
if modo == "qa":
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    permitida = os.path.realpath(os.path.join(cache, "autopilot-kit", "qa")) + os.sep
    if not real.startswith(permitida):
        print("BLOQUEADO por el autopilot: el QA solo puede escribir dentro de sus copias de trabajo (%s). "
              "Ruta pedida: %s" % (permitida, ruta or "-"), file=sys.stderr)
        sys.exit(2)
if modo == "coder" and real:
    sys.path.insert(0, os.environ.get("KIT", ""))
    try:
        import workitems
        motivo = workitems.reservar_ruta(real)
    except Exception:
        motivo = None
    if motivo:
        print("BLOQUEADO por el autopilot: " + motivo, file=sys.stderr)
        sys.exit(2)
sys.exit(0)
'
