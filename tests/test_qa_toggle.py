"""QA=true|false: con QA=false el kit no lanza certificaciones; las tareas esperan en Cola QA."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import workitems as wi  # noqa: E402


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def armar(extra=""):
        env = tmp_path / "autopilot.env"
        env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n%s" % (tmp_path, extra))
        b = wi.Board(wi.cargar_config(str(env)))
        b.crear("task", "uno", "Medium", "T", "desc", "crit")
        b.modificar("task-uno", "qa")
        return b
    return armar


def test_qa_por_defecto_esta_activo(board):
    b = board()
    assert b.cfg["qa"]["activo"] is True and b.cfg["qa"]["invalido"] is None


def test_qa_false_no_ofrece_certificar(board):
    b = board("QA=false\n")
    assert b.cfg["qa"]["activo"] is False
    acciones = b.plan()["acciones"]
    assert not [a for a in acciones if a["puesto"] == "qa"]


def test_qa_true_si_ofrece_certificar(board):
    b = board("QA=true\n")
    acciones = b.plan()["acciones"]
    assert [a for a in acciones if a["puesto"] == "qa" and a["tarea"]["id"] == "task-uno"]


def test_qa_false_avisa_de_tareas_esperando(board):
    b = board("QA=false\n")
    assert any("Cola QA" in a and "task-uno" in a for a in b.avisos())


def test_qa_invalido_avisa_y_usa_true(board):
    b = board("QA=quizas\n")
    assert b.cfg["qa"]["activo"] is True
    assert any("QA=quizas" in a for a in b.avisos())
