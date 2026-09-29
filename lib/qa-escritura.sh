#!/usr/bin/env bash
# ============================================================
#  qa-escritura.sh — el QA solo escribe dentro de sus copias de trabajo
#
#  Hook PreToolUse de Claude Code (matcher: Edit|Write|NotebookEdit) del
#  agente qa-reviewer. Deja escribir pruebas temporales y capturas SOLO bajo
#  la carpeta de worktrees del QA (~/.cache/autopilot-kit/qa/). Cualquier
#  otra ruta (el repo del coder, el board, el sistema) sale con codigo 2:
#  Claude Code cancela la escritura y le muestra el motivo.
# ============================================================
exec python3 -c '
import json, os, sys
try:
    ti = json.load(sys.stdin).get("tool_input", {})
except Exception:
    sys.exit(0)
ruta = ti.get("file_path") or ti.get("notebook_path") or ""
cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
permitida = os.path.realpath(os.path.join(cache, "autopilot-kit", "qa")) + os.sep
if ruta and os.path.realpath(os.path.expanduser(ruta)).startswith(permitida):
    sys.exit(0)
print("BLOQUEADO por el autopilot: el QA solo puede escribir dentro de sus copias de trabajo (%s). "
      "Ruta pedida: %s" % (permitida, ruta or "-"), file=sys.stderr)
sys.exit(2)
'
