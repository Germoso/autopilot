#!/usr/bin/env bash
# aenv.sh — Nunca contra produccion: la UNICA forma de ejecutar algo que se conecta a
# una base de datos o a una API. Valida el .env.autopilot (entorno.py) y, si no es
# "ok", NO ejecuta nada y sale con codigo 3. Si es ok, exporta las variables y corre
# el comando con un timeout.
#
# uso: aenv.sh <repo o worktree> -- <comando...>
#      aenv.sh <repo> --exportar        (pares CLAVE\0VALOR\0, sin ejecutar)
set -uo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT="${COMMAND_TIMEOUT:-900}"

if [[ $# -lt 3 || "$1" == "-h" || "$1" == "--help" ]]; then
  sed -n '1,9p' "$0" >&2; exit 1
fi
REPO="$1"; shift
if [[ "$1" == "--exportar" ]]; then
  python3 "$AQUI/entorno.py" "$REPO" --exportar
  exit $?
fi
[[ "$1" == "--" ]] && shift || { echo "aenv.sh: falta el -- antes del comando" >&2; exit 2; }
(($# == 0)) && { echo "aenv.sh: falta el comando" >&2; exit 2; }

# 1) Validar: si no es ok, NO ejecuta (nunca contra produccion).
estado=$(python3 "$AQUI/entorno.py" "$REPO" --exportar) || { echo "aenv.sh: no ejecuta ($REPO):" >&2; exit 3; }

# 2) Cargar el .env.autopilot y exportar (la salida lleva los valores en CLAVE\0VALOR\0).
eval "$(printf '%s' "$estado" | while IFS= read -r -d '' k; do IFS= read -r -d '' v; printf 'export %q=%q ' "$k" "$v"; done)"

# 3) Ejecutar con timeout.
timeout "$TIMEOUT" "$@"
rc=$?
if ((rc == 124)); then
  echo "aenv.sh: el comando supero ${TIMEOUT}s (COMMAND_TIMEOUT): $*" >&2
fi
exit $rc