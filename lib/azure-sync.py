#!/usr/bin/env python3
"""
azure-sync.py — Importador ADITIVO de Azure DevOps al board de workitems.

COPIA aditiva de /home/user/sync_workitems.py, adaptada para alimentar
el board de carpetas + Markdown del autopilot (workitems.py, misma carpeta).

Cada Work Item se escribe como new/<tipo>-<numero>-<slug>.md, donde tipo es
task o bug segun System.WorkItemType. <tipo>-<numero> es tambien el nombre de
la rama que el autopilot crea desde BASE_BRANCH.

GARANTIAS (identicas a las del original):
  - Solo AGREGA tareas nuevas. Nunca mueve, borra ni sobrescribe.
  - Dedup por numero: si ya hay un archivo *-<numero>-*.md en CUALQUIER
    estado del board, lo salta.
  - Es idempotente: correrlo N veces crea la tarea una sola vez.
  - Si Azure falla, sale con codigo != 0 y NO toca el tablero.
  - El PAT se lee del entorno o de azure-sync.secrets.env. NO se hardcodea.

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

CFG = {
    "org": "",
    "project": "",
    "iteration": "",
    "user": "",
    "pat": "",
}
BOARD = None  # wi.Board, se arma en main()


# ----------------------------------------------------------------- config
def load_config(path):
    """Carga el .env del proyecto y, encima, el archivo de secretos."""
    if not os.path.exists(path):
        die("No existe el archivo de config: %s" % path,
            "Crealo con: install.sh --init <proyecto>")
    secrets = path.replace(".env", ".secrets.env")
    for f in ([path, secrets] if os.path.exists(secrets) else [path]):
        for raw in open(f, encoding="utf-8"):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip().upper(), v.strip().strip("'\"")
            if k == "AZURE_DEVOPS_PAT":
                CFG["pat"] = v
            elif k == "AZURE_ORG":
                CFG["org"] = v
            elif k == "AZURE_PROJECT":
                CFG["project"] = v
            elif k == "AZURE_ITERATION":
                CFG["iteration"] = v
            elif k == "AZURE_USER":
                CFG["user"] = v

    # El entorno tiene prioridad sobre el archivo (pat tipico)
    if os.environ.get("AZURE_DEVOPS_PAT"):
        CFG["pat"] = os.environ["AZURE_DEVOPS_PAT"]


def die(msg, hint=None, code=2):
    out = {"action": "error", "message": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(code)


def azure_base():
    return "https://dev.azure.com/%s/%s" % (CFG["org"], urllib.parse.quote(CFG["project"]))


# ----------------------------------------------------------------- azure
def azure_post(url, data):
    r = subprocess.run(
        ["curl", "-sS", "-u", "%s:%s" % (CFG["user"], CFG["pat"]),
         "-H", "Content-Type: application/json", "-d", json.dumps(data), "-X", "POST", url],
        capture_output=True, text=True)
    if r.returncode != 0:
        die("curl fallo contacting Azure: %s" % r.stderr.strip()[:200])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Azure devolvio algo que no es JSON (PAT invalido?): %s" % r.stdout[:200])


def azure_get(url):
    r = subprocess.run(
        ["curl", "-sS", "-u", "%s:%s" % (CFG["user"], CFG["pat"]), url],
        capture_output=True, text=True)
    if r.returncode != 0:
        die("curl fallo contacting Azure: %s" % r.stderr.strip()[:200])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Azure devolvio algo que no es JSON: %s" % r.stdout[:200])


def strip_html(t):
    if not t:
        return ""
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return re.sub(r"^ℹ️\s*Descripción\s*", "", t)


def fetch_new_workitems():
    """WIQL: Task/Bug del sprint en estado New."""
    esc = CFG["iteration"].replace("'", "''")
    query = (
        "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND "
        "[System.IterationPath] UNDER '%s' AND "
        "[System.WorkItemType] IN ('Task','Bug') AND "
        "[System.State] CONTAINS 'New' "
        "ORDER BY [System.Id]" % esc
    )
    d = azure_post(azure_base() + "/_apis/wit/wiql?api-version=7.1", {"query": query})
    if "workItems" not in d:
        die("Azure no devolvio workItems: %s" % json.dumps(d)[:200])
    return [w["id"] for w in d["workItems"]]


def fetch_detail(wid):
    return azure_get(azure_base() + "/_apis/wit/workitems/%d?api-version=7.1&$expand=all" % wid)["fields"]


# ----------------------------------------------------------------- board
def tipo_de(f):
    """Bug -> bug; todo lo demas (Task) -> task."""
    return "bug" if (f.get("System.WorkItemType") or "").lower() == "bug" else "task"


def criterio_de(f):
    return (strip_html(f.get("Microsoft.VSTS.Common.AcceptanceCriteria"))
            or strip_html(f.get("Microsoft.VSTS.TCM.ReproSteps"))
            or "_Sin criterio en Azure._")


# ----------------------------------------------------------------- sync
def one_pass(dry_run=False):
    ids = fetch_new_workitems()
    if not ids:
        return {"action": "no-op", "added": [], "skipped": [],
                "message": "Azure sin tareas New en el sprint"}

    already = BOARD.numeros()
    added, skipped, errors = [], [], []

    for wid in ids:
        key = str(wid)
        if key in already:
            skipped.append({"id": wid, "reason": "ya en el board (numero %s)" % key})
            continue
        try:
            f = fetch_detail(wid)
        except SystemExit:
            raise
        except Exception as e:
            errors.append({"id": wid, "error": str(e)[:200]})
            continue

        title = f.get("System.Title") or "Work Item #%d" % wid
        desc = strip_html(f.get("System.Description"))
        criterio = criterio_de(f)
        prio = PRIO_MAP.get(f.get("Microsoft.VSTS.Common.Priority"), PRIO_DEFAULT)
        tipo = tipo_de(f)
        clave = "%s-%d" % (tipo, wid)

        if dry_run:
            added.append({"id": wid, "clave": clave, "title": title, "prioridad": prio})
            already.add(key)  # evita duplicados en la misma pasada
            continue

        try:
            path = BOARD.crear(tipo, wid, prio, title, desc, criterio,
                               origen="azure:%s" % CFG["project"])
        except wi.Error as e:
            errors.append({"id": wid, "error": str(e)[:200]})
        else:
            added.append({"id": wid, "clave": clave, "title": title, "archivo": path})
            already.add(key)

    action = "dry-run" if dry_run else ("added" if added else ("partial" if errors else "no-op"))
    result = {"action": action, "added": added, "skipped": skipped, "errors": errors}

    if added and not dry_run:
        BOARD.log("azure-sync importo tareas", "sistema", "deteccion",
              ", ".join(a["clave"] for a in added[:5]), "-", "-",
              "Importadas %d tarea(s) de Azure DevOps: %s" % (len(added), ", ".join(str(a["id"]) for a in added)))
    return result


def do_status():
    ids = fetch_new_workitems()
    already = BOARD.numeros()
    nuevos = [i for i in ids if str(i) not in already]
    print(json.dumps({
        "action": "status",
        "azure_new_count": len(ids),
        "already_in_board": len(ids) - len(nuevos),
        "pending_import": len(nuevos),
        "pending_ids": nuevos[:20],
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="ruta a azure-sync.env")
    ap.add_argument("--watch", type=int, metavar="SEG", help="bucle cada N segundos")
    ap.add_argument("--dry-run", action="store_true", help="muestra que haria sin escribir")
    ap.add_argument("--status", action="store_true", help="solo diagnostico")
    args = ap.parse_args()

    load_config(args.config)

    for k, label in [("org", "AZURE_ORG"), ("project", "AZURE_PROJECT"),
                     ("iteration", "AZURE_ITERATION"), ("user", "AZURE_USER")]:
        if not CFG[k]:
            die("Falta %s en %s" % (label, args.config))
    if not CFG["pat"]:
        die("Falta AZURE_DEVOPS_PAT. Ponelo en el entorno o en azure-sync.secrets.env",
            "echo 'AZURE_DEVOPS_PAT=xxx' >> %s" % args.config.replace(".env", ".secrets.env"))

    global BOARD
    try:
        BOARD = wi.Board(wi.cargar_config(args.config))
    except wi.Error as e:
        die(str(e))
    if not args.dry_run and not args.status and not os.path.isdir(BOARD.dir):
        die("No existe el board %s" % BOARD.dir,
            "Crealo con: %s %s init" % (os.path.join(SCRIPT_DIR, "wi.sh"), args.config))

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
