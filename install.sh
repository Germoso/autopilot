#!/usr/bin/env bash
# ============================================================
#  install.sh — instala el kit AUTOPILOT de forma LOCAL (por proyecto).
#
#  Todo el kit se instala DENTRO de la carpeta del proyecto donde lo corras
#  (por defecto la carpeta actual). No escribe nada en tu config global
#  (~/.config/opencode, ~/.claude, ~/.pi/agent, ~/.local/share/...).
#  Por eso solo funciona donde se instaló: esa carpeta tiene .autopilot/,
#  y fuera de ella ninguna skill ni agente existe.
#
#  Que instala, dentro de <proyecto>/:
#    - .autopilot/                  el kit local: validadores (aenv.sh,
#                                   entorno.py), skills, agente coder fuente
#    - .pi/skills/    skills+agentes para pi          (cliente pi)
#    - .opencode/     skill+agent+commands de opencode (cliente opencode)
#    - .claude/       skills+agents de Claude Code    (cliente claude)
#    - .gitignore     + bloque "# autopilot-kit (local)": nada se commitea
#    - .pi/settings.json   si instalas con pi: declara la extension
#                          npm:@juicesharp/rpiv-ask-user-question (pi install --local),
#                          SOLO cuando pi esta entre los clientes
#
#  Reinstalar SIEMPRE sobreescribe las copias viejas del kit dentro del proyecto
#  (aunque les falte la marca interna de la v2) y limpia los restos de la v1
#  (pi-guard*.mjs, comandos de pi, wi.sh, watcher, carpetas de estado viejas
#  del board: in-progress/bug-fix/reviewed/qa). Asi nunca queda corriendo una
#  version vieja.
#
#  El resto de la maquinaria (worktrees, lanzar al coder, vigilar, notificar)
#  la maneja Orca (orca orchestration + orca worktree), no scripts del kit.
#
#  Uso:
#    ./install.sh                       # LOCAL en la carpeta actual (clientes: los 3)
#    ./install.sh --local <carpeta>     # LOCAL en <carpeta>
#    ./install.sh --opencode --claude --pi   # elige clientes (default: los 3)
#    ./install.sh --cli                  # instala el comando GLOBAL "autopilot" (launcher fino)
#                                        #  en ~/.local/bin (otra ruta: AUTOPILOT_BIN_DIR)
#    ./install.sh --cli --local <carpeta>   # CLI global + instalacion local de un proyecto
#    ./install.sh --azure                # SOLO la integracion de Azure DevOps (apart)
#    ./install.sh --uninstall            # desinstala la copia GLOBAL heredada
#                                        #  (la que instalan versiones viejas del kit)
#    ./install.sh --uninstall --local <carpeta>   # quita la instalacion LOCAL de <carpeta>
#    ./install.sh --uninstall --cli      # quita el comando GLOBAL "autopilot"
# ============================================================

set -uo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER="$KIT_DIR/clients/render.py"
SKILLS=(autopilot autopilot-init autopilot-plan ponytail tdd)
MARCA=".autopilot-kit"
# Rutas GLOBALES de versiones viejas (solo para --uninstall de herencia)
KIT_LEGACY="${XDG_DATA_HOME:-$HOME/.local/share}/autopilot-kit"
OC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CC_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
PI_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"

# --azure: solo la integracion de Azure (sin el kit). El resto de flags va a ella.
RESTO=(); SOLO_AZURE=0
for a in "$@"; do [[ "$a" == --azure ]] && SOLO_AZURE=1 || RESTO+=("$a"); done
[[ "$SOLO_AZURE" == 1 ]] && exec "$KIT_DIR/integraciones/azure/instalar.sh" "${RESTO[@]}"

WANT_OC=0; WANT_CC=0; WANT_PI=0; UNINSTALL=0; LOCAL_MODE=0; CLI=0; PROY=""
for a in "$@"; do
  [[ "$a" == -h || "$a" == --help ]] && { sed -n '3,50p' "$0"; exit 0; }
done
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencode)     WANT_OC=1 ;;
    --claude)       WANT_CC=1 ;;
    --pi)           WANT_PI=1 ;;
    --local)        LOCAL_MODE=1; PROY="${2:-}"; shift ;;
    --cli)          CLI=1 ;;
    --uninstall)    UNINSTALL=1 ;;
    -h|--help)      sed -n '3,40p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1 (ver --help). Si preparas un proyecto usa /autopilot-init (crea autopilot.env + board)." >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

command -v python3 >/dev/null || { err "necesita python3"; exit 1; }

# Clientes por defecto: los tres (la instalacion local queda lista para cualquiera
# que abras en esa carpeta). -cliente* filtra.
if [[ $WANT_OC == 0 && $WANT_CC == 0 && $WANT_PI == 0 ]]; then WANT_OC=1; WANT_CC=1; WANT_PI=1; fi
CLIENTES=()
[[ $WANT_OC == 1 ]] && CLIENTES+=(opencode)
[[ $WANT_CC == 1 ]] && CLIENTES+=(claude)
[[ $WANT_PI == 1 ]] && CLIENTES+=(pi)

K_DIR() { case "$1" in opencode) echo ".opencode";; claude) echo ".claude";; pi) echo ".pi";; esac; }
# Carpetas de skills por cliente dentro del proyecto (opencode usa singular).
KSUBS() { case "$1" in opencode) echo "skill";; claude) echo "skills";; pi) echo "skills";; esac; }

# ------------------------------------------------------------------
# --uninstall --local <carpeta>: quita SOLO la instalacion LOCAL de esa carpeta
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 && "$LOCAL_MODE" == 1 ]]; then
  [[ -z "$PROY" ]] && { err "--uninstall --local necesita una carpeta (o usa --uninstall solo para lo global)"; exit 1; }
  PROY="$(cd "$PROY" 2>/dev/null && pwd)" || { err "no existe: $PROY"; exit 1; }
  echo "==> Quitando la instalacion local de autopilot: $PROY"
  rm -rf "$PROY/.autopilot"
  say ".autopilot/"
  for c in "${CLIENTES[@]}"; do
    p="$PROY/$(K_DIR "$c")/$(KSUBS "$c")"
    for s in "${SKILLS[@]}"; do
      d="$p/$s"
      [[ -f "$d/$MARCA" ]] && { rm -rf "$d"; say "$c: skill $s"; }
    done
    python3 "$RENDER" local-uninstall "$c" "$PROY"
    # quita la extension de pi que instalo el kit (si pi es cliente): local, .pi/settings.json
    if [[ "$c" == "pi" ]] && command -v pi >/dev/null 2>&1; then
      (cd "$PROY" && pi remove --local npm:@juicesharp/rpiv-ask-user-question >/dev/null 2>&1) \
        && say "pi: extension rpiv-ask-user-question retirada"
    fi
    # quita carpetas de cliente que quedaron vacias (solo si no tienen contenido propio)
    # quita carpetas de cliente que quedaron vacias (solo si no tienen contenido propio)
    rmdir "$p" "$PROY/$(K_DIR "$c")/agents" "$PROY/$(K_DIR "$c")/agent" \
          "$PROY/$(K_DIR "$c")/commands" "$PROY/$(K_DIR "$c")/command" "$PROY/$(K_DIR "$c")" 2>/dev/null
  done
  # gitignore: quita el bloque del kit local
  GI="$PROY/.gitignore"
  if [[ -f "$GI" ]]; then
    python3 - "$GI" <<'PY'
import os, sys
p = sys.argv[1]; s = open(p, encoding="utf-8").read()
inicio = "# --- autopilot-kit (local) ---"; fin = "# --- fin autopilot-kit (local) ---"
if inicio in s:
    a, b = s.index(inicio), s.index(fin)+len(fin)
    rest = (s[:a]+s[b:]).lstrip("\n")
    if rest.strip():   # quedo algo: se escribe; si quedo vacio, se borra el archivo
        open(p, "w", encoding="utf-8").write(rest)
        print("+ .gitignore: bloque del kit quitado")
    else:
        os.remove(p)
        print("+ .gitignore: estaba vacio, se borro")
else:
    print("= .gitignore: sin bloque del kit, nada que quitar")
PY
  fi
  echo; echo "==> Listo. Esta carpeta quedo sin autopilot. Otras instalaciones y tu config global no se tocaron."
  exit 0
fi

# ------------------------------------------------------------------
# --uninstall --cli: quita el comando GLOBAL "autopilot"
# ------------------------------------------------------------------
BIN_DIR="${AUTOPILOT_BIN_DIR:-$HOME/.local/bin}"
if [[ "$UNINSTALL" == 1 && "$CLI" == 1 ]]; then
  if [[ -f "$BIN_DIR/autopilot" ]]; then
    rm -f "$BIN_DIR/autopilot"
    say "cli: $BIN_DIR/autopilot quitado"
  else
    warn "cli: no habia nada en $BIN_DIR/autopilot"
  fi
  echo; echo "==> Listo. Las instalaciones LOCALES de cada proyecto no se tocaron."
  exit 0
fi

# ------------------------------------------------------------------
# --cli: instala (o actualiza) el comando GLOBAL "autopilot".
# Es SOLO un launcher fino que delega en este mismo instalador; el kit
# sigue siendo LOCAL por proyecto. Nada mas se escribe fuera de $BIN_DIR.
# ------------------------------------------------------------------
if [[ "$CLI" == 1 ]]; then
  mkdir -p "$BIN_DIR"
  LAUNCHER_TMP="$BIN_DIR/autopilot.tmp"
  cat > "$LAUNCHER_TMP" <<'LAUNCHER'
#!/usr/bin/env bash
# autopilot — CLI global del kit (un launcher fino).
# El kit es LOCAL por proyecto; este comando solo delega en su instalador.
KIT_DIR="__KIT_DIR__"
INSTALL="$KIT_DIR/install.sh"

usage() {
  cat <<'HELP'
autopilot — instalador del kit de desarrollo autonomo (por proyecto).

Uso:
  autopilot install <proyecto> [--pi|--claude|--opencode]  instala el kit DENTRO del proyecto
  autopilot uninstall <proyecto>                           quita la instalacion local de un proyecto
  autopilot uninstall --global                             quita la copia GLOBAL vieja (herencia)
  autopilot azure ...                                      integracion de Azure DevOps (ver su ayuda)
  autopilot upgrade                                        actualiza el kit (git pull) y re-instala el CLI
  autopilot --help                                         esta ayuda

El kit nunca toca tu config global: solo crea .autopilot/, .pi/, .opencode/, .claude/
y un bloque en .gitignore DENTRO del proyecto donde lo instalas.
HELP
}

case "${1:-}" in
  install)
    shift
    [[ $# -ge 1 ]] || { echo "usa: autopilot install <proyecto> [--pi|--claude|--opencode]" >&2; exit 1; }
    exec bash "$INSTALL" --local "$@"
    ;;
  uninstall)
    shift
    if [[ "${1:-}" == "--global" || "${1:-}" == "-g" ]]; then
      shift; exec bash "$INSTALL" --uninstall "$@"
    fi
    [[ $# -ge 1 ]] || { echo "usa: autopilot uninstall <proyecto>  (o --global)" >&2; exit 1; }
    exec bash "$INSTALL" --uninstall --local "$@"
    ;;
  azure)
    shift; exec bash "$KIT_DIR/integraciones/azure/instalar.sh" "$@"
    ;;
  upgrade)
    git -C "$KIT_DIR" pull --ff-only || { echo "! no se pudo actualizar el repo del kit ($KIT_DIR)" >&2; exit 1; }
    exec bash "$INSTALL" --cli
    ;;
  -h|--help|"")
    usage; exit 0
    ;;
  *)
    echo "! subcomando desconocido: ${1:-} (usa: autopilot --help)" >&2
    exit 1
    ;;
esac
LAUNCHER
  sed "s|__KIT_DIR__|$KIT_DIR|" "$LAUNCHER_TMP" > "$BIN_DIR/autopilot"
  rm -f "$LAUNCHER_TMP"
  chmod +x "$BIN_DIR/autopilot"
  say "cli: $BIN_DIR/autopilot  (llamalo: autopilot install <proyecto>)"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR no esta en tu PATH: agrega  export PATH=\"\$PATH:$BIN_DIR\"  a tu shell, o usa AUTOPILOT_BIN_DIR" ;;
  esac
  [[ "$LOCAL_MODE" == 0 ]] && { echo; echo "==> Listo. Comando global: autopilot --help"; exit 0; }
  echo "    (ademas, sigue la instalacion local pedida con --local)"
fi

# ------------------------------------------------------------------
# --uninstall: quita la copia GLOBAL heredada de versiones viejas del kit
# ------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  echo "==> Quitando la copia GLOBAL heredada (${CLIENTES[*]}) — sin tocar instalaciones locales"
  for c in "${CLIENTES[@]}"; do
    case "$c" in
      opencode) cfg="$OC_DIR";;
      claude)   cfg="$CC_DIR";;
      pi)       cfg="$PI_DIR";;
    esac
    for s in "${SKILLS[@]}" azure-sync; do  # azure-sync: la instalaban versiones viejas del kit
      if [[ -f "$cfg/skills/$s/$MARCA" ]]; then rm -rf "$cfg/skills/$s"; say "$c: skill $s"; fi
    done
    python3 "$RENDER" uninstall "$c" "$cfg"
  done
  for h in "$KIT_LEGACY"/integraciones/*/instalar.sh; do
    [[ -f "$h" ]] && bash "$h" --uninstall "${CLIENTES[@]/#/--}"
  done
  [[ -f "$KIT_LEGACY/ado-mcp.sh" ]] && warn "queda registrado el MCP azure-devops de una version vieja: quitalo en tu cliente (p. ej. claude mcp remove azure-devops -s user)"
  [[ -d "$KIT_LEGACY" ]] && rm -rf "$KIT_LEGACY" && say "scripts globales: $KIT_LEGACY"
  say "Hecho. Las instalaciones LOCALES de cada proyecto y tus proyectos (.env, boards) quedaron intactos."
  exit 0
fi

# ------------------------------------------------------------------
# Instalacion LOCAL
# ------------------------------------------------------------------
if [[ "$LOCAL_MODE" == 1 && -z "$PROY" ]]; then
  err "--local necesita una carpeta (o corre ./install.sh sin flags en la carpeta del proyecto)"; exit 1
fi
PROY="${PROY:-$PWD}"
PROY="$(cd "$PROY" 2>/dev/null && pwd)" || { err "no existe: $PROY"; exit 1; }
KIT="$PROY/.autopilot"

echo "==> Instalacion LOCAL de autopilot en: $PROY"
echo "    (no toca tu config global)"
if [[ ! -d "$PROY/.git" && ! -f "$PROY/../../.git" ]]; then
  warn "no veo un repo git en $PROY: igual lo dejo, pero el autopilot necesita repos (autopilot.env + board)."
fi

# 0) Limpiar restos de versiones VIEJAS del kit dentro del proyecto (si existen).
#    La v1 del kit dejaba en el proyecto: pi-guard*.mjs (protegian subagentes),
#    comandos de pi, scripts wi.sh/watcher y carpetas de estado del board ya
#    inexistentes (in-progress/bug-fix/reviewed/qa).
for f in "$PROY"/.pi/extensions/pi-guard*.mjs; do
  [[ -f "$f" ]] && { rm -f "$f"; say "resto viejo: $f"; }
done
rm -f "$PROY"/.pi/commands/autopilot.md "$PROY"/.pi/commands/autopilot-init.md "$PROY"/.pi/commands/autopilot-plan.md "$PROY"/.pi/commands/azure-sync.md 2>/dev/null
rm -f "$PROY/wi.sh" "$PROY/watcher" 2>/dev/null

# Carpetas de estado VIEJAS del board (v1: in-progress/bug-fix/reviewed/qa, dentro de
# .workitems/ o en la raiz). Si tienen tareas se avisa (migralas a new/working/done/
# stopped); si estan vacias se eliminan. La purga deja .workitems/ recreado por el init.
limpiar_carpeta() {  # $1 = ruta completa
  local p="$1"
  [[ -d "$p" ]] || return 0
  if ls -A "$p" 2>/dev/null | grep -q .; then
    warn "board viejo: $p/ tiene tareas -> movelas a .workitems/new..stopped"
  else
    rmdir "$p" 2>/dev/null && say "board viejo: $p eliminada (vacia)"
  fi
}
for p in in-progress bug-fix reviewed qa; do
  limpiar_carpeta "$PROY/.workitems/$p"
  limpiar_carpeta "$PROY/$p"
done
rmdir "$PROY/.workitems" 2>/dev/null   # si quedo vacia tras purgar las carpetas viejas

# 1) Validadores de "nunca contra produccion" (aenv.sh + entorno.py), locales al proyecto
mkdir -p "$KIT"
cp "$KIT_DIR/skills/autopilot/aenv.sh" "$KIT_DIR/skills/autopilot/entorno.py" "$KIT/" && \
  chmod +x "$KIT/aenv.sh"
(python3 -m py_compile "$KIT/entorno.py" >/dev/null 2>&1) || warn "entorno.py no compila: revisa skills/autopilot/entorno.py"
say "validadores: aenv.sh entorno.py ($KIT)"

# 2) Copias canonicas en .autopilot/skills (con «K_DIR» resuelto al kit local)
sub_k() {  # sed sobre todas las copias: «K_DIR» -> ruta del kit local
  local raiz="$1"; shift
  find "$raiz" -name "*.md" -type f -print0 | while IFS= read -r -d '' f; do
    python3 - "$f" "$KIT" <<'PY'
import sys
p, kit = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
if "«K_DIR»" in s:
    open(p, "w", encoding="utf-8").write(s.replace("«K_DIR»", kit))
PY
  done
}
mkdir -p "$KIT/skills"
for s in "${SKILLS[@]}"; do
  rm -rf "$KIT/skills/$s"; cp -r "$KIT_DIR/skills/$s" "$KIT/skills/$s"; rm -rf "$KIT/skills/$s/__pycache__"
done
sub_k "$KIT/skills"

# 3) Agente fuente (con K local) en .autopilot/agents — la usa el orquestador para
#    lanzar al coder sin depender de agentes registrados en la config global.
for c in "${CLIENTES[@]}"; do
  python3 "$RENDER" local-install "$c" "$PROY" "$KIT" || { err "fallo generando el agente para $c"; exit 1; }
done
sub_k "$PROY/.autopilot/agents"

# 4) Enrutado por cliente dentro del proyecto
for c in "${CLIENTES[@]}"; do
  base="$PROY/$(K_DIR "$c")/$(KSUBS "$c")"
  echo "==> $c -> $base"
  mkdir -p "$base"
  for s in "${SKILLS[@]}"; do
    dst="$base/$s"
    if [[ -d "$dst" && ! -f "$dst/$MARCA" ]]; then
      warn "skill $s existia (version vieja del kit, sin la marca): se sobreescribe con la actual"
    fi
    rm -rf "$dst"; cp -r "$KIT/skills/$s" "$dst"; touch "$dst/$MARCA"
    say "skill $s"
  done
done

# 5) gitignore: bloque del kit local (nada del kit se commitea)
GI="$PROY/.gitignore"
[[ -f "$GI" ]] || : > "$GI"
if ! grep -q "# --- autopilot-kit (local) ---" "$GI"; then
  {
    echo
    echo "# --- autopilot-kit (local) ---"
    echo "/.autopilot/"
    echo ".pi/skills/"
    echo ".opencode/skill/"
    echo ".opencode/agent/"
    echo ".opencode/command/"
    echo ".claude/skills/"
    echo ".claude/agents/"
    echo "# --- fin autopilot-kit (local) ---"
  } >> "$GI"
  say "gitignore: bloque del kit local (nada de esto se commitea)"
fi

# 6) Extension de pi: rpiv-ask-user-question (solo si pi es cliente).
#    pi install --local la declara en .pi/settings.json del PROYECTO (nada en el home),
#    para que el coder use su herramienta de preguntas. Idempotente: si ya esta, no
#    vuelve a instalarla.
if [[ " ${CLIENTES[*]} " == *" pi "* ]]; then
  if command -v pi >/dev/null 2>&1; then
    if [[ -f "$PROY/.pi/settings.json" ]] && grep -q "rpiv-ask-user-question" "$PROY/.pi/settings.json" 2>/dev/null; then
      say "extension pi: rpiv-ask-user-question ya declarada (.pi/settings.json)"
    else
      if (cd "$PROY" && pi install --local npm:@juicesharp/rpiv-ask-user-question >/dev/null 2>&1); then
        say "extension pi: instalada rpiv-ask-user-question (.pi/settings.json, local)"
      else
        warn "no se pudo instalar la extension pi rpiv-ask-user-question (pi install --local fallo)"
      fi
    fi
  else
    warn "no encontre 'pi' en el PATH: no instale la extension rpiv-ask-user-question"
  fi
fi

echo
echo "==> Listo. Kit LOCAL instalado en $PROY (clientes: ${CLIENTES[*]})."
echo "  Tablero:  el board en .workitems/ (carpetas + .md) — los estados y las notas son archivos."
echo "  Ejecuta:  Orca (orca orchestration + orca worktree) lanza y vigila a los coders."
echo "  Preparar el proyecto al usarlo: /autopilot-init crea autopilot.env + board."
echo "  Desinstalar esta carpeta:  ./install.sh --uninstall --local $PROY"
[[ -f "$OC_DIR/skills/autopilot/$MARCA" ]] && warn "aun existe una copia GLOBAL vieja en opencode: quitala con ./install.sh --uninstall"
exit 0