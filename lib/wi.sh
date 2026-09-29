#!/usr/bin/env bash
# ============================================================
#  wi.sh — Unica via de escritura del board de workitems
#
#  El board son carpetas + archivos .md (ver workitems.py).
#  El watcher y el agente escriben siempre por aca, asi nunca
#  mutan el mismo archivo por caminos distintos.
#
#  uso: wi.sh <ruta/autopilot.env> <comando> [args]
#       wi.sh <env> help   para ver todos los comandos
# ============================================================
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || echo '')"
[[ -z "$PY" ]] && { echo "ERROR: falta python3" >&2; exit 1; }
exec "$PY" "$DIR/workitems.py" "$@"
