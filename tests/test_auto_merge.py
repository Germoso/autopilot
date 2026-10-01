"""Pruebas de AUTO_MERGE: integración automática de la rama de la tarea en la base.

Solo con AUTO_MERGE=true el kit mergea; nunca hace push ni borra ramas; un conflicto
deja la base intacta y la tarea stopped (avisada).
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import workitems as wi  # noqa: E402

WI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "workitems.py")


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo)] + [str(x) for x in args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError("git %s fallo: %s" % (" ".join(str(x) for x in args), (r.stderr + r.stdout).strip()))
    return r


def sha(repo, ref):
    return git(repo, "rev-parse", ref).stdout.strip()


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Repo git real con rama base main y una rama task-uno; board temporal con la tarea done."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t.com")
    git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "branch", "-M", "main")
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % repo)
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "T", "d", "c")
    git(repo, "switch", "-q", "-c", "task-uno")
    (repo / "tarea.txt").write_text("nuevo\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "tarea")
    git(repo, "switch", "-q", "main")
    b.modificar("task-uno", "done")
    p = {"b": b, "env": env, "repo": repo, "tmp": tmp_path}
    return p


def activar(p):
    """Enciende AUTO_MERGE en el env y devuelve un Board con la config fresca."""
    p["env"].write_text(p["env"].read_text() + "AUTO_MERGE=true\n")
    p["b"] = wi.Board(wi.cargar_config(str(p["env"])))
    return p["b"]


# ----------------------------------------------------------------- config
def test_config_auto_merge(tmp_path):
    e = tmp_path / "a.env"
    e.write_text("WORKITEMS_DIR=board\n")
    assert wi.cargar_config(str(e))["auto_merge"] is False
    e.write_text("WORKITEMS_DIR=board\nAUTO_MERGE=true\n")
    assert wi.cargar_config(str(e))["auto_merge"] is True
    e.write_text("WORKITEMS_DIR=board\nAUTO_MERGE=si\n")
    cfg = wi.cargar_config(str(e))
    assert cfg["auto_merge"] is False and cfg["auto_merge_invalido"] == "si"
    assert any("AUTO_MERGE" in a for a in wi.Board(cfg).avisos())


def test_merge_solo_con_flag_activado(proyecto):
    with pytest.raises(wi.Error, match="AUTO_MERGE"):
        proyecto["b"].merge("task-uno")
    assert proyecto["b"].buscar("task-uno")[0] == "done"   # nada cambio


# ----------------------------------------------------------------- merge
def test_merge_fast_forward_deja_reviewed(proyecto):
    b = activar(proyecto)
    rama = sha(proyecto["repo"], "task-uno")
    r = b.merge("task-uno")
    assert r["ok"] is True and r["estado"] == "reviewed"
    assert sha(proyecto["repo"], "main") == rama          # la base avanzo (ff)
    assert git(proyecto["repo"], "branch", "--show-current").stdout.strip() == "main"
    assert b.buscar("task-uno")[0] == "reviewed"
    assert sha(proyecto["repo"], "task-uno") == rama       # no borra ramas


def test_merge_no_fast_forward_hace_merge_commit(proyecto):
    repo = proyecto["repo"]
    (repo / "otro.txt").write_text("otro\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "avance directo de base")
    b = activar(proyecto)
    r = b.merge("task-uno")
    assert r["ok"] is True
    padres = git(repo, "log", "--pretty=%P", "-n", "1", "main").stdout.split()
    assert len(padres) == 2                             # merge commit real
    assert sha(repo, "task-uno") in padres


def test_merge_en_conflicto_deja_base_intacta_y_stopped(proyecto):
    repo = proyecto["repo"]
    (repo / "tarea.txt").write_text("otra version en base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base toca el mismo archivo")
    antes = sha(repo, "main")
    b = activar(proyecto)
    r = b.merge("task-uno")
    assert r["ok"] is False
    assert sha(repo, "main") == antes                    # la base NO se toco
    assert b.buscar("task-uno")[0] == "stopped"
    motivo = b.leer("task-uno")[4].get("Motivo de stopped", "")
    assert "AUTO_MERGE" in motivo


def test_merge_sucio_no_destruye_trabajo_del_humano(proyecto):
    repo = proyecto["repo"]
    (repo / "tarea.txt").write_text("archivo del humano sin commitear\n")
    antes = sha(repo, "main")
    b = activar(proyecto)
    r = b.merge("task-uno")
    assert r["ok"] is False
    assert sha(repo, "main") == antes
    assert (repo / "tarea.txt").read_text() == "archivo del humano sin commitear\n"
    assert b.buscar("task-uno")[0] == "stopped"


def test_merge_sin_rama_pasa_a_reviewed(proyecto):
    b = activar(proyecto)
    git(proyecto["repo"], "branch", "-D", "task-uno")    # ya no existe
    r = b.merge("task-uno")
    assert r["ok"] is True and r["estado"] == "reviewed"


def test_merge_idempotente(proyecto):
    b = activar(proyecto)
    b.merge("task-uno")
    r = b.merge("task-uno")                              # segunda vez: ya integrada
    assert r["ok"] is True and r["estado"] == "reviewed"
    assert any(h["accion"] == "ya-integrada" for h in r["repos"])


def test_merge_rechaza_tarea_no_done(proyecto):
    b = activar(proyecto)
    b.modificar("task-uno", "new")
    with pytest.raises(wi.Error, match="done"):
        b.merge("task-uno")


# ----------------------------------------------------------------- flujo
def test_aprobar_con_flag_mergea_y_deja_reviewed(proyecto):
    b = activar(proyecto)
    b.modificar("task-uno", "validando")
    r = subprocess.run([sys.executable, WI, str(proyecto["env"]), "aprobar", "task-uno"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    b2 = wi.Board(wi.cargar_config(str(proyecto["env"])))
    assert b2.buscar("task-uno")[0] == "reviewed"
    assert sha(proyecto["repo"], "main") == sha(proyecto["repo"], "task-uno")
    assert "auto-merge" in r.stdout


def test_aprobar_sin_flag_no_mergea(proyecto):
    proyecto["b"].modificar("task-uno", "validando")
    r = subprocess.run([sys.executable, WI, str(proyecto["env"]), "aprobar", "task-uno"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    assert proyecto["b"].buscar("task-uno")[0] == "done"
    assert sha(proyecto["repo"], "main") != sha(proyecto["repo"], "task-uno")