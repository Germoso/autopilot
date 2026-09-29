#!/usr/bin/env bash
# ============================================================
#  install.sh — instala el kit para OpenCode y/o Claude Code
#
#  Que instala:
#    - scripts (board, watcher, azure-sync, guardas de git, MCP) en
#      ~/.local/share/autopilot-kit/   (compartidos por ambos clientes)
#    - skills autopilot y azure-sync   en la carpeta de skills de cada cliente
#    - agentes coder y qa-reviewer, generados desde agents/*.md
#      con los bloqueos de git propios de cada cliente
#    - (OpenCode) comandos /autopilot y /azure-sync
#      (en Claude Code las skills ya son /autopilot y /azure-sync)
#
#  Que NO hace:
#    - No pisa archivos que no genero el kit.
#    - No escribe ningun secreto.
#
#  Uso:
#    ./install.sh                        # detecta los clientes instalados
#    ./install.sh --opencode --claude    # elige clientes explicitamente
#    ./install.sh --with-ado-mcp <org>   # ademas registra el MCP local de Azure DevOps
#    ./install.sh --init /mi/proyecto --base dev        # prepara un repo (o usa /autopilot-init)
#    ./install.sh --init /mi/workspace --base app=dev  # workspace: carpeta con varios repos
#    ./install.sh --uninstall            # deshace todo lo instalado por el kit
# ============================================================

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
SECRETS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autopilot-kit"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILLS=(autopilot autopilot-init azure-sync)
MARCA=".autopilot-kit"
RENDER="$KIT_DIR/clients/render.py"

WANT_OC=0; WANT_CC=0; UNINSTALL=0; PROJ=""; ADO_ORG=""; BASES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)     WANT_OC=1 ;;
    --claude)       WANT_CC=1 ;;
    --uninstall)    UNINSTALL=1 ;;
    --with-ado-mcp) shift; ADO_ORG="${1:-}"; [[ -z "$ADO_ORG" ]] && { echo "--with-ado-mcp necesita la organizacion" >&2; exit 1; } ;;
    --base)         shift; [[ -z "${1:-}" ]] && { echo "--base necesita la rama (o repo=rama)" >&2; exit 1; }; BASES+=(--base "$1") ;;
    --init)         shift; PROJ="${1:-}";    [[ -z "$PROJ" ]] && { echo "--init necesita una ruta" >&2; exit 1; } ;;
    -h|--help)      sed -n '3,27p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1 (ver --help)" >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

command -v python3 >/dev/null || { err "necesita python3"; exit 1; }

# Sin flags de cliente: los que esten instalados
if [[ $WANT_OC == 0 && $WANT_CC == 0 ]]; then
  { command -v opencode >/dev/null || [[ -d "$OC_DIR" ]]; } && WANT_OC=1
  { command -v claude   >/dev/null || [[ -d "$CC_DIR" ]]; } && WANT_CC=1
  [[ $WANT_OC == 0 && $WANT_CC == 0 ]] && { err "no encuentro OpenCode ni Claude Code. Usa --opencode o --claude."; exit 1; }
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
  echo "==> Desinstalando (${CLIENTES[*]})"
  for c in "${CLIENTES[@]}"; do
    cfg="$(cfg_de "$c")"
    for s in "${SKILLS[@]}"; do
      if [[ -f "$cfg/skills/$s/$MARCA" ]]; then rm -rf "$cfg/skills/$s"; say "$c: skill $s"; fi
    done
    python3 "$RENDER" uninstall "$c" "$cfg"
    [[ "$c" == opencode ]] && oc_mcp del
    [[ "$c" == claude ]] && cc_mcp del
  done
  [[ -d "$KIT" ]] && rm -rf "$KIT" && say "scripts: $KIT"
  say "Hecho. Quedaron intactos: los proyectos (.env, board, guardas) y $SECRETS_DIR (tu PAT)."
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
cp "$KIT_DIR"/lib/*.py "$KIT_DIR"/lib/*.sh "$KIT_DIR/clients/render.py" "$KIT/" && chmod +x "$KIT"/*.sh "$KIT"/*.py
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
done
[[ -d "$OC_DIR/skills/notion-autopilot" ]] && warn "queda la skill vieja notion-autopilot: rm -rf $OC_DIR/skills/notion-autopilot"

# ------------------------------------------------------------------
# 3. MCP de Azure DevOps (opcional)
# ------------------------------------------------------------------
if [[ -n "$ADO_ORG" ]]; then
  echo; echo "==> MCP de Azure DevOps ($ADO_ORG)"
  for c in "${CLIENTES[@]}"; do
    [[ "$c" == opencode ]] && oc_mcp set "$KIT/ado-mcp.sh" "$ADO_ORG"
    [[ "$c" == claude ]] && cc_mcp set "$KIT/ado-mcp.sh" "$ADO_ORG"
  done
  mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
  if [[ ! -f "$SECRETS_DIR/ado-mcp.secrets.env" ]]; then
    warn "falta el PAT. Guardalo (en tu terminal, no en el chat del agente):"
    echo "    (umask 077; read -rsp 'PAT: ' p; echo; printf 'AZURE_DEVOPS_PAT=%s\\n' \"\$p\" > $SECRETS_DIR/ado-mcp.secrets.env)"
  fi
fi

echo
echo "==> Listo (${CLIENTES[*]})."
echo "  Comandos:  /autopilot  /azure-sync"
echo "  Proyecto:  $0 --init /ruta/al/proyecto"
echo "  Docs:      $KIT_DIR/README.md"
