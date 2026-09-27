#!/usr/bin/env bash
# ============================================================
#  install.sh — instala el kit en una instalacion de OpenCode
#
#  Que hace:
#    1. Copia las skills a ~/.config/opencode/skills/
#    2. Mergea config/opencode.fragment.json en opencode.json
#       (solo claves que NO existan; backup antes de tocar)
#    3. Opcionalmente instala el MCP de Notion
#    4. Genera un .env de ejemplo con las rutas locales reales
#
#  Que NO hace:
#    - No sobrescribe opencode.json. Mergea.
#    - No toca tu mcp, model, permissions, ni nada que ya exista.
#    - No escribe ningun secreto.
#
#  Uso:
#    ./install.sh                    # instalacion normal
#    ./install.sh --with-mcp-notion  # ademas instala el MCP de Notion
#    ./install.sh --uninstall        # deshace todo
# ============================================================

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CFG="$CFG_DIR/opencode.json"
WITH_MCP=0
UNINSTALL=0

for a in "$@"; do
  case "$a" in
    --with-mcp-notion) WITH_MCP=1 ;;
    --uninstall)      UNINSTALL=1 ;;
    -h|--help)        sed -n '3,20p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $a" >&2; exit 1 ;;
  esac
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

# ------------------------------------------------------------------
# Uninstall
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  echo "Desinstalando el kit..."
  for s in notion-autopilot azure-sync; do
    if [[ -d "$CFG_DIR/skills/$s" ]]; then
      rm -rf "$CFG_DIR/skills/$s"
      say "skill removida: $s"
    fi
  done

  if [[ -f "$CFG" ]]; then
    BK="$(ls -t "$CFG".bak.* 2>/dev/null | head -1)"
    if [[ -n "$BK" ]]; then
      cp "$BK" "$CFG"
      warn "opencode.json restaurado desde $(basename "$BK")"
    else
      warn "no hay backup previo, no toco opencode.json. Editalo a mano."
    fi
  fi
  say "Hecho. Los .env de cada proyecto quedaron intactos."
  exit 0
fi

# ------------------------------------------------------------------
# 1. Skills
# ------------------------------------------------------------------
echo "==> Instalando skills en $CFG_DIR/skills"
mkdir -p "$CFG_DIR/skills"
for s in notion-autopilot azure-sync; do
  if [[ -d "$CFG_DIR/skills/$s" ]]; then
    warn "$s ya existe. Se sobreescribe solo si usas --force (no implementado; borralo a mano si queres)."
  else
    cp -r "$KIT_DIR/skills/$s" "$CFG_DIR/skills/"
    say "$s"
  fi
  [[ -f "$CFG_DIR/skills/$s/watcher.sh"   ]] && chmod +x "$CFG_DIR/skills/$s/watcher.sh"
  [[ -f "$CFG_DIR/skills/$s/notion-set.sh" ]] && chmod +x "$CFG_DIR/skills/$s/notion-set.sh"
done

# ------------------------------------------------------------------
# 2. Config: merge, nunca overwrite
# ------------------------------------------------------------------
echo
echo "==> Mergeando config en $CFG"
command -v python3 >/dev/null || { err "necesita python3"; exit 1; }

python3 - "$KIT_DIR/config/opencode.fragment.json" "$CFG" << 'PY'
import json, os, shutil, sys, time

frag_p, cfg_p = sys.argv[1], sys.argv[2]

with open(frag_p, encoding="utf-8") as f:
    frag = json.load(f)

if os.path.exists(cfg_p):
    with open(cfg_p, encoding="utf-8") as f:
        cur = json.load(f)
    first = not cur
else:
    cur, first = {}, True

# backup
if not first:
    bak = "%s.bak.%s" % (cfg_p, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(cfg_p, bak)
    print("  backup: %s" % os.path.basename(bak))

added, skipped = [], []
for section in ("agents", "commands"):
    cur.setdefault(section, {})
    for name, body in frag.get(section, {}).items():
        if name in cur[section]:
            skipped.append("%s.%s" % (section, name))
        else:
            cur[section][name] = body
            added.append("%s.%s" % (section, name))

if "$schema" not in cur:
    cur["$schema"] = frag.get("$schema", "https://opencode.ai/config.json")

os.makedirs(os.path.dirname(cfg_p), exist_ok=True)
with open(cfg_p, "w", encoding="utf-8") as f:
    json.dump(cur, f, ensure_ascii=False, indent=2)
    f.write("\n")

for a in added:
    print("  + %s" % a)
for s in skipped:
    print("  = %s (ya existia, no se toco)" % s)
if not added and not skipped:
    print("  nada que hacer")
PY

rc=$?
[[ $rc -ne 0 ]] && { err "el merge fallo. Revisá el backup."; exit 1; }

# ------------------------------------------------------------------
# 3. MCP de Notion (opcional)
# ------------------------------------------------------------------
if [[ "$WITH_MCP" == 1 ]]; then
  echo
  echo "==> Instalando MCP de Notion"
  if command -v opencode >/dev/null; then
    if opencode mcp list 2>/dev/null | grep -q "notion"; then
      warn "el MCP notion ya esta"
    else
      opencode mcp add notion --global --url https://mcp.notion.com/mcp \
        && say "notion agregado (podes necesitar autenticarte)"
    fi
  else
    warn "opencode no esta en el PATH. Corre manualmente:"
    warn "  opencode mcp add notion --global --url https://mcp.notion.com/mcp"
  fi
fi

# ------------------------------------------------------------------
# 4. Ejemplo de proyecto con rutas reales
# ------------------------------------------------------------------
echo
echo "==> Generando ejemplo de proyecto"
PROJ="${1:-}"
if [[ -n "$PROJ" && -d "$PROJ" ]]; then
  for f in notion-autopilot azure-sync; do
    src="$KIT_DIR/examples/proyecto/$f.env.example"
    dst="$PROJ/$f.env"
    if [[ -f "$dst" ]]; then
      warn "$f.env ya existe en $PROJ, no se toco"
    else
      sed "s|/ruta/absoluta/a/este/proyecto|$PROJ|g" "$src" > "$dst"
      say "$f.env creado en $PROJ (con REPO_PATH=$PROJ)"
    fi
  done
  if [[ -f "$PROJ/.gitignore" ]] && ! grep -q "secrets.env" "$PROJ/.gitignore"; then
    printf '\n# secretos del kit\n*.secrets.env\n' >> "$PROJ/.gitignore"
    say ".gitignore actualizado"
  fi
else
  say "Para generar un .env en un proyecto, reejecuta:"
  say "  $0 $WITH_MCP -- $(pwd)"
fi

echo
echo "==> Listo. Resumen:"
echo
echo "  Skills:    $CFG_DIR/skills/{notion-autopilot,azure-sync}"
echo "  Comandos:  /autopilot  /azure-sync"
echo
echo "  Falta hacer a mano:"
echo "   1. Editar los .env del proyecto: poner NOTION_TOKEN y los IDs"
echo "   2. Compartir tablero y log con la integracion de Notion"
if [[ "$WITH_MCP" == 0 ]]; then
  echo "   3. (opcional) MCP de Notion: opencode mcp add notion --global --url https://mcp.notion.com/mcp"
fi
echo
echo "  Documentacion: $KIT_DIR/README.md"
