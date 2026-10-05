"""El servidor web sirve los adjuntos con Range (206): sin eso Safari no reproduce videos."""
import http.client
import json
import os
import sys
import threading

import pytest

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "web"))


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import servidor as srv
    monkeypatch.setattr(srv, "CONF", str(tmp_path / "config" / "autopilot-kit"))
    env = tmp_path / "autopilot.env"
    env.write_text("WORKITEMS_DIR=board\nREPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)
    import workitems as wi
    b = wi.Board(wi.cargar_config(str(env)))
    b.crear("task", "uno", "Medium", "T", "d", "c")
    carpeta = os.path.join(b.dir, "adjuntos", "task-uno")
    os.makedirs(carpeta)
    datos = bytes(range(256)) * 1000                     # 256000 bytes
    open(os.path.join(carpeta, "video.mp4"), "wb").write(datos)
    s = srv.Servidor(("127.0.0.1", 0), srv.Handler)
    s.extra, s.con_clave, s.clave, s.sesion = [str(env)], False, "", "x"
    threading.Thread(target=s.serve_forever, daemon=True).start()
    con = http.client.HTTPConnection("127.0.0.1", s.server_address[1])
    con.request("GET", "/api/proyectos")
    pid = json.loads(con.getresponse().read())[0]["id"]
    yield {"puerto": s.server_address[1], "pid": pid, "datos": datos}
    s.shutdown()


def pedir(s, rango=None):
    con = http.client.HTTPConnection("127.0.0.1", s["puerto"])
    con.request("GET", "/api/p/%s/archivo?ruta=adjuntos/task-uno/video.mp4" % s["pid"],
                headers={"Range": rango} if rango else {})
    r = con.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_completo_anuncia_rangos(servidor):
    st, h, cuerpo = pedir(servidor)
    assert st == 200 and h["Accept-Ranges"] == "bytes" and h["Content-Type"] == "video/mp4"
    assert cuerpo == servidor["datos"]


@pytest.mark.parametrize("rango,ini,fin", [("bytes=0-1", 0, 1), ("bytes=1000-", 1000, 255999),
                                           ("bytes=-10", 255990, 255999), ("bytes=255000-999999", 255000, 255999)])
def test_rango_206(servidor, rango, ini, fin):
    st, h, cuerpo = pedir(servidor, rango)
    assert st == 206
    assert h["Content-Range"] == "bytes %d-%d/256000" % (ini, fin)
    assert cuerpo == servidor["datos"][ini:fin + 1]


def test_rango_invalido_416(servidor):
    st, h, _ = pedir(servidor, "bytes=300000-")
    assert st == 416 and h["Content-Range"] == "bytes */256000"
