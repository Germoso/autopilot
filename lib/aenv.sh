#!/usr/bin/env bash
# ============================================================
#  aenv.sh — ejecuta un comando contra un ambiente SOLO con .env.autopilot
#
#  Unica forma en que el coder y el QA pueden correr algo que se conecte a un
#  ambiente (tests de integracion/e2e, levantar el backend, migraciones, scripts).
#  Valida el .env.autopilot del repo con entorno.py (local o QA, completo); si no
#  esta ok, NO ejecuta y dice que recomienda. Si esta ok, exporta sus variables
#  (las del proceso le ganan al .env del repo en dotenv/NestJS) y ejecuta.
#
#  El .env.autopilot lo crea el HUMANO. Nadie mas lo crea, edita ni copia.
#  Nunca espera para siempre: tiempo maximo COMMAND_TIMEOUT (autopilot.env, default 900 s).
#
#  uso: aenv.sh <repo o worktree> -- <comando> [args...]
# ============================================================
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${1:-}"; shift || true
[[ "${1:-}" == "--" ]] && shift
[[ -z "$REPO" || $# -eq 0 ]] && { echo "uso: aenv.sh <repo> -- <comando> [args...]" >&2; exit 2; }
[[ -d "$REPO" ]] || { echo "aenv: no existe $REPO" >&2; exit 2; }

VALIDACION="$(python3 "$DIR/entorno.py" "$REPO")"
ESTADO="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["estado"])' <<<"$VALIDACION")"
if [[ "$ESTADO" != "ok" ]]; then
  python3 -c '
import json,sys
d=json.load(sys.stdin)
print("aenv: NO SE EJECUTA (%s). Posible ambiente no seguro." % d["estado"], file=sys.stderr)
print("RECOMENDACION: " + d.get("recomendacion", ""), file=sys.stderr)' <<<"$VALIDACION"
  exit 3
fi

while IFS= read -r -d '' k && IFS= read -r -d '' v; do
  export "$k=$v"
done < <(python3 "$DIR/entorno.py" "$REPO" --exportar)
export AUTOPILOT_ENTORNO=1

# Nunca espera para siempre: COMMAND_TIMEOUT del autopilot.env (junto al repo o, en un workspace,
# en la carpeta padre); default 900 s. Al vencer se le pide terminar y, 30 s despues, se lo fuerza.
LIMITE="$(python3 -c '
import os, sys
sys.path.insert(0, sys.argv[2])
import entorno, workitems
repo = entorno.repo_principal(sys.argv[1])
for env in (os.path.join(repo, "autopilot.env"), os.path.join(os.path.dirname(repo), "autopilot.env")):
    if os.path.isfile(env):
        print(workitems.cargar_config(env)["vigia"]["timeout"])
        break
else:
    print(900)' "$REPO" "$DIR" 2>/dev/null)"
cd "$REPO" && exec timeout --kill-after=30 "${LIMITE:-900}" "$@"
