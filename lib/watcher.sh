#!/usr/bin/env bash
# ============================================================
#  watcher.sh — Sensor del board de workitems (carpetas + .md)
#
#  DISEÑO: bloqueante y de un solo disparo.
#  - Se lanza y QUEDA ESPERANDO. No retorna nada aún.
#  - Cuando detecta algo accionable, imprime el JSON y SALE.
#  - El control vuelve al agente, que actúa con las herramientas
#    nativas (subagent) o con wi.sh para los estados.
#
#  NO usa `opencode run`. NO crea sesiones duplicadas.
#  Leer el board es leer archivos locales: no hay red ni tokens.
#
#  Prioridad de selección:
#    1. bug-fix        — rompe el ciclo, va primero
#    2. qa             — la cola de certificacion
#    3. new            — trabajo nuevo, por Critical>High>Medium>Low
#
#  uso: watcher.sh [ruta/autopilot.env]     (default: ./autopilot.env)
# ============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || echo '')"
WI="$SCRIPT_DIR/workitems.py"
ENV_FILE="${1:-${ENV_FILE:-./autopilot.env}}"

[[ -z "$PY" ]] && { echo "ERROR: falta python3"; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "ERROR: no existe $ENV_FILE. Este proyecto no participa."; exit 1; }

_env_poll="${POLL_INTERVAL:-}"
POLL_INTERVAL="$(sed -n 's/^POLL_INTERVAL=//p' "$ENV_FILE" | tail -1)"
[[ -n "$_env_poll" ]] && POLL_INTERVAL="$_env_poll"
: "${POLL_INTERVAL:=5}"

log(){ echo "$(date '+%H:%M:%S') $*" >&2; }

"$PY" "$WI" "$ENV_FILE" query >/dev/null || exit 1   # falla ruidosa si el board no existe

log " vigilando el board cada ${POLL_INTERVAL}s (bloqueante). Ctrl+C para salir."
iter=0
while true; do
  iter=$((iter+1))

  # --recuperar: las tareas en in-progress/validando sin agente pasan a stopped
  plan="$("$PY" "$WI" "$ENV_FILE" plan --recuperar)" \
    || { log " #$iter no pude leer el board, reintento"; sleep "$POLL_INTERVAL"; continue; }

  accion="$("$PY" -c 'import json,sys;print(json.load(sys.stdin)["accion"])' <<<"$plan")"

  if [[ "$accion" != "idle" ]]; then
    log " #$iter ACCION: $accion. Retornando al agente."
    echo "$plan"
    exit 0
  fi

  c="$("$PY" -c '
import json,sys
p = json.load(sys.stdin); c = p["cola"]
print("bugfix=%d qa=%d new=%d stopped=%d" % (c["bugfix"], c["qa"], c["new"], len(p["stopped"])))' <<<"$plan")"
  log " #$iter idle ($c). Espero ${POLL_INTERVAL}s."
  sleep "$POLL_INTERVAL"
done
