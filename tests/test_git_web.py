"""Pruebas del git de la app web: ver cambios, merge del humano, push y PR (GitHub y Azure DevOps).

Repos git reales con un remoto bare local; gh y curl se reemplazan por stubs en el PATH.
"""
import json
import os
import stat
import subprocess
import sys

import pytest

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
import remoto  # noqa: E402
import workitems as wi  # noqa: E402


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo)] + [str(x) for x in args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError("git %s fallo: %s" % (" ".join(str(x) for x in args), (r.stderr + r.stdout).strip()))
    return r


def sha(repo, ref):
    return git(repo, "rev-parse", ref).stdout.strip()


def commit(repo, archivo, texto, msg):
    (repo / archivo).write_text(texto)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def p(tmp_path, monkeypatch):
    """Repo con remoto bare (origin), base main publicada, rama task-uno con un commit; tarea en done."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", bare)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t.com")
    git(repo, "config", "user.name", "Test")
    commit(repo, "base.txt", "base\n", "base")
    git(repo, "remote", "add", "origin", bare)
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    git(repo, "switch", "-q", "-c", "task-uno")
    commit(repo, "tarea.txt", "nuevo\nlinea\n", "agrega tarea")
    git(repo, "switch", "-q", "main")
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % repo)
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "Pantalla", "d", "criterio")
    b.modificar("task-uno", "done", meta_set={"rama": "task-uno"})
    return {"b": b, "env": env, "repo": repo, "bare": bare, "tmp": tmp_path}


def stub(dirpath, nombre, codigo):
    dirpath.mkdir(exist_ok=True)
    f = dirpath / nombre
    f.write_text("#!/usr/bin/env python3\n" + codigo)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


# ----------------------------------------------------------------- ver cambios
def test_git_estado_y_diff(p):
    e = p["b"].git_estado("task-uno")
    r = e["repos"][0]
    assert r["existe_rama"] and not r["integrada"] and r["base"] == "main"
    assert [c["asunto"] for c in r["commits"]] == ["agrega tarea"]
    assert r["archivos"] == [{"ruta": "tarea.txt", "estado": "A", "binario": False, "mas": 2, "menos": 0}]
    assert r["base_vs_origin"] == {"adelante": 0, "atras": 0}
    d = p["b"].git_diff("task-uno", r["repo"], "tarea.txt")
    assert "+nuevo" in d["diff"] and not d["recortado"]
    assert p["b"].git_diff("task-uno", r["repo"], "tarea.txt", limite=10)["recortado"]
    with pytest.raises(wi.Error):
        p["b"].git_diff("task-uno", "otro-repo", "tarea.txt")


# ----------------------------------------------------------------- merge del humano
def test_merge_humano_sin_auto_merge(p):
    b = p["b"]
    with pytest.raises(wi.Error, match="AUTO_MERGE"):
        b.merge("task-uno")                       # el automatico sigue necesitando AUTO_MERGE
    res = b.merge("task-uno", humano=True)
    assert res["ok"] and res["estado"] == "reviewed"
    assert b.leer("task-uno")[0] == "reviewed"
    git(p["repo"], "merge-base", "--is-ancestor", "task-uno", "main")
    r = b.git_estado("task-uno")["repos"][0]
    assert r["integrada"] and r["base_vs_origin"]["adelante"] >= 1
    git(p["repo"], "rev-parse", "--verify", "task-uno")   # la rama no se borra


def test_merge_humano_con_conflicto_no_cambia_estado(p):
    commit(p["repo"], "tarea.txt", "otra cosa\n", "conflicto en main")
    antes = sha(p["repo"], "main")
    res = p["b"].merge("task-uno", humano=True)
    assert not res["ok"] and res["estado"] == "done"
    assert p["b"].leer("task-uno")[0] == "done"            # no pasa a stopped
    assert sha(p["repo"], "main") == antes
    assert not (p["repo"] / ".git" / "MERGE_HEAD").exists()


# ----------------------------------------------------------------- push
def test_push_base_y_al_dia(p):
    b = p["b"]
    b.merge("task-uno", humano=True)
    res = b.push("task-uno", "base")
    assert res["ok"] and res["repos"][0]["accion"] == "subida"
    assert git(p["bare"], "rev-parse", "main").stdout.strip() == sha(p["repo"], "main")
    git(p["repo"], "fetch", "-q", "origin")
    assert b.push("task-uno", "base")["repos"][0]["accion"] == "al-dia"


def test_push_rechazado_sin_force(p):
    otro = p["tmp"] / "otro"
    git(p["tmp"], "clone", "-q", p["bare"], otro)
    git(otro, "config", "user.email", "o@o.com")
    git(otro, "config", "user.name", "Otro")
    commit(otro, "remoto.txt", "x\n", "avanza el remoto")
    git(otro, "push", "-q", "origin", "main")
    remoto_antes = git(p["bare"], "rev-parse", "main").stdout.strip()
    p["b"].merge("task-uno", humano=True)
    res = p["b"].push("task-uno", "base")
    assert not res["ok"] and res["repos"][0]["accion"] == "rechazada"
    assert git(p["bare"], "rev-parse", "main").stdout.strip() == remoto_antes


def test_push_rama_solo_si_la_tarea_modifico_el_repo(p):
    b = p["b"]
    assert b.git_estado("task-uno")["repos"][0]["modificada"]
    res = b.push("task-uno", "rama")
    assert res["ok"] and res["repos"][0]["accion"] == "subida"
    assert git(p["bare"], "rev-parse", "task-uno").stdout.strip() == sha(p["repo"], "task-uno")
    assert git(p["bare"], "rev-parse", "main").stdout.strip() != sha(p["repo"], "task-uno")   # la base no se toca
    git(p["repo"], "fetch", "-q", "origin")
    assert b.push("task-uno", "rama")["repos"][0]["accion"] == "al-dia"


def test_push_rama_salta_repo_sin_cambios(p):
    git(p["repo"], "branch", "-f", "task-uno", "main")      # rama sin commits propios
    assert not p["b"].git_estado("task-uno")["repos"][0]["modificada"]
    res = p["b"].push("task-uno", "rama")
    assert res["repos"][0]["accion"] == "sin-cambios"
    assert git(p["bare"], "rev-parse", "--verify", "--quiet", "task-uno", check=False).returncode != 0


def test_rama_mergeada_sin_push_sigue_modificada(p):
    p["b"].merge("task-uno", humano=True)                  # base local la tiene, origin/main no
    r = p["b"].git_estado("task-uno")["repos"][0]
    assert r["integrada"] and r["modificada"]


@pytest.mark.parametrize("estado", ["qa", "validando", "e2e", "probando-e2e", "done", "reviewed"])
def test_push_rama_desde_que_el_coder_termina(p, estado):
    p["b"].modificar("task-uno", estado)
    res = p["b"].push("task-uno", "rama")
    assert res["ok"] and res["repos"][0]["accion"] == "subida"


@pytest.mark.parametrize("estado", ["new", "in-progress", "bug-fix", "stopped"])
def test_push_rama_no_antes_de_que_termine_el_coder(p, estado):
    p["b"].modificar("task-uno", estado)
    with pytest.raises(wi.Error, match="coder termino"):
        p["b"].push("task-uno", "rama")


@pytest.mark.parametrize("estado", ["qa", "validando", "e2e", "probando-e2e"])
def test_push_base_y_pr_solo_en_done_o_reviewed(p, estado):
    p["b"].modificar("task-uno", estado)
    with pytest.raises(wi.Error, match="done o reviewed"):
        p["b"].push("task-uno", "base")
    with pytest.raises(wi.Error, match="done o reviewed"):
        p["b"].crear_pr("task-uno")


# ----------------------------------------------------------------- remotos
@pytest.mark.parametrize("url,esperado", [
    ("https://user@dev.azure.com/codikasrl/Konectame%20App/_git/Repo_BE",
     {"tipo": "azure", "org": "codikasrl", "proyecto": "Konectame App", "repo": "Repo_BE"}),
    ("git@ssh.dev.azure.com:v3/org/proy/repo", {"tipo": "azure", "org": "org", "proyecto": "proy", "repo": "repo"}),
    ("https://org.visualstudio.com/proy/_git/repo.git", {"tipo": "azure", "org": "org", "proyecto": "proy", "repo": "repo"}),
    ("https://x:tok@github.com/Germoso/autopilot.git", {"tipo": "github", "slug": "Germoso/autopilot"}),
    ("git@github.com:Germoso/autopilot.git", {"tipo": "github", "slug": "Germoso/autopilot"}),
    ("/tmp/algo.git", {"tipo": "otro"}),
])
def test_analizar_remoto(url, esperado):
    info = remoto.analizar(url)
    assert {k: info.get(k) for k in esperado} == esperado
    assert "tok@" not in info["url"] and "user@" not in info["url"]


def test_pr_github_crea_y_reusa(p, monkeypatch):
    git(p["repo"], "remote", "set-url", "origin", "https://github.com/dueno/repo.git")
    git(p["repo"], "remote", "set-url", "--push", "origin", p["bare"])
    bin_ = p["tmp"] / "bin"
    llamadas = p["tmp"] / "gh.log"
    stub(bin_, "gh", """import json, os, sys
open(%r, "a").write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["pr", "list"]:
    print(open(%r).read() if os.path.exists(%r) else "[]")
elif sys.argv[1:3] == ["pr", "create"]:
    sys.stdin.read(); print("https://github.com/dueno/repo/pull/5")
""" % (str(llamadas), str(p["tmp"] / "existente.json"), str(p["tmp"] / "existente.json")))
    monkeypatch.setenv("PATH", "%s:%s" % (bin_, os.environ["PATH"]))
    res = p["b"].crear_pr("task-uno")
    assert res["ok"] and res["repos"][0]["accion"] == "creado"
    assert git(p["bare"], "rev-parse", "task-uno").stdout.strip() == sha(p["repo"], "task-uno")
    _, _, meta, _, secs = p["b"].leer("task-uno")
    assert json.loads(meta["prs"]) == {"repo": "https://github.com/dueno/repo/pull/5"}
    assert "pull/5" in secs["Pull requests"]
    crear = [json.loads(l) for l in open(llamadas) if '"create"' in l][0]
    assert crear[crear.index("--base") + 1] == "main" and crear[crear.index("--head") + 1] == "task-uno"
    (p["tmp"] / "existente.json").write_text('[{"url": "https://github.com/dueno/repo/pull/5"}]')
    assert p["b"].crear_pr("task-uno")["repos"][0]["accion"] == "existente"
    assert p["b"].leer("task-uno")[0] == "done"     # el PR no cambia el estado


def test_pr_azure_sin_pat_en_argv(p, monkeypatch):
    git(p["repo"], "remote", "set-url", "origin", "https://u@dev.azure.com/org/Mi%20Proy/_git/repo")
    git(p["repo"], "remote", "set-url", "--push", "origin", p["bare"])
    bin_ = p["tmp"] / "bin"
    log = p["tmp"] / "curl.log"
    stub(bin_, "curl", """import json, sys
stdin = sys.stdin.read()
open(%r, "a").write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\\n")
if "POST" in sys.argv:
    print(json.dumps({"pullRequestId": 7})); print("201", end="")
else:
    print(json.dumps({"value": []})); print("200", end="")
""" % str(log))
    monkeypatch.setenv("PATH", "%s:%s" % (bin_, os.environ["PATH"]))
    (p["tmp"] / "azure-sync.secrets.env").write_text("AZURE_DEVOPS_PAT=secreto123\n")
    res = p["b"].crear_pr("task-uno")
    assert res["ok"], res
    assert res["repos"][0]["detalle"] == "https://dev.azure.com/org/Mi%20Proy/_git/repo/pullrequest/7"
    llamadas = [json.loads(l) for l in open(log)]
    assert all("secreto123" not in " ".join(c["argv"]) for c in llamadas)
    assert all("secreto123" in c["stdin"] for c in llamadas)
    post = [c for c in llamadas if "POST" in c["argv"]][0]
    cuerpo = json.loads(post["argv"][post["argv"].index("--data-binary") + 1])
    assert cuerpo["sourceRefName"] == "refs/heads/task-uno" and cuerpo["targetRefName"] == "refs/heads/main"


def test_pr_azure_sin_pat_explica(p, monkeypatch):
    git(p["repo"], "remote", "set-url", "origin", "https://dev.azure.com/org/proy/_git/repo")
    git(p["repo"], "remote", "set-url", "--push", "origin", p["bare"])
    monkeypatch.setattr(remoto, "PAT_MCP", str(p["tmp"] / "no-existe.env"))
    res = p["b"].crear_pr("task-uno")
    assert not res["ok"] and "AZURE_DEVOPS_PAT" in res["repos"][0]["detalle"]


# ----------------------------------------------------------------- agentes
@pytest.mark.parametrize("cmd,bloquea", [
    ('$W "$E" push task-1 base', True),
    ('$W "$E" pr task-1', True),
    ('$W "$E" merge task-1 --humano', True),
    ('python3 ~/.local/share/autopilot-kit/workitems.py ./autopilot.env pr task-1', True),
    ('$W "$E" merge task-1', False),
    ('$W "$E" git-estado task-1', False),
])
def test_git_guard_bloquea_a_los_agentes(cmd, bloquea):
    r = subprocess.run(["bash", os.path.join(LIB, "git-guard.sh"), "coder"],
                       input=json.dumps({"tool_input": {"command": cmd}}), capture_output=True, text=True)
    assert (r.returncode == 2) == bloquea, r.stderr
