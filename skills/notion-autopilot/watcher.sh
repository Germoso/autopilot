#!/usr/bin/env bash
# ============================================================
#  watcher.sh — Sensor de cambios del tablero Notion
#
#  DISEÑO: bloqueante y de un solo disparo.
#  - Se lanza y QUEDA ESPERANDO. No retorna nada aún.
#  - Cuando detecta algo accionable, imprime el JSON y SALE.
#  - El control vuelve al agente, que actúa con las herramientas
#    nativas (subagent) o con notion-set.sh para los estados.
#
#  NO usa `opencode run`. NO crea sesiones duplicadas.
#
#  Prioridad de selección:
#    1. Bug Fix        — rompe el ciclo, va primero
#    2. QA             — la cola de certificacion
#    3. New            — trabajo nuevo, por Critical>High>Medium>Low
# ============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/watcher.log}"
PY="$(command -v python3 || command -v python || echo '')"
API="https://api.notion.com/v1"
NSET="$SCRIPT_DIR/notion-set.sh"

_env_poll="${POLL_INTERVAL:-}"
if [[ -f "${ENV_FILE:-$SCRIPT_DIR/.env}" ]]; then
  set -a; source "${ENV_FILE:-$SCRIPT_DIR/.env}"; set +a
fi
[[ -n "$_env_poll" ]] && POLL_INTERVAL="$_env_poll"

: "${NOTION_TOKEN:?falta NOTION_TOKEN}"
: "${NOTION_DATABASE_ID:?falta NOTION_DATABASE_ID}"
: "${POLL_INTERVAL:=60}"
[[ -z "$PY" ]] && { echo "ERROR: falta python3"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
log(){ echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG_FILE"; }

set_motivo(){  # $1=id $2=motivo
  "$PY" -c "
import json
print(json.dumps({'properties':{
 'Estado':{'select':{'name':'Stopped'}},
 'Motivo de stopped':{'rich_text':[{'type':'text','text':{'content':'''$2'''}}]}}}))" > "$TMP/p.json"
  curl -s -X PATCH "$API/pages/$1" -H "Authorization: Bearer $NOTION_TOKEN" \
    -H "Notion-Version: 2022-06-28" -H "Content-Type: application/json" \
    -d @"$TMP/p.json" -o /dev/null
}

consultar(){
  curl -s -X POST "$API/databases/$NOTION_DATABASE_ID/query" \
    -H "Authorization: Bearer $NOTION_TOKEN" -H "Notion-Version: 2022-06-28" \
    -H "Content-Type: application/json" -d '{"page_size":100}' -o "$TMP/db.json"
  [[ "$("$PY" -c "import json;print(json.load(open('$TMP/db.json')).get('object',''))" 2>/dev/null)" == "list" ]]
}

analizar(){
  "$PY" -c "
import json
db = json.load(open('$TMP/db.json'))
PRI = {'Critical':0,'High':1,'Medium':2,'Low':3}
ts = []
for pg in db.get('results', []):
    p = pg.get('properties', {})
    def tx(n, t):
        v = p.get(n, {}).get(t, [])
        return ''.join(s.get('plain_text','') for s in v)
    def se(n):
        v = p.get(n, {}).get('select')
        return v.get('name','') if v else ''
    def num(n):
        return p.get(n, {}).get('number')
    ts.append({
      'id': pg['id'], 'nombre': tx('Name','title'), 'estado': se('Estado'),
      'prioridad': se('Prioridad'), 'descripcion': tx('Descripción','rich_text'),
      'criterio': tx('Criterio de aceptación','rich_text'), 'repo': tx('Repo','rich_text'),
      'intento': num('Intento') or 0, 'rama': tx('Rama','rich_text'),
      'feedback': tx('Feedback de QA','rich_text'), 'resultado': tx('Resultado','rich_text'),
    })

def take(lst, prio=False):
    if prio: lst.sort(key=lambda t: PRI.get(t['prioridad'], 9))
    return lst[0] if lst else None

by = lambda s: [t for t in ts if t['estado'] == s]
huerfanas = by('In Progress') + by('Validando')
bugfix = take(by('Bug Fix'))
qa      = take(by('QA'))
nuevas  = [t for t in by('New')]
nuevas.sort(key=lambda t: PRI.get(t['prioridad'], 9))

# Prioridad: Bug Fix > QA > New
if bugfix:        accion, elegida = 'desarrollar-bugfix', bugfix
elif qa:          accion, elegida = 'certificar', qa
elif nuevas:      accion, elegida = 'desarrollar', nuevas[0]
else:             accion, elegida = 'idle', None

json.dump({'accion': accion, 'tarea': elegida, 'huerfanas': huerfanas,
           'stopped': by('Stopped'),
           'cola': {'bugfix': len(by('Bug Fix')), 'qa': len(by('QA')), 'new': len(nuevas)}},
          open('$TMP/plan.json','w'), ensure_ascii=False)
print('ok')" 2>/dev/null
}

log_notion(){  # $1=Evento $2=Origen $3=Tipo $4=Tarea $5=Rama $6=Commit $7=Detalle
  [[ -z "${NOTION_LOG_DB_ID:-}" ]] && return 0
  "$NSET" "$ENV_FILE" log "$1" "$2" "$3" "$4" "$5" "$6" "$7" >/dev/null 2>&1
}

log " vigilando Notion cada ${POLL_INTERVAL}s (bloqueante). Ctrl+C para salir."
iter=0
while true; do
  iter=$((iter+1))

  consultar || { log " #$iter API no respondio, reintento"; sleep "$POLL_INTERVAL"; continue; }
  analizar >/dev/null 2>&1 || { log " #$iter no pude analizar, reintento"; sleep "$POLL_INTERVAL"; continue; }

  # 1) recuperar huerfanas (In Progress o Validando sin agente)
  mapfile -t huerf < <("$PY" -c "
import json
for t in json.load(open('$TMP/plan.json'))['huerfanas']: print(t['id']+'\t'+t['nombre']+'\t'+t['estado'])" 2>/dev/null)
  for h in "${huerf[@]:-}"; do
    [[ -z "$h" ]] && continue
    set_motivo "${h%%$'\t'*}" "Huerfana en ${h##*$'\t'} sin agente activo (recuperada por el watcher). Re-encolar manualmente a New o QA."
    log " #$iter huerfana -> Stopped: ${h#*$'\t'}"
    log_notion "Watcher recupero tarea huerfana" "watcher" "recuperacion" "${h#*$'\t'}" "-" "-" \
      "Estaba en ${h##*$'\t'} sin agente. Marcada Stopped."
  done
  [[ ${#huerf[@]} -gt 0 ]] && { sleep 2; consultar; analizar; }

  accion="$("$PY" -c "import json;print(json.load(open('$TMP/plan.json'))['accion'])" 2>/dev/null)"

  if [[ "$accion" != "idle" ]]; then
    log " #$iter ACCION: $accion. Retornando al agente."
    cat "$TMP/plan.json"
    exit 0
  fi

  c="$("$PY" -c "
import json
c = json.load(open('$TMP/plan.json'))['cola']
s = json.load(open('$TMP/plan.json'))['stopped']
print(f\"bugfix={c['bugfix']} qa={c['qa']} new={c['new']} stopped={len(s)}\")" 2>/dev/null)"
  log " #$iter idle ($c). Espero ${POLL_INTERVAL}s."
  sleep "$POLL_INTERVAL"
done
