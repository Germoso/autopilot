"""La vista .md de una tarea solo trae el bug original (descripcion, criterio y adjuntos originales).
Notas, reportes, feedback e historial viven en la base: `get`. Editar o mover el .md no debe borrar nada de la base."""
import json
import os
import sys

import pytest

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
import workitems as wi  # noqa: E402


@pytest.fixture
def b(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)
    board = wi.Board(wi.cargar_config(str(env)))
    board.crear("bug", "100", "High", "Pantalla rota", "Descripcion de Azure", "Criterio de Azure")
    # adjunto original (vino con la tarea) y uno del coder: solo el original debe aparecer en el .md
    orig = os.path.join(board.dir, "adjuntos", "bug-100", "captura.png")
    coder = os.path.join(board.dir, "adjuntos", "bug-100", "coder-intento1", "prueba.png")
    for p in (orig, coder):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"\x89PNG")
    board.adjuntos("bug-100")
    board.modificar("bug-100", "in-progress")
    board.modificar("bug-100", "qa", secs_set={"Notas del desarrollador": "### Intento 1\n\nNOTAS-SECRETAS-DEL-CODER"})
    return board


def md_de(board, clave="bug-100"):
    return open(os.path.join(board.dir, board.db.fila(clave)["vista"]), encoding="utf-8").read()


def test_vista_solo_tiene_el_bug_y_sus_adjuntos_originales(b):
    texto = md_de(b)
    assert "Descripcion de Azure" in texto and "Criterio de Azure" in texto
    assert "## Adjuntos originales" in texto and "captura.png" in texto
    assert "prueba.png" not in texto                       # adjunto del coder: fuera de la vista
    assert "NOTAS-SECRETAS-DEL-CODER" not in texto         # notas: fuera de la vista
    for seccion in ("Notas del desarrollador", "Reporte de QA", "Feedback de QA", "Resultado", "Historial"):
        assert seccion not in texto


def test_get_resumen_y_todo_siguen_teniendo_todo(b):
    assert "NOTAS-SECRETAS-DEL-CODER" in b.get("bug-100", "notas")
    assert "NOTAS-SECRETAS-DEL-CODER" in b.get("bug-100", "todo")   # `todo` se arma desde la base
    assert "NOTAS-SECRETAS-DEL-CODER" not in md_de(b)


def test_json_no_expone_la_ruta_del_md(b):
    datos = json.loads(b.get("bug-100", "resumen", como_json=True))
    assert "archivo_md" not in datos
    assert any("NOTAS-SECRETAS-DEL-CODER" in str(e) for e in datos["entradas"])


def test_editar_el_md_a_mano_no_borra_el_historial(b):
    ruta = os.path.join(b.dir, b.db.fila("bug-100")["vista"])
    texto = open(ruta, encoding="utf-8").read().replace("Descripcion de Azure", "Descripcion corregida a mano")
    open(ruta, "w", encoding="utf-8").write(texto)
    b._sync_ok = False
    b._sincronizar()
    assert b.db.obtener("bug-100")[3]["Descripción"] == "Descripcion corregida a mano"
    assert "NOTAS-SECRETAS-DEL-CODER" in b.get("bug-100", "notas")   # el historial sigue en la base
    assert len(b.get("bug-100", "adjuntos").splitlines()) >= 1        # y los adjuntos tambien


def test_mover_el_md_cambia_el_estado_sin_borrar_historial(b):
    ruta = os.path.join(b.dir, b.db.fila("bug-100")["vista"])
    nueva = os.path.join(b.dir, "done", os.path.basename(ruta))
    os.makedirs(os.path.dirname(nueva), exist_ok=True)
    os.rename(ruta, nueva)
    b._sync_ok = False
    b._sincronizar()
    assert b.leer("bug-100")[0] == "done"
    assert "NOTAS-SECRETAS-DEL-CODER" in b.get("bug-100", "notas")


def test_editar_el_md_no_pisa_el_intento_de_la_base(b):
    b.modificar("bug-100", "qa", meta_set={"intento": "2"})
    ruta = os.path.join(b.dir, b.db.fila("bug-100")["vista"])
    texto = open(ruta, encoding="utf-8").read().replace("Criterio de Azure", "Criterio editado")
    texto = texto.replace("intento: 2", "intento: 0")   # frontmatter viejo, como si la vista fuera anterior
    open(ruta, "w", encoding="utf-8").write(texto)
    b._sync_ok = False
    b._sincronizar()
    assert b.db.obtener("bug-100")[1]["intento"] == "2"
