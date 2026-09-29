#!/usr/bin/env python3
"""
azure-sync.py — Importador ADITIVO de Azure DevOps al board de workitems.

COPIA aditiva de /home/user/sync_workitems.py, adaptada para alimentar
el board de carpetas + Markdown del autopilot (workitems.py, misma carpeta).

Cada Work Item se escribe como new/<tipo>-<numero>-<slug>.md, donde tipo es
task o bug segun System.WorkItemType. <tipo>-<numero> es tambien el nombre de
la rama que el autopilot crea desde la rama base del repo.

FUENTES (azure-sync.env):
  Un repo:    AZURE_PROJECT=<proyecto>  AZURE_ITERATION=<sprint>
  Workspace:  SYNC.<carpeta del repo>=<proyecto>|<sprint>   (una linea por repo)
              La tarea se crea con repo: <carpeta>, asi el autopilot sabe en que
              repo crear la rama.
  <sprint> es la ruta de la iteracion (Proyecto\\Sprint X) o @current, que usa el
  sprint actual del equipo por defecto (<Proyecto> Team); @current:<Equipo> para otro.

GARANTIAS (identicas a las del original):
  - Solo AGREGA tareas nuevas. Nunca mueve, borra ni sobrescribe.
  - Dedup por numero: si ya hay un archivo *-<numero>-*.md en CUALQUIER
    estado del board, lo salta. (Los IDs son unicos en toda la organizacion.)
  - Es idempotente: correrlo N veces crea la tarea una sola vez.
  - Si Azure falla en CUALQUIER fuente, sale con codigo != 0 y NO toca el board.
  - El PAT se lee del entorno, de azure-sync.secrets.env o del de ado-mcp.
    NO se hardcodea y no se pasa por linea de comandos (no aparece en `ps`).

El script ORIGINAL (/home/user/sync_workitems.py) NO se modifica.

Uso:
  python3 azure-sync.py --config <proyecto>/azure-sync.env
  python3 azure-sync.py --config <...> --watch 60
  python3 azure-sync.py --config <...> --dry-run
  python3 azure-sync.py --config <...> --status
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# El formato del board vive en un solo lugar: workitems.py, en esta misma carpeta.
sys.path.insert(0, SCRIPT_DIR)
try:
    import workitems as wi
except ImportError:
    print(json.dumps({"action": "error",
                      "message": "no encuentro workitems.py junto a azure-sync.py",
                      "hint": "reinstala el kit con install.sh"}, ensure_ascii=False, indent=2))
    sys.exit(2)

# Prioridad de Azure (1=alta) -> board
PRIO_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
PRIO_DEFAULT = "Medium"
PAT_MCP = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                       "autopilot-kit", "ado-mcp.secrets.env")

CFG = {"org": "", "user": "", "pat": "", "fuentes": []}
BOARD = None  # wi.Board, se arma en main()


# ----------------------------------------------------------------- config
def leer_env(path):
    vals = {}
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip("'\"")
    return vals


def load_config(path):
    """Carga azure-sync.env, las fuentes y el PAT (entorno > secrets.env > PAT del MCP)."""
    if not os.path.exists(path):
        die("No existe el archivo de config: %s" % path, "Crealo con /autopilot-init o install.sh --init")
    vals = leer_env(path)
    CFG["org"] = vals.get("AZURE_ORG", "")
    CFG["user"] = vals.get("AZURE_USER", "") or "pat"

    fuentes = []
    for k, v in sorted(vals.items()):
        if k.startswith("SYNC.") and k[5:]:
            proyecto, _, iteracion = v.partition("|")
            fuentes.append({"repo": k[5:], "project": proyecto.strip(), "iteration": iteracion.strip()})
    if not fuentes and vals.get("AZURE_PROJECT"):
        fuentes.append({"repo": "", "project": vals["AZURE_PROJECT"], "iteration": vals.get("AZURE_ITERATION", "")})
    CFG["fuentes"] = fuentes

    secrets = path[:-4] + ".secrets.env" if path.endswith(".env") else path + ".secrets"
    for origen in (os.environ, leer_env(secrets) if os.path.exists(secrets) else {},
                   leer_env(PAT_MCP) if os.path.exists(PAT_MCP) else {}):
        if origen.get("AZURE_DEVOPS_PAT"):
            CFG["pat"] = origen["AZURE_DEVOPS_PAT"]
            break


def die(msg, hint=None, code=2):
    out = {"action": "error", "message": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(code)


# ----------------------------------------------------------------- azure
def curl(url, data=None):
    """curl con las credenciales por stdin (-K -): el PAT nunca va en argv."""
    conf = 'user = "%s:%s"\n' % (CFG["user"], CFG["pat"].replace('"', '\\"'))
    cmd = ["curl", "-sS", "-K", "-", url]
    if data is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(data)]
    r = subprocess.run(cmd, input=conf, capture_output=True, text=True)
    if r.returncode != 0:
        die("curl fallo contactando Azure: %s" % r.stderr.strip()[:200])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Azure devolvio algo que no es JSON (PAT invalido o sin permisos?): %s" % r.stdout[:200])


def base_url(project, team=None):
    parts = [CFG["org"], urllib.parse.quote(project)] + ([urllib.parse.quote(team)] if team else [])
    return "https://dev.azure.com/" + "/".join(parts)


def strip_html(t):
    if not t:
        return ""
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return re.sub(r"^ℹ️\s*Descripción\s*", "", t)


def fetch_new_workitems(fuente):
    """WIQL: Task/Bug del sprint de la fuente, en estado New."""
    it, team = fuente["iteration"], None
    if it.startswith("@current"):
        team = it.partition(":")[2].strip() or "%s Team" % fuente["project"]
        filtro = "[System.IterationPath] = @CurrentIteration"
    else:
        filtro = "[System.IterationPath] UNDER '%s'" % it.replace("'", "''")
    query = ("SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND %s AND "
             "[System.WorkItemType] IN ('Task','Bug') AND [System.State] CONTAINS 'New' "
             "ORDER BY [System.Id]" % filtro)
    d = curl(base_url(fuente["project"], team) + "/_apis/wit/wiql?api-version=7.1", {"query": query})
    if "workItems" not in d:
        die("Azure no devolvio workItems para %s: %s" % (fuente["project"], json.dumps(d)[:200]))
    return [w["id"] for w in d["workItems"]]


def fetch_detail(project, wid):
    return curl(base_url(project) + "/_apis/wit/workitems/%d?api-version=7.1&$expand=all" % wid)["fields"]


# ----------------------------------------------------------------- board
def tipo_de(f):
    """Bug -> bug; todo lo demas (Task) -> task."""
    return "bug" if (f.get("System.WorkItemType") or "").lower() == "bug" else "task"


def criterio_de(f):
    return (strip_html(f.get("Microsoft.VSTS.Common.AcceptanceCriteria"))
            or strip_html(f.get("Microsoft.VSTS.TCM.ReproSteps"))
            or "_Sin criterio en Azure._")


# ----------------------------------------------------------------- sync
def recolectar():
    """[(fuente, id)] de todas las fuentes. Si una falla, die() antes de tocar el board."""
    return [(f, wid) for f in CFG["fuentes"] for wid in fetch_new_workitems(f)]


def one_pass(dry_run=False):
    pendientes = recolectar()
    if not pendientes:
        return {"action": "no-op", "added": [], "skipped": [],
                "message": "Azure sin tareas New en los sprints configurados"}

    already = BOARD.numeros()
    added, skipped, errors = [], [], []

    for fuente, wid in pendientes:
        key = str(wid)
        donde = fuente["repo"] or fuente["project"]
        if key in already:
            skipped.append({"id": wid, "repo": donde, "reason": "ya en el board (numero %s)" % key})
            continue
        try:
            f = fetch_detail(fuente["project"], wid)
        except SystemExit:
            raise
        except Exception as e:
            errors.append({"id": wid, "error": str(e)[:200]})
            continue

        title = f.get("System.Title") or "Work Item #%d" % wid
        prio = PRIO_MAP.get(f.get("Microsoft.VSTS.Common.Priority"), PRIO_DEFAULT)
        tipo = tipo_de(f)
        clave = "%s-%d" % (tipo, wid)

        if dry_run:
            added.append({"id": wid, "clave": clave, "repo": donde, "title": title, "prioridad": prio})
            already.add(key)  # evita duplicados en la misma pasada
            continue

        try:
            path = BOARD.crear(tipo, wid, prio, title, strip_html(f.get("System.Description")),
                               criterio_de(f), repo=fuente["repo"], origen="azure:%s" % fuente["project"])
        except wi.Error as e:
            errors.append({"id": wid, "error": str(e)[:200]})
        else:
            added.append({"id": wid, "clave": clave, "repo": donde, "title": title, "archivo": path})
            already.add(key)

    action = "dry-run" if dry_run else ("added" if added else ("partial" if errors else "no-op"))
    result = {"action": action, "added": added, "skipped": skipped, "errors": errors}

    if added and not dry_run:
        BOARD.log("azure-sync importo tareas", "sistema", "deteccion",
                  ", ".join(a["clave"] for a in added[:5]), "-", "-",
                  "Importadas %d tarea(s) de Azure DevOps: %s" % (
                      len(added), ", ".join("%s (%s)" % (a["id"], a["repo"]) for a in added)))
    return result


def do_status():
    already = BOARD.numeros()
    fuentes = []
    for f in CFG["fuentes"]:
        ids = fetch_new_workitems(f)
        nuevos = [i for i in ids if str(i) not in already]
        fuentes.append({"repo": f["repo"] or "-", "project": f["project"], "iteration": f["iteration"],
                        "azure_new_count": len(ids), "already_in_board": len(ids) - len(nuevos),
                        "pending_import": len(nuevos), "pending_ids": nuevos[:20]})
    print(json.dumps({"action": "status", "fuentes": fuentes}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ruta a azure-sync.env")
    ap.add_argument("--watch", type=int, metavar="SEG", help="bucle cada N segundos")
    ap.add_argument("--dry-run", action="store_true", help="muestra que haria sin escribir")
    ap.add_argument("--status", action="store_true", help="solo diagnostico")
    args = ap.parse_args()

    load_config(args.config)

    if not CFG["org"]:
        die("Falta AZURE_ORG en %s" % args.config)
    if not CFG["fuentes"]:
        die("No hay fuentes en %s" % args.config,
            "Un repo: AZURE_PROJECT + AZURE_ITERATION. Workspace: SYNC.<repo>=<proyecto>|<sprint o @current>")
    for f in CFG["fuentes"]:
        if not f["project"] or not f["iteration"]:
            die("Fuente incompleta para %s: falta proyecto o sprint" % (f["repo"] or "AZURE_PROJECT"),
                "Formato: SYNC.<repo>=<proyecto>|<Proyecto\\Sprint X o @current>")
    if not CFG["pat"]:
        die("Falta AZURE_DEVOPS_PAT", "Ponelo en el entorno, en azure-sync.secrets.env o en %s" % PAT_MCP)

    global BOARD
    try:
        # El board lo define autopilot.env (misma carpeta): de ahi salen tambien los repos.
        env_ap = os.path.join(os.path.dirname(os.path.abspath(args.config)), "autopilot.env")
        BOARD = wi.Board(wi.cargar_config(env_ap if os.path.exists(env_ap) else args.config))
    except wi.Error as e:
        die(str(e))
    if not args.dry_run and not args.status and not os.path.isdir(BOARD.dir):
        die("No existe el board %s" % BOARD.dir, "Crealo con /autopilot-init")
    if BOARD.cfg["workspace"]:
        faltan = [f["repo"] for f in CFG["fuentes"] if f["repo"] not in BOARD.cfg["repos"]]
        if faltan:
            die("SYNC.%s no tiene su REPO.%s en autopilot.env" % (faltan[0], faltan[0]),
                "Cada repo de azure-sync.env debe estar declarado en autopilot.env")

    if args.status:
        return do_status()

    if args.watch:
        print("azure-sync en modo watch cada %ds. Ctrl+C para salir." % args.watch, flush=True)
        while True:
            try:
                r = one_pass()
                if r.get("added") or r.get("errors"):
                    print(json.dumps(r, ensure_ascii=False), flush=True)
            except SystemExit:
                raise
            except Exception as e:
                print(json.dumps({"action": "error", "message": str(e)[:300]}), flush=True)
            time.sleep(args.watch)

    r = one_pass(dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if not r.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
