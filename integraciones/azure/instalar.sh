#!/usr/bin/env bash
# ============================================================
#  instalar.sh — integracion OPCIONAL de Azure DevOps para el autopilot
#
#  El autopilot no depende de Azure: esta integracion es un cliente externo
#  del board que importa Work Items como tareas new (azure-sync.py) y,
#  si queres, registra el MCP de Azure DevOps en tu cliente.
#
#  Instala TODO de forma LOCAL al proyecto (igual que el kit del autopilot):
#    - azure-sync.py y ado-mcp.sh en <proyecto>/.autopilot/integraciones/azure/
#    - la skill azure-sync enrutada en la carpeta del proyecto (.opencode,
#      .claude, .pi)
#    - (OpenCode) el comando /azure-sync en el proyecto
#    - (--with-mcp <org>) el MCP azure-devops en el proyecto (.opencode/opencode.json
#      o .mcp.json), NO en tu config global
#
#  No escribe nada en tu config global. azure-sync.py es autocontenido (escribe
#  directo los .md del board), asi que esta integracion no exige el kit.
#
#  Uso (local a la carpeta actual):
#    integraciones/azure/instalar.sh [--opencode --claude --pi]
#    integraciones/azure/instalar.sh --local <carpeta> [--opencode --claude --pi]
#    integraciones/azure/instalar.sh --with-mcp <org>
#    integraciones/azure/instalar.sh --uninstall --local <carpeta>   # quita lo local
#    integraciones/azure/instalar.sh --uninstall                     # quita la copia GLOBAL
#                                    #  (que instalaban las versiones viejas del kit)
# ============================================================

set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autopilot-kit"
MARCA=".autopilot-integracion"
MARCA_CMD="# generado por integraciones/azure/instalar.sh. No editar: se regenera."
# Rutas GLOBALES de la copia vieja (solo para --uninstall de herencia)
KIT_LEGACY="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
LEGACY_DEST="$KIT_LEGACY/integraciones/azure"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

WANT_OC=0; WANT_CC=0; WANT_PI=0; UNINSTALL=0; LOCAL_MODE=0; AZ_PROY=""; ADO_ORG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)   WANT_OC=1 ;;
    --claude)     WANT_CC=1 ;;
    --pi)         WANT_PI=1 ;;
    --local)      LOCAL_MODE=1; AZ_PROY="${2:-}"; shift ;;
    --uninstall)  UNINSTALL=1 ;;
    --with-mcp)   shift; ADO_ORG="${1:-}"; [[ -z "$ADO_ORG" ]] && { echo "--with-mcp necesita la organizacion" >&2; exit 1; } ;;
    -h|--help)    sed -n '3,34p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1 (ver --help)" >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

if [[ $WANT_OC == 0 && $WANT_CC == 0 && $WANT_PI == 0 ]]; then WANT_OC=1; WANT_CC=1; WANT_PI=1; fi
CLIENTES=()
[[ $WANT_OC == 1 ]] && CLIENTES+=(opencode)
[[ $WANT_CC == 1 ]] && CLIENTES+=(claude)
[[ $WANT_PI == 1 ]] && CLIENTES+=(pi)
K_DIR() { case "$1" in opencode) echo ".opencode";; claude) echo ".claude";; pi) echo ".pi";; esac; }
KSUBS() { case "$1" in opencode) echo "skill";; claude) echo "skills";; pi) echo "skills";; esac; }

# ------------------------------------------------------------------
# Uninstall LOCAL (por proyecto)
# ------------------------------------------------------------------
do_uninstall_local() {
  AZ_PROY="$(cd "$AZ_PROY" 2>/dev/null && pwd)" || { err "no existe: $AZ_PROY"; exit 1; }
  echo "==> Quitando la integracion Azure local de: $AZ_PROY"
  rm -rf "$AZ_PROY/.autopilot/integraciones/azure" && say "scripts: .autopilot/integraciones/azure"
  for c in "${CLIENTES[@]}"; do
    d="$AZ_PROY/$(K_DIR "$c")/$(KSUBS "$c")/azure-sync"
    [[ -f "$d/$MARCA" ]] && { rm -rf "$d"; say "$c: skill azure-sync"; }
    cmd="$AZ_PROY/$(K_DIR "$c")/command/azure-sync.md"
    [[ "$c" == opencode && -f "$cmd" ]] && grep -qF "$MARCA_CMD" "$cmd" && { rm -f "$cmd"; say "opencode: /azure-sync"; }
  done
  python3 - "$AZ_PROY" <<'PY'
import json, os, sys
proy = sys.argv[1]
# opencode project mcp
op = os.path.join(proy, ".opencode", "opencode.json")
if os.path.exists(op):
    try:
        d = json.load(open(op, encoding="utf-8"))
        m = d.get("mcp", {})
        s = m.get("servers", m) if isinstance(m, dict) else {}
        if "azure-devops" in s and ("ado-mcp.sh" in str(s["azure-devops"])):
            del s["azure-devops"]
            if not s and set(d) == {"mcp"}:
                os.remove(op); print("+ opencode: MCP azure-devops del proyecto (config vacia, se borro)")
            else:
                json.dump(d, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                print("+ opencode: MCP azure-devops del proyecto")
    except Exception:
        pass
# claude project mcp
mcp = os.path.join(proy, ".mcp.json")
if os.path.exists(mcp):
    try:
        d = json.load(open(mcp, encoding="utf-8"))
        s = d.get("mcpServers", {})
        if "azure-devops" in s:
            del s["azure-devops"]
            if not s:
                os.remove(mcp); print("+ claude: MCP azure-devops del proyecto (.mcp.json borrado)")
            else:
                json.dump(d, open(mcp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                print("+ claude: MCP azure-devops del proyecto (.mcp.json)")
    except Exception:
        pass
PY
  echo "==> Listo. Esta carpeta quedo sin integracion Azure."
  exit 0
}

# ------------------------------------------------------------------
# Uninstall GLOBAL (herencia de versiones viejas del kit)
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 && "$LOCAL_MODE" == 1 ]]; then do_uninstall_local; fi
if [[ "$UNINSTALL" == 1 ]]; then
  for c in "${CLIENTES[@]}"; do
    cfg="$OC_DIR"; [[ "$c" == claude ]] && cfg="$CC_DIR"
    if [[ -f "$cfg/skills/azure-sync/$MARCA" ]]; then rm -rf "$cfg/skills/azure-sync"; say "$c: skill azure-sync"; fi
    cmd="$cfg/commands/azure-sync.md"
    if [[ "$c" == opencode && -f "$cmd" ]] && grep -qF "$MARCA_CMD" "$cmd"; then rm -f "$cmd"; say "opencode: comando /azure-sync"; fi
  done
  [[ -d "$LEGACY_DEST" ]] && rm -rf "$LEGACY_DEST" && say "scripts: $LEGACY_DEST"
  [[ -f "$HOME/.local/bin/azure-sync" ]] && grep -qF "$MARCA_CMD" "$HOME/.local/bin/azure-sync" && rm -f "$HOME/.local/bin/azure-sync" && say "comando: $HOME/.local/bin/azure-sync"
  rmdir "$KIT_LEGACY/integraciones" "$KIT_LEGACY" 2>/dev/null
  say "Hecho. La integracion Azure de tu config global quedo quitada (los proyectos y sus .env no se tocaron)."
  exit 0
fi

# ------------------------------------------------------------------
# Install LOCAL
# ------------------------------------------------------------------
if [[ "$LOCAL_MODE" == 1 && -z "$AZ_PROY" ]]; then
  err "--local necesita una carpeta (o corre sin flags en la carpeta del proyecto)"; exit 1
fi
AZ_PROY="${AZ_PROY:-$PWD}"
AZ_PROY="$(cd "$AZ_PROY" 2>/dev/null && pwd)" || { err "no existe: $AZ_PROY"; exit 1; }
DEST="$AZ_PROY/.autopilot/integraciones/azure"
echo "==> Integracion Azure LOCAL en: $AZ_PROY (no toca tu config global)"

mkdir -p "$DEST"
cp "$AQUI/azure-sync.py" "$AQUI/ado-mcp.sh" "$AQUI/instalar.sh" "$AQUI/azure-sync.env.example" "$DEST/" && chmod +x "$DEST"/*.py "$DEST"/*.sh
say "scripts en $DEST"

for c in "${CLIENTES[@]}"; do
  base="$AZ_PROY/$(K_DIR "$c")/$(KSUBS "$c")"
  mkdir -p "$base"
  dst="$base/azure-sync"
  if [[ -d "$dst" && ! -f "$dst/$MARCA" && ! -f "$dst/.autopilot-kit" ]]; then
    warn "$c: skill azure-sync ya existe y no es de la integracion, no se toco"
  else
    rm -rf "$dst"; cp -r "$AQUI/skill" "$dst"; touch "$dst/$MARCA"
    # K= y los caminos del kit global -> la copia LOCAL de la integracion
    python3 - "$dst" "$DEST" <<'PY'
import os, sys
root, dest = sys.argv[1], sys.argv[2]
viejo = "~/.local/share/autopilot-kit/integraciones/azure"
for dp, _, fs in os.walk(root):
    for f in fs:
        if f.endswith(".md"):
            p = os.path.join(dp, f)
            s = open(p, encoding="utf-8").read()
            if viejo in s:
                open(p, "w", encoding="utf-8").write(s.replace(viejo, dest))
PY
    say "$c: skill azure-sync (K -> $DEST)"
  fi
  if [[ "$c" == opencode ]]; then
    cmd="$AZ_PROY/.opencode/command/azure-sync.md"
    mkdir -p "$AZ_PROY/.opencode/command"
    if [[ -f "$cmd" ]] && ! grep -qF "$MARCA_CMD" "$cmd" && ! grep -q "autopilot-kit" "$cmd"; then
      warn "opencode: $cmd ya existe y no es de la integracion, no se toco"
    else
      printf -- '---\n%s\ndescription: "Importa Work Items de Azure DevOps al board de workitems como new (aditivo, con dedup)"\n---\nCarga la skill `azure-sync` y sigue su seccion "Arranque" en ESTE proyecto, paso por paso. Es la unica fuente de instrucciones.\n\n$ARGUMENTS\n' "$MARCA_CMD" > "$cmd"
      say "opencode: comando /azure-sync"
    fi
  fi
done

if [[ -n "$ADO_ORG" ]]; then
  echo; echo "==> MCP de Azure DevOps por proyecto ($ADO_ORG)"
  python3 - "$AZ_PROY" "$DEST/ado-mcp.sh" "$ADO_ORG" <<'PY'
import json, os, sys
proy, mcp_script, org = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = ["python3", mcp_script, org]
# opencode: proyecto
op = os.path.join(proy, ".opencode", "opencode.json")
os.makedirs(os.path.dirname(op), exist_ok=True)
d = json.load(open(op, encoding="utf-8")) if os.path.exists(op) else {}
mcp = d.setdefault("mcp", {})
tabla = mcp["servers"] if isinstance(mcp.get("servers"), dict) else mcp
if "azure-devops" in tabla and ("ado-mcp.sh" not in str(tabla["azure-devops"])):
    print("  = opencode: azure-devops ya existe y no es de la integracion, no se toco")
else:
    tabla["azure-devops"] = {"type": "local", "command": cmd}
    json.dump(d, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  + opencode del proyecto: MCP azure-devops -> %s" % " ".join(cmd))
# claude: proyecto (.mcp.json)
mcpf = os.path.join(proy, ".mcp.json")
d = json.load(open(mcpf, encoding="utf-8")) if os.path.exists(mcpf) else {}
servers = d.setdefault("mcpServers", {})
if "azure-devops" in servers:
    print("  = claude del proyecto: azure-devops ya existia en .mcp.json, se actualiza")
servers["azure-devops"] = {"command": "python3", "args": [mcp_script, org]}
json.dump(d, open(mcpf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  + claude del proyecto: MCP azure-devops en .mcp.json")
PY
  mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
  if [[ ! -f "$SECRETS_DIR/ado-mcp.secrets.env" ]]; then
    warn "falta el PAT. Guardalo (en tu terminal, no en el chat del agente):"
    echo "    (umask 077; read -rsp 'PAT: ' p; echo; printf 'AZURE_DEVOPS_PAT=%s\\n' \"\$p\" > $SECRETS_DIR/ado-mcp.secrets.env)"
  fi
fi

echo
echo "==> Listo. En el agente: /azure-sync   En la terminal:"
echo "    python3 $DEST/azure-sync.py --dry-run   (en la carpeta del proyecto)"
echo "    Config por proyecto: azure-sync.env (ver $AQUI/README.md)"
echo "    Quitar de esta carpeta: integraciones/azure/instalar.sh --uninstall --local $AZ_PROY"