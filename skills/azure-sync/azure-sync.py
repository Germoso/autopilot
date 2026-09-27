#!/usr/bin/env python3
"""
azure-sync.py — Importador ADITIVO de Azure DevOps al tablero de Notion.

COPIA aditiva de /home/user/sync_workitems.py, adaptada para alimentar
el tablero nativo de Notion en vez de editar Kanban.md de Obsidian.

GARANTIAS (identicas a las del original):
  - Solo AGREGA tareas nuevas. Nunca mueve, borra ni sobrescribe.
  - Dedup por idempotency: busca 'azure-<id>' en el titulo de cada tarea
    del tablero. Si ya existe, la salta.
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

API = "https://api.notion.com/v1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Prioridad de Azure (1=alta) -> Notion
PRIO_MAP = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
PRIO_DEFAULT = "Medium"

CFG = {
    "org": "",
    "project": "",
    "iteration": "",
    "user": "",
    "pat": "",
    "notion_token": "",
    "notion_database_id": "",
    "notion_log_db_id": "",
    "workitem_dir": "",
}


# ----------------------------------------------------------------- config
def load_config(path):
    """Carga el .env del proyecto y, encima, el archivo de secretos."""
    if not os.path.exists(path):
        die("No existe el archivo de config: %s" % path,
            "Copiá la plantilla desde ~/.config/opencode/skills/azure-sync/plantilla.env")
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
            elif k == "NOTION_TOKEN":
                CFG["notion_token"] = v
            elif k == "NOTION_DATABASE_ID":
                CFG["notion_database_id"] = v
            elif k == "NOTION_LOG_DB_ID":
                CFG["notion_log_db_id"] = v
            elif k == "WORKITEM_DIR":
                CFG["workitem_dir"] = v

    # El entorno tiene prioridad sobre el archivo (pat tipico)
    for k in ("AZURE_DEVOPS_PAT", "NOTION_TOKEN"):
        if os.environ.get(k):
            CFG["pat" if k == "AZURE_DEVOPS_PAT" else "notion_token"] = os.environ[k]

    CFG.setdefault("workitem_dir", os.path.join(SCRIPT_DIR, "workitems"))


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


# ----------------------------------------------------------------- notion
def n_post(path, data):
    r = subprocess.run(
        ["curl", "-sS", "-X", "POST", API + path,
         "-H", "Authorization: Bearer %s" % CFG["notion_token"],
         "-H", "Notion-Version: 2022-06-28",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(data, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Notion devolvio algo que no es JSON: %s" % r.stdout[:200])


def n_query_titles():
    """Devuelve el set de azure-<id> ya presentes en el titulo de cualquier tarea."""
    r = subprocess.run(
        ["curl", "-sS", "-X", "POST", API + "/databases/%s/query" % CFG["notion_database_id"],
         "-H", "Authorization: Bearer %s" % CFG["notion_token"],
         "-H", "Notion-Version: 2022-06-28",
         "-H", "Content-Type: application/json",
         "-d", '{"page_size":100}'],
        capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        die("Notion devolvio algo que no es JSON: %s" % r.stdout[:200])
    if d.get("object") == "error":
        die("Notion erro: %s" % d.get("message", "?"))
    seen = set()
    for pg in d.get("results", []):
        for t in pg.get("properties", {}).get("Name", {}).get("title", []):
            txt = t.get("plain_text", "")
            m = re.search(r"azure-(\d+)", txt, re.IGNORECASE)
            if m:
                seen.add(m.group(1))
    return seen


def n_create_task(wid, title, desc, criterio, prioridad):
    props = {
        "Name": {"title": [{"type": "text", "text": {"content": title[:1900]}}]},
        "Estado": {"select": {"name": "New"}},
        "Prioridad": {"select": {"name": prioridad}},
        "Descripción": {"rich_text": [{"type": "text", "text": {"content": (desc or "-")[:1900]}}]},
        "Criterio de aceptación": {"rich_text": [{"type": "text", "text": {"content": (criterio or "-")[:1900]}}]},
        "Repo": {"rich_text": [{"type": "text", "text": {"content": "_azure:_"}}]},
        "Resultado": {"rich_text": [{"type": "text", "text": {
            "content": "_Sincronizado desde Azure DevOps. Project: %s. WI: %d._" % (CFG["project"], wid)}}]},
    }
    return n_post("/pages", {"parent": {"database_id": CFG["notion_database_id"]}, "properties": props})


def n_log(evento, tipo, tarea, detalle):
    if not CFG["notion_log_db_id"]:
        return
    from datetime import datetime, timezone
    c = lambda v: {"rich_text": [{"type": "text", "text": {"content": (v or "-")[:1900]}}]}
    body = {
        "parent": {"database_id": CFG["notion_log_db_id"]},
        "properties": {
            "Evento": {"title": [{"type": "text", "text": {"content": evento}}]},
            "Origen": {"select": {"name": "sistema"}},
            "Tipo": {"select": {"name": tipo}},
            "Tarea": c(tarea),
            "Rama": c("-"),
            "Commit": c("-"),
            "Detalle": c(detalle),
            "Hora": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        },
    }
    n_post("/pages", body)


# ----------------------------------------------------------------- sync
def one_pass(dry_run=False):
    ids = fetch_new_workitems()
    if not ids:
        return {"action": "no-op", "added": [], "skipped": [],
                "message": "Azure sin tareas New en el sprint"}

    already = n_query_titles()
    added, skipped, errors = [], [], []

    for wid in ids:
        key = str(wid)
        if key in already:
            skipped.append({"id": wid, "reason": "ya en el tablero (azure-%s)" % key})
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
        criterio = strip_html(f.get("Microsoft.VSTS.TCM.ReproSteps")) or "_Sin criterio en Azure._"
        prio = PRIO_MAP.get(f.get("Microsoft.VSTS.Common.Priority"), PRIO_DEFAULT)
        task_title = "[azure-%d] %s" % (wid, title)

        if dry_run:
            added.append({"id": wid, "title": task_title, "prioridad": prio})
            already.add(key)  # evita duplicados en la misma pasada
            continue

        resp = n_create_task(wid, task_title, desc, criterio, prio)
        if resp.get("object") == "error":
            errors.append({"id": wid, "error": resp.get("message", "?")[:200]})
        else:
            added.append({"id": wid, "title": task_title})
            already.add(key)

    action = "dry-run" if dry_run else ("added" if added else ("partial" if errors else "no-op"))
    result = {"action": action, "added": added, "skipped": skipped, "errors": errors}

    if added and not dry_run:
        n_log("azure-sync importo tareas", "deteccion",
              ", ".join("azure-%d" % a["id"] for a in added[:5]),
              "Importadas %d tarea(s) de Azure DevOps: %s" % (len(added), ", ".join(str(a["id"]) for a in added)))
    return result


def do_status():
    ids = fetch_new_workitems()
    already = n_query_titles()
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
    if not CFG["notion_token"]:
        die("Falta NOTION_TOKEN en %s" % args.config)
    if not CFG["notion_database_id"]:
        die("Falta NOTION_DATABASE_ID en %s" % args.config)

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
