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
#  en segundo plano (Claude Code y OpenCode: subagentes background; en OpenCode su sesion se
#  registra con `wi.sh sesion` y aca se detecta cuando termina).
#  Leer el board es leer archivos locales: no hay red ni tokens.
#
#  Puestos en paralelo, con capacidad (PARALLEL=false -> 1 cada uno; true -> MAX_CODERS, MAX_QA, MAX_E2E):
#    coder (in-progress):  bug-fix primero, despues new (Critical>High>Medium>Low)
#    qa    (validando):    la cola qa
#    e2e   (probando-e2e): la cola e2e (solo con E2E=true: lo que el QA aprobo)
#  Retorna cuando hay trabajo para un puesto LIBRE (`acciones`), cuando termino una sesion de
#  OpenCode de un puesto (`terminadas`) o cuando llega texto libre por Telegram (`mensajes`, con
#  TELEGRAM=true; los comandos /estado, /reqa... los responde solo, sin despertar al agente).
#  Solo debe haber UN watcher corriendo a la vez.
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
TG="$SCRIPT_DIR/telegram.py"
TG_ON="$("$PY" -c '
import sys; sys.path.insert(0, sys.argv[1]); import workitems as wi
print("1" if wi.cargar_config(sys.argv[2])["telegram"]["activo"] else "0")' "$SCRIPT_DIR" "$ENV_FILE")"
if [[ "$TG_ON" == 1 ]]; then
  log " Telegram activo: avisos y comandos (/estado, /tarea, /reqa, /pausa...)"
  trap '"$PY" "$TG" "$ENV_FILE" send "🛑 El watcher del autopilot se detuvo: ya no se vigila el tablero." --alert; exit 130' INT TERM
  if [[ $INICIO == 1 ]]; then
    "$PY" -c '
import sys, subprocess; sys.path.insert(0, sys.argv[1]); import workitems as wi, telegram
b = wi.Board(wi.cargar_config(sys.argv[2])); p = b.plan(); c = p["cola"]
av = p["avisos"]
txt = "▶️ Autopilot encendido. Cola: bug-fix %d · new %d · qa %d%s" % (c["bugfix"], c["new"], c["qa"], " · e2e %d" % c["e2e"] if p["e2e"] else "")
if av: txt += "\n⚠️ %d aviso(s) de configuracion:\n- " % len(av) + "\n- ".join(a[:200] for a in av[:6])
txt += "\n\n/ayuda para ver los comandos."
telegram.enviar(b.cfg, txt, dedup=True)' "$SCRIPT_DIR" "$ENV_FILE" 2>/dev/null
  fi
fi
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

  # Telegram: los comandos (/pausa, /reqa...) se aplican antes de calcular el plan; el texto libre despierta al agente (`mensajes`).
  mensajes="[]"
  if [[ "$TG_ON" == 1 ]]; then
    mensajes="$("$PY" "$TG" "$ENV_FILE" poll 2>/dev/null)" || mensajes="[]"
    [[ -z "$mensajes" ]] && mensajes="[]"
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
ev += ["telegram: %d mensaje(s)" % len(json.loads(sys.argv[2]))] if json.loads(sys.argv[2]) else []
print(", ".join(ev))' "$atascadas" "$mensajes" <<<"$plan")"

  if [[ -n "$hay" ]]; then
    log " #$iter $hay. Retornando al agente."
    "$PY" -c 'import json,sys; p = json.load(sys.stdin); p["atascadas"] = json.loads(sys.argv[1]); p["mensajes"] = json.loads(sys.argv[2]); print(json.dumps(p, ensure_ascii=False))' "$atascadas" "$mensajes" <<<"$plan"
    exit 0
  fi

  c="$("$PY" -c '
import json,sys
p = json.load(sys.stdin); c = p["cola"]
o = p["ocupados"]
k = p["capacidad"]
f = lambda x: "%d/%d%s" % (len(o[x]), k[x], (" " + ",".join(o[x])) if o[x] else "")
e2e = (" | e2e %s" % f("e2e")) if p.get("e2e") else ""
print("coder %s | qa %s%s | cola bugfix=%d qa=%d%s new=%d en_espera=%d stopped=%d" % (f("coder"), f("qa"), e2e,
      c["bugfix"], c["qa"], (" e2e=%d" % c["e2e"]) if p.get("e2e") else "", c["new"], len(p["en_espera"]),
      len(p["stopped"])) + (" | PAUSA (/seguir en Telegram)" if p.get("pausa") else "") +
      "".join(" | permiso rechazado: %s pidio %s" % (r["tarea"], r["accion"]) for r in p.get("permisos_rechazados") or []))' <<<"$plan")"
  log " #$iter idle ($c). Espero ${POLL_INTERVAL}s."
  sleep "$POLL_INTERVAL"
done
