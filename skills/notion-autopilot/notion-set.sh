#!/usr/bin/env bash
# ============================================================
#  notion-set.sh — Escritura en Notion via REST API
#
#  Unica via de escritura del sistema autonomous. El MCP queda
#  solo para lectura/consulta humana. Asi el watcher (que solo
#  puede usar REST) y el agente nunca escriben los mismos campos
#  por caminos distintos.
# ============================================================

set -uo pipefail

API="https://api.notion.com/v1"
PY="$(command -v python3 || command -v python || echo '')"
TMPF="$(mktemp)"
trap 'rm -f "$TMPF"' EXIT

ENVFILE="${1:-}"; shift || true
[[ -n "$ENVFILE" && -f "$ENVFILE" ]] && { set -a; source "$ENVFILE"; set +a; }
: "${NOTION_TOKEN:?falta NOTION_TOKEN. uso: notion-set.sh <ruta/.env> <comando> [args]}"

REQ() {  # $1=metodo $2=url $3=body-json
  curl -s -X "$1" "$2" \
    -H "Authorization: Bearer $NOTION_TOKEN" \
    -H "Notion-Version: 2022-06-28" \
    -H "Content-Type: application/json" \
    ${3:+-d "$3"}
}

# Convierte lineas "campo|tipo|valor" en el JSON de properties de Notion
props() {
  "$PY" -c '
import json, sys
out = {}
for line in sys.stdin.read().split("\n"):
    if not line.strip():
        continue
    campo, tipo, valor = line.split("|", 2)
    if   tipo == "select": out[campo] = {"select": {"name": valor}}
    elif tipo == "text":   out[campo] = {"rich_text": [{"type": "text", "text": {"content": valor[:1900]}}]}
    elif tipo == "title":  out[campo] = {"title": [{"type": "text", "text": {"content": valor}}]}
    elif tipo == "clear":  out[campo] = {"rich_text": []}
    elif tipo == "number":
        try:   out[campo] = {"number": int(valor)}
        except ValueError: out[campo] = {"number": None}
print(json.dumps(out, ensure_ascii=False))
'
}

patch() {  # $1=page_id  (props json por stdin)
  local pid="$1" p; p="$(props)"
  REQ PATCH "$API/pages/$pid" "{\"properties\":$p}" >/dev/null && echo "ok"
}

cmd="${1:-}"; shift || true

case "$cmd" in
  in-progress) printf 'Estado|select|In Progress\n' | patch "$1" ;;
  qa)          printf 'Estado|select|QA\n'           | patch "$1" ;;
  validando)   printf 'Estado|select|Validando\n'    | patch "$1" ;;
  bugfix)      printf 'Estado|select|Bug Fix\n'      | patch "$1" ;;
  done)        printf 'Estado|select|Done\n'         | patch "$1" ;;
  new)         printf 'Estado|select|New\nMotivo de stopped|clear|\n' | patch "$1" ;;
  stopped)     { printf 'Estado|select|Stopped\n'; printf 'Motivo de stopped|text|%s\n' "$2"; } | patch "$1" ;;
  resultado)   printf 'Resultado|text|%s\n' "$2"      | patch "$1" ;;
  criterio)    printf 'Criterio de aceptación|text|%s\n' "$2" | patch "$1" ;;
  reqa)        printf 'Estado|select|QA\nIntento|number|0\nFeedback de QA|clear|\n' | patch "$1" ;;
  motivo)      printf 'Motivo de stopped|text|%s\n' "$2" | patch "$1" ;;
  feedback)    printf 'Feedback de QA|text|%s\n' "$2" | patch "$1" ;;
  rama)        printf 'Rama|text|%s\n' "$2"           | patch "$1" ;;

  # intentos:Nx  ->  setea Intento a N
  intentos)    printf 'Intento|number|%s\n' "$2"      | patch "$1" ;;

  # ciclo completo de certificacion, en una sola llamada atomica
  #   certificar  <id> <intento_nuevo>
  #   aprobar     <id>
  #   rechazar    <id> <feedback>
  certificar)  printf 'Estado|select|Validando\nIntento|number|%s\n' "$2" | patch "$1" ;;
  aprobar)     printf 'Estado|select|Done\nFeedback de QA|text|Certificado sin observaciones.\n' | patch "$1" ;;
  rechazar)    { printf 'Estado|select|Bug Fix\n'; printf 'Feedback de QA|text|%s\n' "$2"; } | patch "$1" ;;

  log)  # $1=Evento $2=Origen $3=Tipo $4=Tarea $5=Rama $6=Commit $7=Detalle
    : "${NOTION_LOG_DB_ID:?falta NOTION_LOG_DB_ID en el .env}"
    "$PY" - "$NOTION_LOG_DB_ID" "$1" "$2" "$3" "$4" "$5" "$6" "$7" <<'PY' > "$TMPF"
import json, sys, datetime
db, evento, origen, tipo, tarea, rama, commit, detalle = sys.argv[1:9]
c = lambda v: {"rich_text": [{"type": "text", "text": {"content": (v or "-")[:1900]}}]}
print(json.dumps({"parent": {"database_id": db}, "properties": {
    "Evento":  {"title": [{"type": "text", "text": {"content": evento}}]},
    "Origen":  {"select": {"name": origen}},
    "Tipo":    {"select": {"name": tipo}},
    "Tarea":   c(tarea),
    "Rama":    c(rama),
    "Commit":  c(commit),
    "Detalle": c(detalle),
    "Hora":    {"date": {"start": datetime.datetime.now(datetime.timezone.utc).isoformat()}},
}}, ensure_ascii=False))
PY
    REQ POST "$API/pages" "$(cat "$TMPF")" >/dev/null && echo "ok" ;;

  query)  REQ POST "$API/databases/${1:-$NOTION_DATABASE_ID}/query" '{"page_size":100}' ;;

  add-task)  # $1=nombre $2=prioridad $3=descripcion $4=criterio [$5=repo]
    "$PY" - "$NOTION_DATABASE_ID" "$1" "$2" "$3" "$4" "${5:-}" <<'PY' > "$TMPF"
import json, sys
db, nombre, prioridad, desc, crit, repo = sys.argv[1:7]
print(json.dumps({
  "parent": {"database_id": db},
  "properties": {
    "Name":     {"title": [{"type": "text", "text": {"content": nombre}}]},
    "Estado":   {"select": {"name": "New"}},
    "Prioridad":{"select": {"name": prioridad}},
    "Descripción": {"rich_text": [{"type": "text", "text": {"content": desc}}]},
    "Criterio de aceptación": {"rich_text": [{"type": "text", "text": {"content": crit}}]},
    "Repo": {"rich_text": [{"type": "text", "text": {"content": repo or "-"}}]},
  },
}, ensure_ascii=False))
PY
    REQ POST "$API/pages" "$(cat "$TMPF")" >/dev/null && echo "ok" ;;

  *)
    echo "uso: notion-set.sh <env> <comando> [args]" >&2
    printf '%s\n' \
      "  in-progress|qa|validando|bugfix|done|new <page_id>" \
      "  stopped   <page_id> <motivo>" \
      "  resultado <page_id> <texto>" \
      "  motivo    <page_id> <texto>" \
      "  feedback  <page_id> <texto>" \
      "  rama      <page_id> <rama>" \
      "  intentos  <page_id> <n>" \
      "  certificar <page_id> <intento_nuevo>   -- QA -> Validando, incrementa Intento" \
      "  aprobar   <page_id>                    -- Validando -> Done" \
      "  rechazar  <page_id> <feedback>          -- Validando -> Bug Fix" \
      "  add-task  <nombre> <prioridad> <descripcion> <criterio> [repo]" \
      "  log <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>" \
      "  query [database_id]" >&2
    exit 1 ;;
esac
