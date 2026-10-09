#!/usr/bin/env bash
# ============================================================
#  instalar.sh — integracion OPCIONAL de Linear para el autopilot
#
#  El autopilot no depende de Linear: esta integracion es un cliente externo
#  del board que importa issues como tareas new (linear-sync.py).
#
#  Que instala:
#    - linear-sync.py en ~/.local/share/autopilot-kit/integraciones/linear/
#    - la skill linear-sync en la carpeta de skills de cada cliente
#    - (OpenCode) el comando /linear-sync
#
#  Requiere el kit del autopilot ya instalado (install.sh en la raiz del repo).
#
#  Uso:
#    integraciones/linear/instalar.sh                      # clientes detectados
#    integraciones/linear/instalar.sh --claude
#    integraciones/linear/instalar.sh --uninstall          # quita skill, comando y scripts
# ============================================================

set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
DEST="$KIT/integraciones/linear"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
MARCA=".autopilot-integracion"
MARCA_CMD="# generado por integraciones/linear/instalar.sh. No editar: se regenera."

WANT_OC=0; WANT_CC=0; UNINSTALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)   WANT_OC=1 ;;
    --claude)     WANT_CC=1 ;;
    --uninstall)  UNINSTALL=1 ;;
    -h|--help)    sed -n '3,18p' "$0"; exit 0 ;;
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
# Uninstall
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  for c in "${CLIENTES[@]}"; do
    cfg="$(cfg_de "$c")"
    if [[ -f "$cfg/skills/linear-sync/$MARCA" ]]; then rm -rf "$cfg/skills/linear-sync"; say "$c: skill linear-sync"; fi
    cmd="$cfg/commands/linear-sync.md"
    if [[ "$c" == opencode && -f "$cmd" ]] && grep -qF "$MARCA_CMD" "$cmd"; then rm -f "$cmd"; say "opencode: comando /linear-sync"; fi
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
cp "$AQUI/linear-sync.py" "$AQUI/instalar.sh" "$AQUI/linear-sync.env.example" "$DEST/" && chmod +x "$DEST"/*.py "$DEST"/*.sh
say "scripts en $DEST"

for c in "${CLIENTES[@]}"; do
  cfg="$(cfg_de "$c")"
  dst="$cfg/skills/linear-sync"
  if [[ -d "$dst" && ! -f "$dst/$MARCA" && ! -f "$dst/.autopilot-kit" ]]; then
    warn "$c: skill linear-sync ya existe y no es de la integracion, no se toco"
  else
    rm -rf "$dst"; mkdir -p "$cfg/skills"; cp -r "$AQUI/skill" "$dst"; touch "$dst/$MARCA"
    say "$c: skill linear-sync"
  fi
  if [[ "$c" == opencode ]]; then
    cmd="$cfg/commands/linear-sync.md"
    if [[ -f "$cmd" ]] && ! grep -qF "$MARCA_CMD" "$cmd" && ! grep -q "autopilot-kit" "$cmd"; then
      warn "opencode: $cmd ya existe y no es de la integracion, no se toco"
    else
      mkdir -p "$cfg/commands"
      printf -- '---\n%s\ndescription: "Importa issues de Linear al board de workitems como new (aditivo, con dedup)"\n---\nCarga la skill `linear-sync` y sigue su seccion "Arranque" en ESTE proyecto, paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n' "$MARCA_CMD" > "$cmd"
      say "opencode: comando /linear-sync"
    fi
  fi
done

echo
echo "==> Listo. Comando: /linear-sync   Config por proyecto: linear-sync.env (ver $AQUI/README.md)"
