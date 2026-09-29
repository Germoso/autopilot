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
#  Dos puestos en paralelo, con capacidad (PARALLEL=false -> 1 y 1; true -> MAX_CODERS y MAX_QA):
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
"$PY" "$WI" "$ENV_FILE" init >/dev/null               # crea carpetas de estado nuevas (p. ej. reviewed)
while IFS= read -r aviso; do                          # ramas base vacias, repos faltantes
  [[ -n "$aviso" ]] && log " $aviso (las tareas afectadas pasaran a stopped)"
done < <("$PY" "$WI" "$ENV_FILE" check)

log " vigilando el board cada ${POLL_INTERVAL}s (bloqueante). Ctrl+C para salir."
VIGIA="$SCRIPT_DIR/vigia.py"
read -r VIGIA_ON VIGIA_CADA < <("$PY" -c '
import sys; sys.path.insert(0, sys.argv[1]); import workitems as wi
v = wi.cargar_config(sys.argv[2])["vigia"]; print("1" if v["activo"] else "0", v["intervalo"])' "$SCRIPT_DIR" "$ENV_FILE")
ULTIMA_VIGIA=0
[[ "$VIGIA_ON" == 1 ]] && log " vigia activo cada ${VIGIA_CADA}s (procesos colgados, huerfanos y tareas atascadas)"

iter=0
while true; do
  iter=$((iter+1))

  # Vigia: mata procesos colgados/huerfanos (sin despertar al agente) y detecta tareas atascadas.
  atascadas="[]"
  if [[ "$VIGIA_ON" == 1 && $(( $(date +%s) - ULTIMA_VIGIA )) -ge $VIGIA_CADA ]]; then
    ULTIMA_VIGIA=$(date +%s)
    v="$("$PY" "$VIGIA" "$ENV_FILE" 2>/dev/null)" || v='{}'
    res="$("$PY" -c '
import json,sys
v = json.load(sys.stdin)
for h in v.get("huerfanos", []): print("M vigia: %d proceso(s) huerfanos de %s (%s en %s) terminados" % (len(h["procesos"]), h["tarea"], h["puesto"], h["estado"]))
for c in v.get("colgados", []): print("M vigia: proceso colgado de %s (%s, %s min sin CPU) terminado" % (c["tarea"], c["puesto"], c["minutos_sin_cpu"]))
print("A " + json.dumps(v.get("atascadas", [])))' <<<"$v")"
    while IFS= read -r l; do
      [[ "$l" == M* ]] && log " ${l:2}"
      [[ "$l" == A* ]] && atascadas="${l:2}"
    done <<<"$res"
  fi

  # --recuperar solo en la primera vuelta de un --inicio
  rec=(); [[ $INICIO == 1 && $iter == 1 ]] && rec=(--recuperar)
  plan="$("$PY" "$WI" "$ENV_FILE" plan "${rec[@]}")" \
    || { log " #$iter no pude leer el board, reintento"; sleep "$POLL_INTERVAL"; continue; }

  hay="$("$PY" -c '
import json,sys
p = json.load(sys.stdin)
ev = ["%s:%s %s" % (a["puesto"], a["accion"], a["tarea"]["id"]) for a in p["acciones"]]
ev += ["%s:terminada %s" % (t["puesto"], t["tarea"]["id"]) for t in p["terminadas"]]
ev += ["atascada %s" % a["tarea"] for a in json.loads(sys.argv[1])]
print(", ".join(ev))' "$atascadas" <<<"$plan")"

  if [[ -n "$hay" ]]; then
    log " #$iter $hay. Retornando al agente."
    "$PY" -c 'import json,sys; p = json.load(sys.stdin); p["atascadas"] = json.loads(sys.argv[1]); print(json.dumps(p, ensure_ascii=False))' "$atascadas" <<<"$plan"
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
