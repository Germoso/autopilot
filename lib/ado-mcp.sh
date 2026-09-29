#!/usr/bin/env bash
# ============================================================
#  ado-mcp.sh — lanza el MCP local de Azure DevOps con tu PAT
#
#  Sirve igual para OpenCode y Claude Code: ambos lo lanzan por stdio.
#
#  El PAT NUNCA va en la config del cliente (opencode.json, ~/.claude.json). Se lee, en este orden, de:
#    1. la variable de entorno AZURE_DEVOPS_PAT
#    2. ~/.config/autopilot-kit/ado-mcp.secrets.env  (AZURE_DEVOPS_PAT=xxx, chmod 600)
#
#  El MCP (@azure-devops/mcp, modo "pat") espera PERSONAL_ACCESS_TOKEN
#  en base64 de "<email>:<pat>"; este script hace esa conversion.
#  No requiere permisos de administrador en la organizacion: solo un
#  PAT personal con Work Items (Read & Write).
#
#  uso: ado-mcp.sh <organizacion> [dominios...]
#       dominios por defecto: core work work-items
# ============================================================
set -euo pipefail

ORG="${1:?uso: ado-mcp.sh <organizacion> [dominios...]}"; shift
DOMAINS=("$@"); [[ ${#DOMAINS[@]} -eq 0 ]] && DOMAINS=(core work work-items)
VERSION="${ADO_MCP_VERSION:-2.10.0}"
SECRETS="${ADO_MCP_SECRETS:-${XDG_CONFIG_HOME:-$HOME/.config}/autopilot-kit/ado-mcp.secrets.env}"

if [[ -z "${AZURE_DEVOPS_PAT:-}" && -f "$SECRETS" ]]; then
  AZURE_DEVOPS_PAT="$(sed -n 's/^AZURE_DEVOPS_PAT=//p' "$SECRETS" | tail -1 | tr -d "\"' \r")"
fi
if [[ -z "${AZURE_DEVOPS_PAT:-}" ]]; then
  echo "ado-mcp: falta AZURE_DEVOPS_PAT (entorno o $SECRETS)" >&2
  exit 1
fi

export PERSONAL_ACCESS_TOKEN="$(printf '%s' "pat:$AZURE_DEVOPS_PAT" | base64 -w0)"
unset AZURE_DEVOPS_PAT
exec npx -y "@azure-devops/mcp@$VERSION" "$ORG" --authentication pat -d "${DOMAINS[@]}"
