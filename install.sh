#!/usr/bin/env bash
# ============================================================
#  install.sh — instala el kit para OpenCode, Claude Code y/o pi
#
#  Que instala:
#    - scripts (board, guardas de git, tablero de Orca) en
#      ~/.local/share/autopilot-kit/   (compartidos por todos los clientes)
#    - skills autopilot, autopilot-init, autopilot-plan, ponytail y tdd en la carpeta de skills de cada cliente
#    - agente coder, generado desde agents/*.md
#      con los bloqueos de git propios de cada cliente
#    - (OpenCode) comandos /autopilot-init, /autopilot-plan y /autopilot
#      (en Claude Code y pi las skills ya son esos comandos)
#    - (pi) extension de guard (pi-guard-*.mjs) que cancela push/merge, lo que toque
#      un ambiente sin aenv.sh y la escritura de .env* / fuera de las copias de trabajo
#
#  El tablero visual de tareas es agnostico de agente: orca-board (TUI + web)
#  lee las tareas de orquestacion de Orca (orca orchestration task-list).
#
#  Que NO hace:
#    - No pisa archivos que no genero el kit.
#    - No escribe ningun secreto.
#
#  Uso:
#    ./install.sh                        # detecta los clientes instalados
#    ./install.sh --opencode --claude --pi  # elige clientes explicitamente
#    ./install.sh --init /mi/proyecto --base dev        # prepara un repo (o usa /autopilot-init)
#    ./install.sh --init /mi/workspace --base app=dev  # workspace: carpeta con varios repos
#    ./install.sh --azure                # SOLO la integracion de Azure DevOps, sin el kit
#    ./install.sh --uninstall            # deshace todo lo instalado por el kit
# ============================================================

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
SECRETS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autopilot-kit"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
PI_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
SKILLS=(autopilot autopilot-init autopilot-plan ponytail tdd)
MARCA=".autopilot-kit"
RENDER="$KIT_DIR/clients/render.py"

# --azure: solo la integracion de Azure (sin el kit). El resto de flags (--claude, --uninstall...) va a ella.
RESTO=(); SOLO_AZURE=0
for a in "$@"; do [[ "$a" == --azure ]] && SOLO_AZURE=1 || RESTO+=("$a"); done
[[ "$SOLO_AZURE" == 1 ]] && exec "$KIT_DIR/integraciones/azure/instalar.sh" --sin-kit "${RESTO[@]}"

WANT_OC=0; WANT_CC=0; WANT_PI=0; UNINSTALL=0; PROJ=""; BASES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)     WANT_OC=1 ;;
    --claude)       WANT_CC=1 ;;
    --pi)           WANT_PI=1 ;;
    --uninstall)    UNINSTALL=1 ;;
    --base)         shift; [[ -z "${1:-}" ]] && { echo "--base necesita la rama (o repo=rama)" >&2; exit 1; }; BASES+=(--base "$1") ;;
    --init)         shift; PROJ="${1:-}";    [[ -z "$PROJ" ]] && { echo "--init necesita una ruta" >&2; exit 1; } ;;
    -h|--help)      sed -n '3,30p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1 (ver --help)" >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

command -v python3 >/dev/null || { err "necesita python3"; exit 1; }

# Sin flags de cliente: los que esten instalados
if [[ $WANT_OC == 0 && $WANT_CC == 0 && $WANT_PI == 0 ]]; then
  { command -v opencode >/dev/null || [[ -d "$OC_DIR" ]]; } && WANT_OC=1
  { command -v claude   >/dev/null || [[ -d "$CC_DIR" ]]; } && WANT_CC=1
  { command -v pi       >/dev/null || [[ -d "$PI_DIR" ]]; } && WANT_PI=1
  [[ $WANT_OC == 0 && $WANT_CC == 0 && $WANT_PI == 0 ]] && \
    { err "no encuentro OpenCode, Claude Code ni pi. Usa --opencode, --claude o --pi."; exit 1; }
fi
CLIENTES=()
[[ $WANT_OC == 1 ]] && CLIENTES+=(opencode)
[[ $WANT_CC == 1 ]] && CLIENTES+=(claude)
[[ $WANT_PI == 1 ]] && CLIENTES+=(pi)
cfg_de() { case "$1" in opencode) echo "$OC_DIR";; claude) echo "$CC_DIR";; pi) echo "$PI_DIR";; esac; }

# ------------------------------------------------------------------
# Uninstall
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  echo "==> Desinstalando (${CLIENTES[*]})"
  for c in "${CLIENTES[@]}"; do
    cfg="$(cfg_de "$c")"
    for s in "${SKILLS[@]}" azure-sync; do  # azure-sync: la instalaban versiones viejas del kit
      if [[ -f "$cfg/skills/$s/$MARCA" ]]; then rm -rf "$cfg/skills/$s"; say "$c: skill $s"; fi
    done
    python3 "$RENDER" uninstall "$c" "$cfg"
  done
  # Integraciones instaladas en el kit (integraciones/*/instalar.sh): se desinstalan con el.
  for h in "$KIT"/integraciones/*/instalar.sh; do
    [[ -f "$h" ]] && bash "$h" --uninstall "${CLIENTES[@]/#/--}"
  done
  [[ -f "$KIT/ado-mcp.sh" ]] && warn "queda registrado el MCP azure-devops de una version vieja: quitalo en tu cliente (p. ej. claude mcp remove azure-devops -s user)"
  [[ -d "$KIT" ]] && rm -rf "$KIT" && say "scripts: $KIT"
  say "Hecho. Quedaron intactos: los proyectos (.env, board, guardas) y $SECRETS_DIR."
  exit 0
fi

# ------------------------------------------------------------------
# Init de un proyecto
# ------------------------------------------------------------------
if [[ -n "$PROJ" ]]; then
  [[ -x "$KIT/init.py" ]] || { err "primero instala el kit: $0"; exit 1; }
  # Misma logica que /autopilot-init. --base <rama> (un repo) o --base <repo>=<rama> (workspace).
  python3 "$KIT/init.py" "$PROJ" "${BASES[@]}"
  exit $?
fi

# ------------------------------------------------------------------
# 1. Scripts compartidos
# ------------------------------------------------------------------
echo "==> Scripts en $KIT"
mkdir -p "$KIT"
cp "$KIT_DIR"/lib/*.py "$KIT_DIR"/lib/*.sh "$KIT_DIR"/lib/*.cjs "$KIT_DIR"/lib/*.dart "$KIT_DIR"/lib/*.mjs "$KIT_DIR/lib/run-tests" "$KIT_DIR/lib/health-check" "$KIT_DIR/lib/orca-board" \
  "$KIT_DIR/clients/render.py" "$KIT/" && chmod +x "$KIT"/*.sh "$KIT"/*.py "$KIT/run-tests" "$KIT/health-check" "$KIT/orca-board"
say "$(ls "$KIT" | tr '\n' ' ')"

# ------------------------------------------------------------------
# 2. Skills + agentes (+ comandos en OpenCode) por cliente
# ------------------------------------------------------------------
for c in "${CLIENTES[@]}"; do
  cfg="$(cfg_de "$c")"
  echo; echo "==> $c ($cfg)"
  mkdir -p "$cfg/skills"
  for s in "${SKILLS[@]}"; do
    dst="$cfg/skills/$s"
    if [[ -d "$dst" && ! -f "$dst/$MARCA" ]]; then
      warn "skill $s ya existe y no es del kit, no se toco"; continue
    fi
    rm -rf "$dst"; cp -r "$KIT_DIR/skills/$s" "$dst"; touch "$dst/$MARCA"
    say "skill $s"
  done
  python3 "$RENDER" install "$c" "$cfg" "$KIT" || { err "fallo generando agentes para $c"; exit 1; }
  # Versiones viejas instalaban azure-sync como parte del kit; ahora es una integracion aparte.
  if [[ -f "$cfg/skills/azure-sync/$MARCA" ]]; then
    rm -rf "$cfg/skills/azure-sync"
    warn "skill azure-sync quitada del kit: si la usas, integraciones/azure/instalar.sh"
  fi
done
rm -f "$KIT/azure-sync.py"
[[ -f "$KIT/ado-mcp.sh" ]] && warn "$KIT/ado-mcp.sh es de una version vieja (se deja para no romper el MCP registrado); integraciones/azure/instalar.sh --with-mcp <org> lo reemplaza"
[[ -d "$OC_DIR/skills/notion-autopilot" ]] && warn "queda la skill vieja notion-autopilot: rm -rf $OC_DIR/skills/notion-autopilot"

echo
echo "==> Listo (${CLIENTES[*]})."
[[ " ${CLIENTES[*]} " == *" pi "* ]] && echo "  (pi) Skills como /skill:autopilot y agente coder en $PI_DIR/agents"
if [[ " ${CLIENTES[*]} " == *" pi "* && " ${CLIENTES[*]} " != *" opencode "* ]]; then
  echo "  Comandos:  /skill:autopilot-init  /skill:autopilot-plan  /skill:autopilot"
else
  echo "  Comandos:  /autopilot-init  /autopilot-plan  /autopilot"
fi
echo "  Tablero Orca (agnostico):  $KIT/orca-board | $KIT/orca-board web"
echo "  Proyecto:  $0 --init /ruta/al/proyecto"
echo "  Docs:      $KIT_DIR/README.md"
