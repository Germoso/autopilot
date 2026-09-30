"""Pruebas del menu de botones (reply keyboard) del bot de Telegram.

Cubren el cambio de telegram.py: los comandos sin argumento se ofrecen como
botones y /ayuda manda la documentacion junto con el teclado.
"""
import http.server
import json
import os
import sys
import threading
import urllib.parse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import telegram  # noqa: E402


def cfg_minimo(tmp_path):
    """Un cfg que alcanza para comando() y responder() sin tocar el tablero."""
    return {
        "raiz": str(tmp_path),
        "dir": str(tmp_path),
        "repos": {},  # secretos() no encuentra .env reales
        "telegram": {"activo": True, "solo_alertas": False},
        "workspace": False,
        "paralelo": False,
        "capacidad": {},
        "vigia": {},
        "e2e": {},
        "env_path": None,
    }


# ----------------------------------------------------------------- teclado
def test_teclado_es_un_reply_keyboard_valido():
    assert "keyboard" in telegram.TECLADO
    filas = telegram.TECLADO["keyboard"]
    assert isinstance(filas, list) and len(filas) >= 2
    for fila in filas:
        assert fila and all(isinstance(b, dict) and b.get("text") for b in fila)
    assert telegram.TECLADO["resize_keyboard"] is True
    assert telegram.TECLADO["one_time_keyboard"] is False
    assert telegram.TECLADO["input_field_placeholder"]
    json.dumps(telegram.TECLADO)  # serializable para el reply_markup


def test_teclado_solo_comandos_sin_argumento():
    botones = [b["text"] for f in telegram.TECLADO["keyboard"] for b in f]
    assert botones == ["/estado", "/cola", "/health", "/pausa", "/seguir", "/ayuda"]
    for b in botones:
        assert b.startswith("/") and len(b.split()) == 1  # sin argumento


# ----------------------------------------------------------------- comando()
@pytest.mark.parametrize("texto", ["/start", "/ayuda", "/help"])
def test_ayuda_devuelve_documentacion_con_teclado(tmp_path, texto):
    resp = telegram.comando(cfg_minimo(tmp_path), "x", texto)
    assert resp == (telegram.AYUDA, True)


def test_comando_desconocido_devuelve_con_teclado(tmp_path):
    resp = telegram.comando(cfg_minimo(tmp_path), "x", "/no-existe")
    assert resp[1] is True
    assert "No conozco" in resp[0] and telegram.AYUDA in resp[0]


def test_comando_normal_devuelve_sin_teclado(tmp_path):
    resp = telegram.comando(cfg_minimo(tmp_path), "x", "/tarea")
    assert resp == ("uso: /tarea <clave>", False)


# ----------------------------------------------------------------- responder()
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
def api_local(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.capturas = []
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("AUTOPILOT_TELEGRAM_API", "http://127.0.0.1:%d" % srv.server_port)
    monkeypatch.setattr(telegram, "credenciales", lambda: ("tok", "123"))
    yield srv
    srv.shutdown()


def _ultimo(srv):
    ruta, cuerpo = srv.capturas[-1]
    assert ruta == "/bottok/sendMessage"
    return urllib.parse.parse_qs(cuerpo)


def test_responder_con_teclado_adjunta_el_teclado(tmp_path, api_local):
    telegram.responder(cfg_minimo(tmp_path), "hola", con_teclado=True)
    d = _ultimo(api_local)
    assert d.get("text") == ["hola"]
    assert json.loads(d["reply_markup"][0]) == telegram.TECLADO


def test_responder_sin_teclado_no_adjunta_teclado(tmp_path, api_local):
    telegram.responder(cfg_minimo(tmp_path), "hola")
    d = _ultimo(api_local)
    assert d.get("text") == ["hola"]
    assert "reply_markup" not in d