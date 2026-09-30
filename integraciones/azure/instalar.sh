#!/usr/bin/env bash
# ============================================================
#  instalar.sh — integracion OPCIONAL de Azure DevOps para el autopilot
#
#  El autopilot no depende de Azure: esta integracion es un cliente externo
#  del board que importa Work Items como tareas new (azure-sync.py) y,
#  si queres, registra el MCP de Azure DevOps en tu cliente.
#
#  Que instala:
#    - azure-sync.py y ado-mcp.sh en ~/.local/share/autopilot-kit/integraciones/azure/
#    - la skill azure-sync en la carpeta de skills de cada cliente
#    - (OpenCode) el comando /azure-sync
#    - (--with-mcp <org>) el MCP azure-devops en cada cliente
#
#  Requiere el kit del autopilot ya instalado (install.sh en la raiz del repo).
#
#  Uso:
#    integraciones/azure/instalar.sh                      # clientes detectados
#    integraciones/azure/instalar.sh --claude --with-mcp <org>
#    integraciones/azure/instalar.sh --uninstall          # quita skill, comando, MCP y scripts
# ============================================================

set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
DEST="$KIT/integraciones/azure"
SECRETS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autopilot-kit"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
MARCA=".autopilot-integracion"
MARCA_CMD="# generado por integraciones/azure/instalar.sh. No editar: se regenera."

WANT_OC=0; WANT_CC=0; UNINSTALL=0; ADO_ORG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)   WANT_OC=1 ;;
    --claude)     WANT_CC=1 ;;
    --uninstall)  UNINSTALL=1 ;;
    --with-mcp)   shift; ADO_ORG="${1:-}"; [[ -z "$ADO_ORG" ]] && { echo "--with-mcp necesita la organizacion" >&2; exit 1; } ;;
    -h|--help)    sed -n '3,21p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1 (ver --help)" >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

if [[ $WANT_OC == 0 && $WANT_CC == 0 ]]; then
  { command -v opencode >/dev/null || [[ -d "$OC_DIR" ]]; } && WANT_OC=1
  { command -v claude   >/dev/null || [[ -d "$CC_DIR" ]]; } && WANT_CC=1
fi
CLIENTES=()
[[ $WANT_OC == 1 ]] && CLIENTES+=(opencode)
[[ $WANT_CC == 1 ]] && CLIENTES+=(claude)
cfg_de() { [[ "$1" == opencode ]] && echo "$OC_DIR" || echo "$CC_DIR"; }

# ------------------------------------------------------------------
# MCP de Azure DevOps: registrar / quitar en cada cliente
# ------------------------------------------------------------------
oc_mcp() {  # oc_mcp set <cmd...> | oc_mcp del  — edita opencode.json (mcp.servers o mcp)
  python3 - "$OC_DIR/opencode.json" "$KIT" "$@" <<'PY'
import json, os, shutil, sys, time
path, kit, op, cmd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
d = json.load(open(path)) if os.path.exists(path) else {}
mcp = d.setdefault("mcp", {})
tabla = mcp["servers"] if isinstance(mcp.get("servers"), dict) else mcp
cur = tabla.get("azure-devops")
ours = cur is None or any("ado-mcp.sh" in str(c) for c in (cur or {}).get("command", []))
if not ours:
    print("  = azure-devops ya existe en opencode.json y no es del kit, no se toco"); sys.exit(0)
if op == "del" and cur is None:
    sys.exit(0)
if os.path.exists(path):
    shutil.copy2(path, "%s.bak.%s" % (path, time.strftime("%Y%m%d-%H%M%S")))
if op == "set":
    tabla["azure-devops"] = {"type": "local", "command": cmd}
    print("  + opencode: MCP azure-devops -> %s" % " ".join(cmd))
elif cur is not None:
    del tabla["azure-devops"]; print("  - opencode: MCP azure-devops")
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
PY
}

cc_mcp() {  # cc_mcp set <cmd...> | cc_mcp del
  command -v claude >/dev/null || { warn "claude no esta en el PATH: registra el MCP a mano"; return; }
  local actual; actual="$(claude mcp get azure-devops 2>/dev/null || true)"
  if [[ -n "$actual" ]] && ! grep -q "ado-mcp.sh" <<<"$actual"; then
    warn "azure-devops ya existe en Claude Code y no es del kit, no se toco"; return
  fi
  [[ -n "$actual" ]] && claude mcp remove azure-devops -s user >/dev/null 2>&1
  if [[ "$1" == set ]]; then
    shift; claude mcp add azure-devops -s user -- "$@" >/dev/null && say "claude: MCP azure-devops -> $*"
  else
    [[ -n "$actual" ]] && say "claude: MCP azure-devops quitado"
  fi
}

# ------------------------------------------------------------------
# Uninstall
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  for c in "${CLIENTES[@]}"; do
    cfg="$(cfg_de "$c")"
    if [[ -f "$cfg/skills/azure-sync/$MARCA" ]]; then rm -rf "$cfg/skills/azure-sync"; say "$c: skill azure-sync"; fi
    cmd="$cfg/commands/azure-sync.md"
    if [[ "$c" == opencode && -f "$cmd" ]] && grep -qF "$MARCA_CMD" "$cmd"; then rm -f "$cmd"; say "opencode: comando /azure-sync"; fi
    [[ "$c" == opencode ]] && oc_mcp del
    [[ "$c" == claude ]] && cc_mcp del
  done
  [[ -d "$DEST" ]] && rm -rf "$DEST" && say "scripts: $DEST"
  exit 0
fi

# ------------------------------------------------------------------
# Install
# ------------------------------------------------------------------
[[ -f "$KIT/workitems.py" ]] || { err "primero instala el kit del autopilot (install.sh en la raiz del repo)"; exit 1; }
[[ ${#CLIENTES[@]} -eq 0 ]] && { err "no encuentro OpenCode ni Claude Code. Usa --opencode o --claude."; exit 1; }

mkdir -p "$DEST"
cp "$AQUI/azure-sync.py" "$AQUI/ado-mcp.sh" "$AQUI/instalar.sh" "$AQUI/azure-sync.env.example" "$DEST/" && chmod +x "$DEST"/*.py "$DEST"/*.sh
say "scripts en $DEST"

for c in "${CLIENTES[@]}"; do
  cfg="$(cfg_de "$c")"
  dst="$cfg/skills/azure-sync"
  if [[ -d "$dst" && ! -f "$dst/$MARCA" && ! -f "$dst/.autopilot-kit" ]]; then
    warn "$c: skill azure-sync ya existe y no es de la integracion, no se toco"
  else
    rm -rf "$dst"; mkdir -p "$cfg/skills"; cp -r "$AQUI/skill" "$dst"; touch "$dst/$MARCA"
    say "$c: skill azure-sync"
  fi
  if [[ "$c" == opencode ]]; then
    cmd="$cfg/commands/azure-sync.md"
    if [[ -f "$cmd" ]] && ! grep -qF "$MARCA_CMD" "$cmd" && ! grep -q "autopilot-kit" "$cmd"; then
      warn "opencode: $cmd ya existe y no es de la integracion, no se toco"
    else
      mkdir -p "$cfg/commands"
      printf -- '---\n%s\ndescription: "Importa Work Items de Azure DevOps al board de workitems como new (aditivo, con dedup)"\n---\nCarga la skill `azure-sync` y sigue su seccion "Arranque" en ESTE proyecto, paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n' "$MARCA_CMD" > "$cmd"
      say "opencode: comando /azure-sync"
    fi
  fi
done

if [[ -n "$ADO_ORG" ]]; then
  echo; echo "==> MCP de Azure DevOps ($ADO_ORG)"
  for c in "${CLIENTES[@]}"; do
    [[ "$c" == opencode ]] && oc_mcp set "$DEST/ado-mcp.sh" "$ADO_ORG"
    [[ "$c" == claude ]] && cc_mcp set "$DEST/ado-mcp.sh" "$ADO_ORG"
  done
  mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
  if [[ ! -f "$SECRETS_DIR/ado-mcp.secrets.env" ]]; then
    warn "falta el PAT. Guardalo (en tu terminal, no en el chat del agente):"
    echo "    (umask 077; read -rsp 'PAT: ' p; echo; printf 'AZURE_DEVOPS_PAT=%s\\n' \"\$p\" > $SECRETS_DIR/ado-mcp.secrets.env)"
  fi
fi
# Version vieja del kit: el MCP apuntaba a $KIT/ado-mcp.sh. Si ya se re-registro, sobra.
if [[ -f "$KIT/ado-mcp.sh" && -n "$ADO_ORG" ]]; then rm -f "$KIT/ado-mcp.sh"; say "quitado $KIT/ado-mcp.sh (version vieja)"; fi

echo
echo "==> Listo. Comando: /azure-sync   Config por proyecto: azure-sync.env (ver $AQUI/README.md)"
