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
#  NO lanza agentes: solo lee el board. Los subagentes los lanza el agente principal
#  (Claude Code: en segundo plano; OpenCode: como sesiones propias via oc_sesion.py).
#  Leer el board es leer archivos locales: no hay red ni tokens.
#
#  Dos puestos en paralelo, con capacidad (PARALELO=no -> 1 y 1; si -> MAX_CODERS y MAX_QA):
#    coder (in-progress): bug-fix primero, despues new (Critical>High>Medium>Low)
#    qa    (validando):   la cola qa
#  Retorna cuando hay trabajo para un puesto LIBRE (`acciones`) o cuando termino una sesion de
#  OpenCode de un puesto (`terminadas`). Solo debe haber UN watcher corriendo a la vez.
#
#  uso: watcher.sh [ruta/autopilot.env] [--inicio]
#    --inicio  solo al arrancar /autopilot: recupera tareas huerfanas (en un puesto sin agente).
#              En los relanzamientos NO se usa: el otro puesto puede estar trabajando.
# ============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || echo '')"
WI="$SCRIPT_DIR/workitems.py"
INICIO=0; ARGS=()
for a in "$@"; do [[ "$a" == "--inicio" ]] && INICIO=1 || ARGS+=("$a"); done
ENV_FILE="${ARGS[0]:-${ENV_FILE:-./autopilot.env}}"

[[ -z "$PY" ]] && { echo "ERROR: falta python3"; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "ERROR: no existe $ENV_FILE. Este proyecto no participa."; exit 1; }

_env_poll="${POLL_INTERVAL:-}"
POLL_INTERVAL="$(sed -n 's/^POLL_INTERVAL=//p' "$ENV_FILE" | tail -1)"
[[ -n "$_env_poll" ]] && POLL_INTERVAL="$_env_poll"
: "${POLL_INTERVAL:=5}"

log(){ echo "$(date '+%H:%M:%S') $*" >&2; }

"$PY" "$WI" "$ENV_FILE" query >/dev/null || exit 1   # falla ruidosa si el board no existe
while IFS= read -r aviso; do                          # ramas base vacias, repos faltantes
  [[ -n "$aviso" ]] && log " $aviso (las tareas afectadas pasaran a stopped)"
done < <("$PY" "$WI" "$ENV_FILE" check)

log " vigilando el board cada ${POLL_INTERVAL}s (bloqueante). Ctrl+C para salir."
iter=0
while true; do
  iter=$((iter+1))

  # --recuperar solo en la primera vuelta de un --inicio
  rec=(); [[ $INICIO == 1 && $iter == 1 ]] && rec=(--recuperar)
  plan="$("$PY" "$WI" "$ENV_FILE" plan "${rec[@]}")" \
    || { log " #$iter no pude leer el board, reintento"; sleep "$POLL_INTERVAL"; continue; }

  hay="$("$PY" -c '
import json,sys
p = json.load(sys.stdin)
ev = ["%s:%s %s" % (a["puesto"], a["accion"], a["tarea"]["id"]) for a in p["acciones"]]
ev += ["%s:terminada %s" % (t["puesto"], t["tarea"]["id"]) for t in p["terminadas"]]
print(", ".join(ev))' <<<"$plan")"

  if [[ -n "$hay" ]]; then
    log " #$iter $hay. Retornando al agente."
    echo "$plan"
    exit 0
  fi

  c="$("$PY" -c '
import json,sys
p = json.load(sys.stdin); c = p["cola"]
o = p["ocupados"]
k = p["capacidad"]
f = lambda x: "%d/%d%s" % (len(o[x]), k[x], (" " + ",".join(o[x])) if o[x] else "")
print("coder %s | qa %s | cola bugfix=%d qa=%d new=%d en_espera=%d stopped=%d" % (f("coder"), f("qa"),
      c["bugfix"], c["qa"], c["new"], len(p["en_espera"]), len(p["stopped"])))' <<<"$plan")"
  log " #$iter idle ($c). Espero ${POLL_INTERVAL}s."
  sleep "$POLL_INTERVAL"
done
