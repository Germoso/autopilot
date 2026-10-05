"""Pruebas de `pedir-cambios` (boton "Feedback y devolver" de la app web): el humano revisa una tarea
y la devuelve al coder, a QA o a E2E con su feedback.
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
    assert "FEEDBACK DEL HUMANO para el coder" in secs["Feedback de QA"] and "El botón debe decir Guardar" in secs["Feedback de QA"]
    # El QA certifica contra el criterio: el pedido tiene que estar ahi, sin perder el original.
    assert secs["Criterio de aceptación"].startswith("criterio original")
    assert "El botón debe decir Guardar" in secs["Criterio de aceptación"]
    # El coder lo ve como el ultimo feedback en `get`.
    resumen = b.get("task-uno")
    assert "El botón debe decir Guardar" in resumen.split("## Último feedback", 1)[1]


def test_solo_desde_done_reviewed_o_stopped(board):
    board["b"].modificar("task-uno", "qa")
    r = cli(board, "pedir-cambios", "task-uno", "algo")
    assert r.returncode != 0 and "done, reviewed o stopped" in r.stderr
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
    assert avisos and avisos[-1].startswith("💬 Le diste feedback al coder") and "Otro color" in avisos[-1]


# ----------------------------------------------------------------- a QA y a E2E
def test_a_qa_vuelve_a_certificar(board):
    r = cli(board, "pedir-cambios", "task-uno", "Verifica también con un usuario sin permisos", "--a", "qa")
    assert r.returncode == 0, r.stderr
    estado, _, meta, _, secs = board["b"].leer("task-uno")
    assert estado == "qa" and meta["intento"] == "0"
    assert "FEEDBACK DEL HUMANO para QA" in secs["Feedback de QA"]
    assert "usuario sin permisos" in secs["Criterio de aceptación"]
    assert "usuario sin permisos" in board["b"].get("task-uno").split("## Último feedback", 1)[1]


def test_a_e2e_necesita_e2e_activo(board):
    r = cli(board, "pedir-cambios", "task-uno", "Prueba en Android", "--a", "e2e")
    assert r.returncode != 0 and "E2E" in r.stderr
    assert board["b"].leer("task-uno")[0] == "done"


def test_a_e2e_vuelve_a_probar(board):
    board["env"].write_text(board["env"].read_text() + "E2E=true\n")
    board["b"] = wi.Board(wi.cargar_config(str(board["env"])))
    r = cli(board, "pedir-cambios", "task-uno", "Prueba el flujo completo en Android", "--a", "e2e")
    assert r.returncode == 0, r.stderr
    estado, _, meta, _, secs = board["b"].leer("task-uno")
    assert estado == "e2e" and meta["intento"] == "2"          # E2E no cuenta intentos (como re-e2e)
    assert "para E2E" in secs["Feedback de E2E"] and "Android" in secs["Criterio de aceptación"]


def test_desde_stopped_y_destino_invalido(board):
    board["b"].modificar("task-uno", "stopped", secs_set={"Motivo de stopped": "NO CERTIFICABLE"})
    assert cli(board, "pedir-cambios", "task-uno", "x", "--a", "otro").returncode != 0
    r = cli(board, "pedir-cambios", "task-uno", "Usa la cuenta de pruebas 2", "--a", "qa")
    assert r.returncode == 0, r.stderr
    estado, _, _, _, secs = board["b"].leer("task-uno")
    assert estado == "qa" and not secs.get("Motivo de stopped", "").strip()


@pytest.mark.parametrize("estado,seccion,inicio", [("qa", "Feedback de QA", "💬 Le diste feedback a QA"),
                                                    ("e2e", "Feedback de E2E", "💬 Le diste feedback a E2E")])
def test_aviso_de_telegram_a_qa_y_e2e(board, monkeypatch, estado, seccion, inicio):
    b = board["b"]
    avisos = []
    monkeypatch.setattr(b, "avisar", lambda texto, *a, **k: avisos.append(texto))
    b.modificar("task-uno", estado, secs_append={seccion: "### FEEDBACK DEL HUMANO para X (hoy)\n\nMira esto"})
    assert avisos and avisos[-1].startswith(inicio) and "Mira esto" in avisos[-1]


def test_bloques_viejos_de_pedir_cambios_se_siguen_reconociendo(board, monkeypatch):
    b = board["b"]
    avisos = []
    monkeypatch.setattr(b, "avisar", lambda texto, *a, **k: avisos.append(texto))
    b.modificar("task-uno", "qa", secs_append={"Feedback de QA": "### CAMBIOS PEDIDOS en la revisión humana, para QA (ayer)\n\nViejo"})
    assert avisos and avisos[-1].startswith("💬 Le diste feedback a QA") and "Viejo" in avisos[-1]
