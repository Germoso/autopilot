"""Kit — contrato de mensajeria resiliente de Orca, documentado y verificable.

Regresion del contrato validado en sesion real: los mensajes del coder
(question/escalation/worker_done) quedan **encolados durables** en el inbox del run;
CUALQUIER `orca orchestration check` (con o sin `--wait`) los entrega en FIFO; una
delivery se acusa (check --ack) solo despues de procesarla; el nudge es atencion, no
contenido; y el coder pregunta al coordinador con su `ask` (nunca por un TUI local que
el coordinador no puede ver).

Los escenarios de runtime (S1..S5) viven en Orca; este test fija que la skill del
orquestador, la referencia y el rol del coder no pierdan el contrato. Sin pytest import:
funciones `test_*` que pytest tambien recolecta; ademas corre standalone con
`python3 tests/test_mensajeria_orca.py`.
"""

import os
import re
import sys

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _leer(*rel):
    with open(os.path.join(RAIZ, *rel), encoding="utf-8") as f:
        return f.read()


def _norm(s):
    # colapso de espacios + minusculas: el test no depende de quiebres de linea ni caps
    return re.sub(r"\s+", " ", s).lower()


SKILL = _norm(_leer("skills", "autopilot", "SKILL.md"))
REF = _norm(_leer("docs", "REFERENCIA.md"))
COD = _norm(_leer("agents", "coder.md"))


def _contiene(doc, *fragmentos):
    for f in fragmentos:
        assert _norm(f) in doc, f


def test_mensajes_encolados_durables_no_se_pierden():
    for doc in (SKILL, REF):
        _contiene(doc, "encolad", "no se pierden")


def test_cualquier_check_entrega_y_wait_es_solo_comodidad():
    _contiene(SKILL, "con o sin `--wait`", "solo comodidad")
    _contiene(REF, "con o sin `--wait`", "solo evita el polling")


def test_ack_solo_despues_de_procesar_y_redelivery():
    for doc in (SKILL, REF):
        _contiene(doc, "check --ack", "antes de acusar")


def test_nudge_es_atencion_no_contenido():
    _contiene(SKILL, "nudge")
    _contiene(REF, "nudge")


def test_coder_pregunta_por_ask_no_por_tui_local():
    _contiene(COD, "`ask`", "tui local", "encolad", "no es abandono", "preguntarle al coordinador")


def test_mensajes_stale_se_verifican_con_evidencia():
    for doc in (SKILL, REF):
        _contiene(doc, "stale", "evidencia")


def test_grill_es_del_orquestador_antes_de_despachar():
    _contiene(SKILL, "grill", "antes de despachar")  # el orquestador grilla pre-dispatch
    _contiene(COD, "el orquestador")  # en el coder solo como referencia a que YA gRILLO
    for skill in ("grill-me", "grilling"):
        assert skill not in COD  # el coder NO carga grill: arranca con el brief aclarado


def test_redaccion_vieja_eliminada():
    for doc in (SKILL, REF):
        assert "nunca deja de escuchar" not in doc
        assert "truth orchestration" not in doc


if __name__ == "__main__":
    fallas = 0
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            try:
                _f()
                print("ok   %s" % _n)
            except AssertionError as _e:
                fallas += 1
                print("FAIL %s: %s" % (_n, _e))
    print("\n%s falla(s)" % fallas)
    sys.exit(1 if fallas else 0)