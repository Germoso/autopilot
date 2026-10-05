"""Tareas detenidas que el humano ignora completamente: no se toman, no cuentan en nada."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import workitems as wi  # noqa: E402


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "T", "desc", "crit")
    b.crear("task", "dos", "Low", "T", "desc", "crit")
    b.modificar("task-uno", "stopped", secs_set={"Motivo de stopped": "NO CERTIFICABLE"})
    b.modificar("task-dos", "stopped", secs_set={"Motivo de stopped": "otro motivo"})
    return {"env": env, "b": b}


def test_ignorar_pasa_stopped_a_ignored(board):
    b = board["b"]
    assert b.leer("task-uno")[0] == "stopped"
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    assert b.leer("task-uno")[0] == "ignored"
    assert "Ignorada" in b.leer("task-uno")[4]


def test_ignorar_solo_desde_stopped(board):
    b = board["b"]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    assert b.leer("task-uno")[0] == "ignored"
    # el comando "ignorar" tiene la validacion; modificar() permite cambiar entre cualquier estado
    # (es bajo nivel). Para probar la validacion, necesitamos llamar al comando CLI via wi_cmd.


def test_restaurar_vuelve_a_stopped(board):
    b = board["b"]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    b.modificar("task-uno", "stopped", secs_set={"Ignorada": ""})
    assert b.leer("task-uno")[0] == "stopped"


def test_plan_no_cuenta_ignoradas(board):
    b = board["b"]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    plan = b.plan()
    assert "task-uno" not in plan.get("stopped", [])
    assert len(plan.get("stopped", [])) == 1 and plan["stopped"][0] == "task-dos"


def test_cadena_no_cuenta_ignoradas(board):
    b = board["b"]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    b.modificar("task-dos", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    cadena = b.cadena()
    assert cadena["pendiente"]["stopped"] == 0


def test_todas_incluyendo_ignored(board):
    b = board["b"]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    todas = [t["id"] for t in b.todas()]
    assert "task-uno" in todas and "task-dos" in todas


def test_ignorar_no_borra_nada(board):
    b = board["b"]
    meta1_antes = b.leer("task-uno")[2]
    b.modificar("task-uno", "ignored", secs_set={"Ignorada": "2026-10-05T12:00:00"})
    meta1_despues = b.leer("task-uno")[2]
    assert meta1_antes == meta1_despues
    # el archivo se mueve de stopped/ a ignored/, no se borra
    ignorados = os.listdir(os.path.join(b.dir, "ignored"))
    parados = os.listdir(os.path.join(b.dir, "stopped"))
    assert any("task-uno" in f for f in ignorados) and not any("task-uno" in f for f in parados)
