"""Pruebas del aviso de cadena detenida (Board.cadena + lib/cadena.py).

¿Qué haría que estos tests fallaran antes de implementar? Board.cadena() no existe,
cadena.py no existe (import Error), y cargar_config no tiene la seccion "cadena".
"""
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import workitems as wi  # noqa: E402
import cadena  # noqa: E402


@pytest.fixture
def board(tmp_path):
    """Board temporal sin Telegram y sin repo (crear/modificar no tocan red)."""
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\n")
    cfg = wi.cargar_config(str(env))
    b = wi.Board(cfg)
    b.cfg = cfg
    return b, env, cfg


def nueva_done(board, numero, hacia="done"):
    b, _, _ = board
    b.crear("task", numero, "Medium", "Tarea " + numero, "desc", "criterio")
    if hacia:
        b.modificar("task-" + numero, hacia)


# ------------------------------------------------------------- Board.cadena()
def test_cadena_board_vacio_no_parada(board):
    b, _, _ = board
    c = b.cadena()
    assert c["parada"] is False
    assert c["pendiente"] == {"done": 0, "stopped": 0, "en_espera": 0}


def test_cadena_done_sin_revisar_es_parada(board):
    nueva_done(board, "uno")
    c = board[0].cadena()
    assert c["parada"] is True
    assert c["pendiente"]["done"] == 1


def test_cadena_new_asignable_no_parada(board):
    b, _, _ = board
    b.crear("task", "uno", "Medium", "T", "d", "c")
    c = b.cadena()
    assert c["parada"] is False
    assert c["asignables"] >= 1  # coder libre y tarea lista


def test_cadena_en_espera_por_dependencias_es_parada(board):
    nueva_done(board, "a")
    b, _, _ = board
    b.crear("task", "b", "Medium", "B", "d", "c", depende="task-a")
    c = b.cadena()
    assert c["parada"] is True
    assert c["pendiente"]["en_espera"] == 1


def test_cadena_puesto_ocupado_no_parada(board):
    nueva_done(board, "uno", hacia="in-progress")
    c = board[0].cadena()
    assert c["parada"] is False


def test_cadena_con_pausa_no_parada(board):
    nueva_done(board, "uno")
    b, _, _ = board
    open(os.path.join(b.dir, ".pausa"), "w").write("pausa")
    c = b.cadena()
    assert c["parada"] is False  # pausa explicita != atascado


def test_cadena_stopped_es_parada(board):
    nueva_done(board, "uno", hacia="stopped")
    c = board[0].cadena()
    assert c["parada"] is True
    assert c["pendiente"]["stopped"] == 1


# ------------------------------------------------------------- cadena.decidir
def test_decidir_primera_deteccion_no_avisa_todavia():
    desde, avisar, avisada, ultimo = cadena.decidir({}, True, 1000.0, 20, 240)
    assert desde == 1000.0
    assert avisar is False and avisada is False and ultimo is None


def test_decidir_avisa_al_superar_el_umbral():
    ahora = 1000.0
    prev = {"desde": ahora - 21 * 60, "avisada": False, "ultimo_aviso": None}
    desde, avisar, avisada, ultimo = cadena.decidir(prev, True, ahora, 20, 240)
    assert avisar is True and avisada is True and ultimo == ahora


def test_decidir_no_reavisa_antes_del_reaviso():
    ahora = 1000.0
    prev = {"desde": ahora - 3 * 3600, "avisada": True, "ultimo_aviso": ahora - 3600}
    desde, avisar, avisada, ultimo = cadena.decidir(prev, True, ahora, 20, 240)
    assert avisar is False and avisada is True and ultimo == ahora - 3600


def test_decidir_reavisa_despues_del_reaviso():
    ahora = 1000.0
    prev = {"desde": ahora - 10 * 3600, "avisada": True, "ultimo_aviso": ahora - 5 * 3600}
    desde, avisar, avisada, ultimo = cadena.decidir(prev, True, ahora, 20, 240)
    assert avisar is True and avisada is True and ultimo == ahora


def test_decidir_reaviso_cero_no_reavisa():
    ahora = 1000.0
    prev = {"desde": ahora - 3600, "avisada": True, "ultimo_aviso": ahora - 60}
    desde, avisar, avisada, ultimo = cadena.decidir(prev, True, ahora, 20, 0)
    assert avisar is False and avisada is True and ultimo == ahora - 60


def test_decidir_se_resetea_cuando_no_hay_parada():
    desde, avisar, avisada, ultimo = cadena.decidir({"desde": 100.0}, False, 1000.0, 20, 240)
    assert desde is None and avisar is False and avisada is False and ultimo is None


# ------------------------------------------------------------- cadena.texto
def test_texto_incluye_conteos_y_minutos():
    t = cadena.texto({"pendiente": {"done": 3, "en_espera": 2, "stopped": 1}}, 25)
    assert "detenido hace 25 min" in t
    assert "3 en done sin revisar" in t
    assert "2 bloqueadas por dependencias" in t
    assert "1 en stopped" in t


# ------------------------------------------------------------- end-to-end
class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        self.server.capturas.append((self.path, self.rfile.read(largo).decode()))
        cuerpo = json.dumps({"ok": True, "result": {}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass


@pytest.fixture
def api_local(monkeypatch, tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.capturas = []
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("AUTOPILOT_TELEGRAM_API", "http://127.0.0.1:%d" % srv.server_port)
    cfg_dir = tmp_path / "config" / "autopilot-kit"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "telegram.env").write_text("TELEGRAM_BOT_TOKEN=tok\nTELEGRAM_CHAT_ID=123\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))  # dedup y estado aislados por test
    yield srv
    srv.shutdown()


def _esperar_capturas(srv, seg=5):
    fin = time.time() + seg
    while time.time() < fin and not srv.capturas:
        time.sleep(0.2)
    return srv.capturas


def test_alerta_cadena_llega_por_telegram(board, api_local, tmp_path):
    nueva_done(board, "uno")
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nTELEGRAM=true\nCADENA_MIN=1\n")
    cfg = wi.cargar_config(str(env))
    # la cadena ya lleva mas de CADENA_MIN parada: el estado previo asi lo dice
    path = cadena.estado_path(str(env))
    cadena.guardar_estado(path, {"desde": time.time() - 120, "avisada": False, "ultimo_aviso": None})
    cadena.main([str(env)])
    capturas = _esperar_capturas(api_local)
    assert capturas, "no llego el aviso al servidor de prueba"
    ruta, cuerpo = capturas[-1]
    assert ruta == "/bottok/sendMessage"
    d = urllib.parse.parse_qs(cuerpo)
    assert "detenido hace" in d["text"][0]
    assert "1 en done sin revisar" in d["text"][0]
    assert cfg["cadena"]["min"] == 1  # CADENA_MIN=1 se leyo del env


def test_simular_no_escribe_estado_ni_envia(board, api_local, tmp_path):
    nueva_done(board, "uno")
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nTELEGRAM=true\nCADENA_MIN=1\n")
    cadena.main([str(env), "--simular"])
    time.sleep(0.5)
    assert not api_local.capturas
    assert not os.path.exists(cadena.estado_path(str(env)))