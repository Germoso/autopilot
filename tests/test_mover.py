"""Movimiento manual del humano: a cualquier estado (menos ignored), con motivo al detener y con la
capacidad de los puestos respetada."""
import os
import sys

import pytest

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
import workitems as wi  # noqa: E402

# new es el estado inicial de la prueba; ignored tiene su propio comando
ESTADOS_MANUALES = [e for e in wi.ESTADOS if e not in ("new", "ignored")]


@pytest.fixture
def b(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)
    board = wi.Board(wi.cargar_config(str(env)))
    board.crear("bug", "100", "High", "Pantalla rota", "d", "c")
    board.crear("bug", "101", "High", "Otra", "d", "c")
    return board


@pytest.mark.parametrize("destino", ESTADOS_MANUALES)
def test_desde_new_a_cualquier_estado(b, destino):
    b.mover("bug-100", destino, "motivo de prueba")
    assert b.leer("bug-100")[0] == destino


def test_revisada_a_mano_desde_cualquier_estado(b):
    b.mover("bug-100", "qa")
    b.mover("bug-100", "reviewed")
    assert b.leer("bug-100")[0] == "reviewed"


def test_detener_pide_motivo_y_lo_guarda(b):
    with pytest.raises(wi.Error, match="motivo"):
        b.mover("bug-100", "stopped")
    b.mover("bug-100", "stopped", "esperando al cliente")
    assert b.leer("bug-100")[4]["Motivo de stopped"] == "esperando al cliente"


def test_nueva_limpia_el_motivo(b):
    b.mover("bug-100", "stopped", "algo")
    b.mover("bug-100", "new")
    assert b.leer("bug-100")[4]["Motivo de stopped"] == ""


def test_ignored_no_se_mueve_con_mover(b):
    with pytest.raises(wi.Error, match="ignorar"):
        b.mover("bug-100", "ignored")
    assert b.leer("bug-100")[0] == "new"


def test_estado_invalido_y_mismo_estado(b):
    with pytest.raises(wi.Error, match="invalido"):
        b.mover("bug-100", "nada")
    with pytest.raises(wi.Error, match="ya esta en"):
        b.mover("bug-100", "new")


def test_respeta_la_capacidad_del_coder(b):
    b.mover("bug-100", "in-progress")
    with pytest.raises(wi.Error, match="lleno"):
        b.mover("bug-101", "in-progress")
    assert b.leer("bug-101")[0] == "new"


def test_queda_registrado_en_el_log(b):
    b.mover("bug-100", "qa")
    evento = [r for r in b.db.q("SELECT evento, detalle FROM log WHERE tarea=?", ("bug-100",))]
    assert any("Movida a mano: new -> qa" in (r["evento"] or "") for r in evento)
