"""Pruebas de `pedir-cambios`: el humano revisa una tarea (done o reviewed) y la devuelve al coder
con lo que quiere cambiar, desde la app web.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import workitems as wi  # noqa: E402

WI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "workitems.py")


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "T", "d", "criterio original")
    b.modificar("task-uno", "done", meta_set={"intento": "2"})
    return {"b": b, "env": env}


def cli(p, *args):
    return subprocess.run([sys.executable, WI, str(p["env"])] + list(args), capture_output=True, text=True)


@pytest.mark.parametrize("desde", ["done", "reviewed"])
def test_vuelve_al_coder_con_el_pedido(board, desde):
    b = board["b"]
    if desde == "reviewed":
        b.modificar("task-uno", "reviewed")
    r = cli(board, "pedir-cambios", "task-uno", "El botón debe decir Guardar")
    assert r.returncode == 0, r.stderr
    estado, _, meta, _, secs = b.leer("task-uno")
    assert estado == "bug-fix"
    assert meta["intento"] == "0"
    assert "CAMBIOS PEDIDOS" in secs["Feedback de QA"] and "El botón debe decir Guardar" in secs["Feedback de QA"]
    # El QA certifica contra el criterio: el pedido tiene que estar ahi, sin perder el original.
    assert secs["Criterio de aceptación"].startswith("criterio original")
    assert "El botón debe decir Guardar" in secs["Criterio de aceptación"]
    # El coder lo ve como el ultimo feedback en `get`.
    resumen = b.get("task-uno")
    assert "El botón debe decir Guardar" in resumen.split("## Último feedback", 1)[1]


def test_solo_desde_done_o_reviewed(board):
    board["b"].modificar("task-uno", "qa")
    r = cli(board, "pedir-cambios", "task-uno", "algo")
    assert r.returncode != 0 and "done o reviewed" in r.stderr
    assert board["b"].leer("task-uno")[0] == "qa"


def test_texto_obligatorio(board):
    r = cli(board, "pedir-cambios", "task-uno", "   ")
    assert r.returncode != 0
    assert board["b"].leer("task-uno")[0] == "done"


def test_aviso_de_telegram(board, monkeypatch):
    b = board["b"]
    avisos = []
    monkeypatch.setattr(b, "avisar", lambda texto, *a, **k: avisos.append(texto))
    b.modificar("task-uno", "bug-fix", secs_append={
        "Feedback de QA": "### CAMBIOS PEDIDOS en la revisión humana (hoy)\n\nOtro color"})
    assert avisos and avisos[-1].startswith("✏️") and "Otro color" in avisos[-1]
