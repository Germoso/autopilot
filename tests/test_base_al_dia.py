"""Antes de crear la rama de una tarea, el kit trae lo ultimo de origin/<base> (como un pull, sin merges)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
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


def clon(tmp_path, bare, nombre):
    c = tmp_path / nombre
    git(tmp_path, "clone", "-q", bare, c)
    git(c, "config", "user.email", "o@o.com")
    git(c, "config", "user.name", "Otro")
    return c


@pytest.fixture
def p(tmp_path, monkeypatch):
    """Repo del humano (en main) con origin bare; otro clon simula al equipo subiendo cambios."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", bare)
    semilla = tmp_path / "semilla"
    semilla.mkdir()
    git(semilla, "init", "-q", "-b", "main")
    git(semilla, "config", "user.email", "t@t.com")
    git(semilla, "config", "user.name", "T")
    commit(semilla, "base.txt", "base\n", "base")
    git(semilla, "remote", "add", "origin", bare)
    git(semilla, "push", "-q", "origin", "main")
    repo = clon(tmp_path, bare, "repo")
    equipo = clon(tmp_path, bare, "equipo")
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % repo)
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "T", "d", "c")
    b.modificar("task-uno", "in-progress")
    return {"b": b, "repo": repo, "equipo": equipo, "bare": bare, "tmp": tmp_path}


def test_la_rama_nace_de_lo_ultimo_de_origin(p):
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    info = p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "task-uno") == sha(p["equipo"], "main")          # tiene el cambio del equipo
    assert sha(p["repo"], "main") == sha(p["equipo"], "main")              # la base local se adelanto (copia limpia)
    assert "1 commit" in info["base_al_dia"][0]["detalle"] and not info["base_al_dia"][0]["aviso"]


def test_no_toca_la_copia_del_humano_con_cambios(p):
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    (p["repo"] / "base.txt").write_text("editando\n")                     # trabajo sin commitear del humano
    antes = sha(p["repo"], "main")
    info = p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "task-uno") == sha(p["equipo"], "main")          # igual nace de lo ultimo
    assert sha(p["repo"], "main") == antes                                 # su base no se movio
    assert (p["repo"] / "base.txt").read_text() == "editando\n"
    assert "cambios sin commitear" in info["base_al_dia"][0]["detalle"]


def test_base_no_abierta_se_adelanta_por_ref(p):
    git(p["repo"], "switch", "-q", "-c", "otra")                           # el humano esta en otra rama
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "main") == sha(p["equipo"], "main")
    assert git(p["repo"], "branch", "--show-current").stdout.strip() == "otra"


def test_base_local_adelante_se_usa_la_local(p):
    commit(p["repo"], "merge.txt", "dep\n", "merge local de una dependencia sin push")
    info = p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "task-uno") == sha(p["repo"], "main")
    assert "sin subir" in info["base_al_dia"][0]["detalle"] and not info["base_al_dia"][0]["aviso"]


def test_divergidas_avisa_y_usa_la_local(p):
    commit(p["repo"], "local.txt", "l\n", "local")
    commit(p["equipo"], "remoto.txt", "r\n", "remoto")
    git(p["equipo"], "push", "-q", "origin", "main")
    info = p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "task-uno") == sha(p["repo"], "main")
    assert "divergieron" in info["base_al_dia"][0]["aviso"]
    assert any("divergieron" in (l.get("detalle") or "") for l in p["b"].db.log_listar("task-uno", 20))


def test_sin_red_sigue_con_la_base_local(p):
    git(p["repo"], "remote", "set-url", "origin", p["tmp"] / "no-existe.git")
    info = p["b"].preparar_rama("task-uno", "nueva")
    assert sha(p["repo"], "task-uno") == sha(p["repo"], "main")
    assert "no se pudo traer" in info["base_al_dia"][0]["aviso"]
    assert p["b"].leer("task-uno")[0] == "in-progress"                     # no se detiene la tarea


def test_bugfix_no_vuelve_a_traer(p):
    p["b"].preparar_rama("task-uno", "nueva")
    p["b"].coder_worktree_borrar("task-uno")
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    antes = sha(p["repo"], "task-uno")
    info = p["b"].preparar_rama("task-uno", "existente")
    assert "base_al_dia" not in info and sha(p["repo"], "task-uno") == antes


# ----------------------------------------------------------------- boton "Pull de las bases" (app web)
def test_pull_bases_adelanta_la_base(p):
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    res = p["b"].pull_bases("task-uno")
    assert res["ok"] and res["repos"][0]["accion"] == "actualizada"
    assert sha(p["repo"], "main") == sha(p["equipo"], "main")
    assert (p["repo"] / "nuevo.txt").exists()                               # la copia del humano se actualizo
    assert p["b"].pull_bases("task-uno")["repos"][0]["accion"] == "al-dia"
    assert p["b"].leer("task-uno")[0] == "in-progress"                     # no toca el estado de la tarea


def test_pull_bases_respeta_cambios_sin_commitear(p):
    commit(p["equipo"], "nuevo.txt", "x\n", "cambio del equipo")
    git(p["equipo"], "push", "-q", "origin", "main")
    (p["repo"] / "base.txt").write_text("editando\n")
    antes = sha(p["repo"], "main")
    res = p["b"].pull_bases("task-uno")
    assert not res["ok"] and res["repos"][0]["accion"] == "no-adelantada"
    assert "cambios sin commitear" in res["repos"][0]["detalle"]
    assert sha(p["repo"], "main") == antes and (p["repo"] / "base.txt").read_text() == "editando\n"


def test_pull_bases_divergida_no_mergea(p):
    commit(p["repo"], "local.txt", "l\n", "local")
    commit(p["equipo"], "remoto.txt", "r\n", "remoto")
    git(p["equipo"], "push", "-q", "origin", "main")
    antes = sha(p["repo"], "main")
    res = p["b"].pull_bases("task-uno")
    assert not res["ok"] and res["repos"][0]["accion"] == "divergida"
    assert sha(p["repo"], "main") == antes


def test_git_guard_bloquea_pull_bases_a_los_agentes():
    import json
    guard = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "git-guard.sh")
    r = subprocess.run(["bash", guard, "coder"], input=json.dumps({"tool_input": {"command": '$W "$E" pull-bases task-1'}}),
                       capture_output=True, text=True)
    assert r.returncode == 2
