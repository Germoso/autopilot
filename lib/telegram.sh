#!/usr/bin/env bash
# telegram.sh — avisos del autopilot por Telegram (atajo de telegram.py)
#   telegram.sh send "<texto>" [--alert]    manda un aviso (si TELEGRAM=true en autopilot.env)
#   telegram.sh test                        mensaje de prueba      telegram.sh setup   conectar el bot
# Busca autopilot.env en la carpeta actual o la de arriba (o usa AUTOPILOT_ENV).
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ENV_FILE="${AUTOPILOT_ENV:-}"
if [[ -z "$ENV_FILE" ]]; then
  for d in "$PWD" "$(dirname "$PWD")"; do [[ -f "$d/autopilot.env" ]] && { ENV_FILE="$d/autopilot.env"; break; }; done
fi
[[ -z "$ENV_FILE" ]] && { echo "telegram.sh: no encuentro autopilot.env aqui ni en la carpeta de arriba (o define AUTOPILOT_ENV)" >&2; exit 2; }
exec python3 "$DIR/telegram.py" "$ENV_FILE" "$@"
