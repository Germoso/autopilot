#!/usr/bin/env python3
"""remoto.py — el remoto de un repo (GitHub o Azure DevOps) y sus Pull Requests.

Lo usa workitems.py para `wi.sh pr` (boton "Crear PR" de la app web). Solo lo dispara el humano.
- GitHub: con `gh` (usa la sesion de gh del usuario).
- Azure DevOps: API REST con el PAT de AZURE_DEVOPS_PAT (entorno, <proyecto>/azure-sync.secrets.env o
  ~/.config/autopilot-kit/ado-mcp.secrets.env, igual que azure-sync). El PAT va a curl por stdin (-K -),
  nunca en argv. Necesita permiso "Code (Read & Write)".
"""
import json
import os
import re
import subprocess
import urllib.parse

PAT_MCP = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                       "autopilot-kit", "ado-mcp.secrets.env")
API = "7.1"


class Error(Exception):
    pass


def sin_credenciales(url):
    """https://usuario:token@host/... -> https://host/..."""
    return re.sub(r"^(\w+://)[^@/]+@", r"\1", url or "")


def analizar(url):
    """Tipo de remoto y sus partes: {'tipo': github|azure|otro, 'url', ...}."""
    limpia = sin_credenciales(url).strip()
    m = re.match(r"^(?:https?://)(?:[^/]+\.)?dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/?#]+)", limpia) or \
        re.match(r"^(?:ssh://)?(?:[^@]+@)?ssh\.dev\.azure\.com:v3/([^/]+)/([^/]+)/([^/?#]+)", limpia)
    if m:
        org, proyecto, repo = (urllib.parse.unquote(x) for x in m.groups())
        return {"tipo": "azure", "url": limpia, "org": org, "proyecto": proyecto, "repo": re.sub(r"\.git$", "", repo)}
    m = re.match(r"^https?://([^.]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/?#]+)", limpia)
    if m:
        org, proyecto, repo = (urllib.parse.unquote(x) for x in m.groups())
        return {"tipo": "azure", "url": limpia, "org": org, "proyecto": proyecto, "repo": re.sub(r"\.git$", "", repo)}
    m = re.match(r"^(?:https?://github\.com/|(?:ssh://)?git@github\.com[:/])([^/]+)/([^/?#]+?)(?:\.git)?/?$", limpia)
    if m:
        return {"tipo": "github", "url": limpia, "slug": "%s/%s" % m.groups()}
    return {"tipo": "otro", "url": limpia}


def leer_env(path):
    vals = {}
    for linea in open(path, encoding="utf-8"):
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def pat_azure(raiz):
    archivos = [os.path.join(raiz, "azure-sync.secrets.env")] if raiz else []
    for vals in [os.environ] + [leer_env(f) for f in archivos + [PAT_MCP] if os.path.isfile(f)]:
        if vals.get("AZURE_DEVOPS_PAT"):
            return vals["AZURE_DEVOPS_PAT"]
    return ""


def _azure(info, pat, metodo, ruta, datos=None):
    url = "https://dev.azure.com/%s/%s/_apis/git/repositories/%s/%s" % (
        urllib.parse.quote(info["org"]), urllib.parse.quote(info["proyecto"]), urllib.parse.quote(info["repo"]), ruta)
    url += ("&" if "?" in url else "?") + "api-version=" + API
    conf = 'user = ":%s"\n' % pat.replace('"', '\\"')
    cmd = ["curl", "-sS", "-K", "-", "-X", metodo, "-w", "\n%{http_code}", url]
    if datos is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(datos)]
    r = subprocess.run(cmd, input=conf, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise Error("no se pudo contactar a Azure DevOps: %s" % r.stderr.strip()[:200])
    cuerpo, _, codigo = r.stdout.rpartition("\n")
    if codigo in ("401", "203"):
        raise Error("Azure DevOps rechazo el PAT (vencido o sin permiso 'Code: Read & Write')")
    try:
        j = json.loads(cuerpo) if cuerpo.strip() else {}
    except json.JSONDecodeError:
        raise Error("Azure DevOps respondio %s y algo que no es JSON: %s" % (codigo, cuerpo[:200]))
    if not codigo.startswith("2"):
        raise Error("Azure DevOps respondio %s: %s" % (codigo, j.get("message") or cuerpo[:200]))
    return j


def _url_pr_azure(info, pr_id):
    return "https://dev.azure.com/%s/%s/_git/%s/pullrequest/%s" % (
        urllib.parse.quote(info["org"]), urllib.parse.quote(info["proyecto"]), urllib.parse.quote(info["repo"]), pr_id)


def crear_pr(info, repo_path, base, rama, titulo, cuerpo, raiz=None):
    """Crea el PR rama -> base (o devuelve el que ya esta abierto). {'url', 'existente'}."""
    if info["tipo"] == "github":
        gh = lambda *a, **k: subprocess.run(["gh"] + list(a), cwd=repo_path, capture_output=True, text=True,
                                            timeout=90, **k)
        try:
            r = gh("pr", "list", "-R", info["slug"], "--head", rama, "--base", base, "--state", "open", "--json", "url")
        except FileNotFoundError:
            raise Error("no esta instalado gh (GitHub CLI)")
        if r.returncode == 0 and json.loads(r.stdout or "[]"):
            return {"url": json.loads(r.stdout)[0]["url"], "existente": True}
        r = gh("pr", "create", "-R", info["slug"], "--base", base, "--head", rama, "--title", titulo,
               "--body-file", "-", input=cuerpo)
        if r.returncode != 0:
            raise Error("gh pr create: %s" % (r.stderr or r.stdout).strip()[:300])
        return {"url": r.stdout.strip().splitlines()[-1], "existente": False}
    if info["tipo"] == "azure":
        pat = pat_azure(raiz)
        if not pat:
            raise Error("falta el PAT de Azure DevOps: define AZURE_DEVOPS_PAT en azure-sync.secrets.env del "
                        "proyecto o en ~/.config/autopilot-kit/ado-mcp.secrets.env (permiso Code: Read & Write)")
        abiertos = _azure(info, pat, "GET", "pullrequests?searchCriteria.status=active"
                          "&searchCriteria.sourceRefName=refs/heads/%s&searchCriteria.targetRefName=refs/heads/%s"
                          % (urllib.parse.quote(rama), urllib.parse.quote(base)))
        if abiertos.get("value"):
            return {"url": _url_pr_azure(info, abiertos["value"][0]["pullRequestId"]), "existente": True}
        pr = _azure(info, pat, "POST", "pullrequests", {
            "sourceRefName": "refs/heads/" + rama, "targetRefName": "refs/heads/" + base,
            "title": titulo[:400], "description": cuerpo[:3900]})
        return {"url": _url_pr_azure(info, pr["pullRequestId"]), "existente": False}
    raise Error("el remoto origin (%s) no es de GitHub ni de Azure DevOps: crea el PR a mano" % info["url"])
