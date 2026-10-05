#!/usr/bin/env python3
"""
servidor.py — app web del autopilot: ver y gestionar los tableros (solo stdlib).

uso: autopilot-web [--lan] [--port 8765] [--env <autopilot.env>]...
  sin --lan   solo en http://localhost:<puerto> (esta maquina)
  --lan       tambien desde la red local (celular, otra PC): pide la CLAVE de
              ~/.config/autopilot-kit/web.env (se crea sola la primera vez). Va sin HTTPS: usala solo en
              redes de confianza.
Muestra todos los proyectos donde se uso el kit (~/.config/autopilot-kit/proyectos.json) y los --env.

Seguridad: cookie HttpOnly + SameSite=Strict; toda accion (POST) exige el encabezado X-Autopilot (un
sitio ajeno no puede mandarlo); las acciones pasan por wi.sh (mismas validaciones y avisos); solo se
sirven archivos de .workitems/ y test-results/ del proyecto; nunca se muestran valores de los .env ni
de cuentas-e2e.env.
"""
import base64
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse

WEB = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(WEB)
sys.path.insert(0, KIT)
import workitems as wi  # noqa: E402
import cadena  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autopilot-kit")
ESTATICOS = os.path.join(WEB, "estatico")
TRABAJOS = {}          # id -> {proyecto, que, proceso, salida, inicio, fin, rc}
ACCIONES = {"reqa": "reqa", "re-e2e": "re-e2e", "stop": "stopped", "reviewed": "reviewed", "new": "new", "cambios": "pedir-cambios",
            "prioridad": "prioridad", "criterio": "criterio", "descripcion": "descripcion", "titulo": "titulo"}


def clave_web():
    path = os.path.join(CONF, "web.env")
    v = {}
    if os.path.isfile(path):
        for l in open(path):
            if "=" in l:
                k, x = l.strip().split("=", 1)
                v[k] = x
    if not v.get("WEB_CLAVE"):
        v["WEB_CLAVE"] = secrets.token_urlsafe(18)
        os.makedirs(CONF, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("WEB_CLAVE=%s\n" % v["WEB_CLAVE"])
    return v["WEB_CLAVE"]


def proyectos(extra):
    try:
        lista = json.load(open(os.path.join(CONF, "proyectos.json")))
    except (OSError, ValueError):
        lista = []
    vistos, out = set(), []
    for env in list(extra) + lista:
        env = os.path.abspath(env)
        if env in vistos or not os.path.isfile(env):
            continue
        vistos.add(env)
        pid = hashlib.sha1(env.encode()).hexdigest()[:10]
        out.append({"id": pid, "env": env, "nombre": os.path.basename(os.path.dirname(env))})
    return out


def board(env):
    return wi.Board(wi.cargar_config(env))


def limpiar(cfg, x):
    """Quita valores de .env / cuentas de cualquier texto (o estructura) que se manda al navegador."""
    try:
        import telegram
        secretos = telegram.secretos(cfg)
    except Exception:
        secretos = []
    def f(v):
        if isinstance(v, str):
            for s in secretos:
                if s and s in v:
                    v = v.replace(s, "***")
            return v
        if isinstance(v, list):
            return [f(i) for i in v]
        if isinstance(v, dict):
            return {k: f(i) for k, i in v.items()}
        return v
    return f(x)


GIT_OPS = {"merge": ["merge", "{clave}", "--humano"], "push-base": ["push", "{clave}", "base"],
           "push-rama": ["push", "{clave}", "rama"], "pr": ["pr", "{clave}"]}


def wi_cmd(env, *args):
    r = subprocess.run([sys.executable, os.path.join(KIT, "workitems.py"), env] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=300)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "autopilot-web"

    def log_message(self, fmt, *args):
        pass

    # -- utilidades
    def enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        if not isinstance(cuerpo, (bytes, bytearray)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def error(self, codigo, msg):
        self.enviar(codigo, {"error": msg})

    def autorizado(self):
        if not self.server.con_clave:
            return True
        c = dict(x.strip().split("=", 1) for x in (self.headers.get("Cookie") or "").split(";") if "=" in x)
        return hmac.compare_digest(c.get("ap_sesion", ""), self.server.sesion)

    def cuerpo(self, maximo=80 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > maximo:
            raise ValueError("demasiado grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def proyecto(self, pid):
        p = next((p for p in proyectos(self.server.extra) if p["id"] == pid), None)
        if not p:
            raise KeyError("proyecto")
        return p

    # -- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        ruta, q = u.path, urllib.parse.parse_qs(u.query)
        if ruta == "/" or ruta.startswith("/static/"):
            return self.estatico("index.html" if ruta == "/" else ruta[len("/static/"):])
        if ruta == "/api/sesion":
            return self.enviar(200, {"ok": self.autorizado(), "con_clave": self.server.con_clave})
        if not self.autorizado():
            return self.error(401, "falta la clave")
        try:
            if ruta == "/api/proyectos":
                return self.enviar(200, proyectos(self.server.extra))
            m = re.match(r"^/api/p/(\w+)/(.+)$", ruta)
            if not m:
                return self.error(404, "no existe")
            p = self.proyecto(m.group(1))
            return self.api_get(p, m.group(2), q)
        except KeyError:
            return self.error(404, "no existe")
        except wi.Error as e:
            return self.error(400, str(e))

    def estatico(self, nombre):
        path = os.path.realpath(os.path.join(ESTATICOS, nombre))
        if not path.startswith(os.path.realpath(ESTATICOS) + os.sep) or not os.path.isfile(path):
            return self.error(404, "no existe")
        tipo = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript",):
            tipo += "; charset=utf-8"
        self.enviar(200, open(path, "rb").read(), tipo,
                    {"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
                                                "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"})

    def api_get(self, p, sub, q):
        b = board(p["env"])
        cfg = b.cfg
        if sub == "tablero":
            ts = []
            for e, c, _ in b.archivos():
                estado, meta, titulo, secs = b.db.obtener(c)
                ts.append({"clave": c, "titulo": titulo, "estado": estado, "prioridad": meta.get("prioridad", "Medium"),
                           "intento": meta.get("intento", "0"), "repo": meta.get("repo", ""),
                           "repos_extra": meta.get("repos_extra", ""), "espera": meta.get("espera"),
                           "depende": meta.get("depende", ""),
                           "actualizado": meta.get("actualizado", ""), "origen": meta.get("origen", "")})
            pausa = os.path.exists(os.path.join(b.dir, ".pausa"))
            watcher = subprocess.run(["pgrep", "-f", "watcher.sh %s" % p["env"]], capture_output=True).returncode == 0 or \
                subprocess.run(["pgrep", "-f", "watcher.sh ./autopilot.env"], capture_output=True).returncode == 0
            return self.enviar(200, limpiar(cfg, {
                "tareas": ts, "estados": wi.ESTADOS, "pausa": pausa, "watcher": watcher, "e2e": cfg["e2e"]["activo"],
                "cadena": cadena.info(p["env"]),
                "auto_merge": cfg.get("auto_merge", False),
                "repos": sorted(n or os.path.basename(r["path"]) for n, r in cfg["repos"].items()),
                "capacidad": cfg["capacidad"], "telegram": cfg.get("telegram", {}).get("activo", False)}))
        m = re.match(r"^tarea/((?:task|bug)-%s)$" % wi.ID, sub)
        if m:
            clave = m.group(1)
            estado, path, meta, titulo, secs = b.leer(clave)
            b.adjuntos(clave)
            datos = {"clave": clave, "estado": estado, "titulo": titulo, "meta": meta,
                     "descripcion": secs.get("Descripción", ""), "criterio": secs.get("Criterio de aceptación", ""),
                     "adjuntos_md": secs.get("Adjuntos", ""), "repos_modificados": secs.get("Repos modificados", ""),
                     "resultado": secs.get("Resultado", ""), "motivo": secs.get("Motivo de stopped", ""),
                     "entradas": b.db.entradas(clave), "adjuntos": b.db.adjuntos(clave),
                     "log": b.db.log_listar(clave, 100),
                     "borradores": {k: os.path.isdir(b.borrador_dir(clave, k)) for k in ("qa", "e2e")}}
            return self.enviar(200, limpiar(cfg, datos))
        m = re.match(r"^git/((?:task|bug)-%s)$" % wi.ID, sub)
        if m:
            return self.enviar(200, limpiar(cfg, b.git_estado(m.group(1), fetch=(q.get("fetch") or [""])[0] == "1")))
        m = re.match(r"^diff/((?:task|bug)-%s)$" % wi.ID, sub)
        if m:
            return self.enviar(200, limpiar(cfg, b.git_diff(m.group(1), (q.get("repo") or [""])[0],
                                                            (q.get("archivo") or [""])[0])))
        if sub == "log":
            return self.enviar(200, limpiar(cfg, b.db.log_listar(None, int((q.get("n") or ["300"])[0]))))
        if sub == "pruebas":
            d = os.path.join(cfg["raiz"], "test-results")
            lista = sorted((f for f in os.listdir(d) if f.endswith(".md")), reverse=True) if os.path.isdir(d) else []
            return self.enviar(200, lista)
        m = re.match(r"^prueba/([\w.\-]+\.md)$", sub)
        if m:
            path = os.path.join(cfg["raiz"], "test-results", m.group(1))
            if not os.path.isfile(path):
                return self.error(404, "no existe")
            return self.enviar(200, limpiar(cfg, {"nombre": m.group(1), "texto": open(path, encoding="utf-8").read()}))
        if sub == "archivo":
            return self.archivo(b, cfg, (q.get("ruta") or [""])[0], (q.get("base") or ["tablero"])[0])
        m = re.match(r"^trabajo/(\w+)$", sub)
        if m:
            t = TRABAJOS.get(m.group(1))
            if not t or t["proyecto"] != p["id"]:
                return self.error(404, "no existe")
            salida = open(t["salida"], encoding="utf-8", errors="replace").read()[-60000:] if os.path.exists(t["salida"]) else ""
            return self.enviar(200, limpiar(cfg, {"que": t["que"], "rc": t["proceso"].poll(), "salida": salida,
                                                  "inicio": t["inicio"]}))
        if sub == "trabajos":
            return self.enviar(200, [{"id": k, "que": t["que"], "rc": t["proceso"].poll(), "inicio": t["inicio"]}
                                     for k, t in TRABAJOS.items() if t["proyecto"] == p["id"]])
        return self.error(404, "no existe")

    def archivo(self, b, cfg, ruta, base):
        raiz = b.dir if base == "tablero" else os.path.join(cfg["raiz"], "test-results")
        path = os.path.realpath(os.path.join(raiz, ruta))
        if not path.startswith(os.path.realpath(raiz) + os.sep) or not os.path.isfile(path) \
                or os.path.basename(path).startswith(".env") or re.search(r"\.db(-wal|-shm|-journal)?$", path):
            return self.error(404, "no existe")
        tipo = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if tipo == "image/svg+xml":   # un SVG puede traer scripts: se sirve como descarga
            return self.enviar(200, open(path, "rb").read(), tipo, {"Content-Disposition": "attachment",
                                                                    "Content-Security-Policy": "script-src 'none'"})
        self.enviar_archivo(path, tipo)

    def enviar_archivo(self, path, tipo):
        """Sirve un archivo en trozos y acepta Range (206): sin eso Safari (iPhone/iPad) no reproduce
        videos y ningun navegador puede adelantar o retroceder."""
        total = os.path.getsize(path)
        ini, fin, codigo = 0, total - 1, 200
        m = re.match(r"^bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                ini = int(m.group(1))
                fin = min(int(m.group(2)), total - 1) if m.group(2) else total - 1
            else:                                   # bytes=-N: los ultimos N
                ini = max(0, total - int(m.group(2)))
            if ini > fin or ini >= total:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % total)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            codigo = 206
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(fin - ini + 1))
        self.send_header("Accept-Ranges", "bytes")
        if codigo == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (ini, fin, total))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(ini)
                falta = fin - ini + 1
                while falta > 0:
                    trozo = f.read(min(1 << 16, falta))
                    if not trozo:
                        break
                    self.wfile.write(trozo)
                    falta -= len(trozo)
        except (BrokenPipeError, ConnectionResetError):
            pass   # el navegador corto (adelanto el video o cerro el visor): normal

    # -- POST
    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path
        if self.headers.get("X-Autopilot") != "1":
            return self.error(403, "falta el encabezado X-Autopilot")
        try:
            if ruta == "/api/login":
                datos = self.cuerpo(10000)
                if not self.server.con_clave:
                    return self.enviar(200, {"ok": True})
                if hmac.compare_digest(str(datos.get("clave", "")), self.server.clave):
                    return self.enviar(200, {"ok": True}, extra={
                        "Set-Cookie": "ap_sesion=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000" % self.server.sesion})
                time.sleep(1)
                return self.error(401, "clave incorrecta")
            if not self.autorizado():
                return self.error(401, "falta la clave")
            m = re.match(r"^/api/p/(\w+)/(accion|crear|subir|correr|pausa|git)$", ruta)
            if not m:
                return self.error(404, "no existe")
            p = self.proyecto(m.group(1))
            return getattr(self, "post_" + m.group(2))(p, self.cuerpo())
        except KeyError:
            return self.error(404, "no existe")
        except (ValueError, wi.Error) as e:
            return self.error(400, str(e))

    def post_accion(self, p, d):
        accion, clave = d.get("accion"), str(d.get("clave", "")).lower()
        if accion not in ACCIONES or not wi.es_clave(clave):
            return self.error(400, "accion o tarea invalida")
        args = [ACCIONES[accion], clave]
        if accion in ("stop", "prioridad", "criterio", "descripcion", "titulo", "cambios"):
            texto = str(d.get("texto", "")).strip()
            if not texto:
                return self.error(400, "falta el texto")
            args.append(texto)
        ok, out = wi_cmd(p["env"], *args)
        if ok:
            wi_cmd(p["env"], "log", "App web: %s" % accion, "humano", "nota", clave, clave)
        return self.enviar(200 if ok else 400, {"ok": ok, "salida": out.replace("ERROR: ", "")})

    def post_git(self, p, d):
        """Merge / push / PR pedidos por el humano desde el panel Git. Responde el resultado por repo."""
        op, clave = d.get("op"), str(d.get("clave", "")).lower()
        if op not in GIT_OPS or not wi.es_clave(clave):
            return self.error(400, "operacion o tarea invalida")
        r = subprocess.run([sys.executable, os.path.join(KIT, "workitems.py"), p["env"]] +
                           [x.format(clave=clave) for x in GIT_OPS[op]], capture_output=True, text=True, timeout=600)
        cfg = board(p["env"]).cfg
        try:
            res = json.loads(r.stdout)
        except ValueError:
            return self.enviar(400, limpiar(cfg, {"ok": False, "salida": (r.stdout + r.stderr).strip().replace("ERROR: ", "")}))
        return self.enviar(200, limpiar(cfg, res))

    def post_crear(self, p, d):
        campos = [d.get(k, "") for k in ("tipo", "numero", "prioridad", "titulo", "descripcion", "criterio", "repo")]
        ok, out = wi_cmd(p["env"], "add-task", *campos)
        return self.enviar(200 if ok else 400, {"ok": ok, "salida": out.replace("ERROR: ", "")})

    def post_subir(self, p, d):
        clave = str(d.get("clave", "")).lower()
        if not wi.es_clave(clave):
            return self.error(400, "tarea invalida")
        tmp = os.path.join(wi.cache_kit("web-subidas"), secrets.token_hex(6))
        os.makedirs(tmp, exist_ok=True)
        rutas = []
        for a in d.get("archivos", [])[:20]:
            nombre = re.sub(r"[^\w.\-]", "_", os.path.basename(str(a.get("nombre", "archivo"))))[:120] or "archivo"
            if nombre.startswith(".env"):
                continue
            path = os.path.join(tmp, nombre)
            open(path, "wb").write(base64.b64decode(a.get("datos", "")))
            rutas.append(path)
        if not rutas:
            return self.error(400, "no hay archivos")
        ok, out = wi_cmd(p["env"], "adjuntar", clave, *rutas)
        for r in rutas:
            os.remove(r)
        os.rmdir(tmp)
        return self.enviar(200 if ok else 400, {"ok": ok, "salida": out})

    def post_pausa(self, p, d):
        b = board(p["env"])
        f = os.path.join(b.dir, ".pausa")
        if d.get("pausa"):
            open(f, "w").write(time.strftime("%Y-%m-%d %H:%M"))
        elif os.path.exists(f):
            os.remove(f)
        b.log("Pausa %s desde la app web" % ("puesta" if d.get("pausa") else "quitada"), "humano", "nota")
        return self.enviar(200, {"ok": True, "pausa": bool(d.get("pausa"))})

    def post_correr(self, p, d):
        que = d.get("que")
        clave = str(d.get("clave", "") or "").lower()
        filtro = d.get("filtro") if d.get("filtro") in ("--qa", "--e2e", "--web", "--android") else None
        kit = KIT
        if que == "health":
            cmd = [os.path.join(kit, "salud.py"), p["env"]] + ([clave] if clave else [])
        elif que == "run-tests":
            objetivo = clave if clave == "smoke" or wi.es_clave(clave) else "--all"
            cmd = [os.path.join(kit, "pruebas.py"), p["env"], objetivo] + ([filtro] if filtro else [])
        else:
            return self.error(400, "no se puede correr eso")
        if any(t["proyecto"] == p["id"] and t["que"] == que and t["proceso"].poll() is None for t in TRABAJOS.values()):
            return self.error(409, "ya hay un %s corriendo" % que)
        tid = secrets.token_hex(5)
        salida = os.path.join(wi.cache_kit("web-trabajos"), tid + ".log")
        os.makedirs(os.path.dirname(salida), exist_ok=True)
        proc = subprocess.Popen([sys.executable] + cmd, stdout=open(salida, "w"), stderr=subprocess.STDOUT,
                                cwd=os.path.dirname(p["env"]), start_new_session=True)
        TRABAJOS[tid] = {"proyecto": p["id"], "que": que, "proceso": proc, "salida": salida,
                         "inicio": time.strftime("%H:%M:%S")}
        return self.enviar(200, {"ok": True, "id": tid})


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "?"


def main(a):
    if "-h" in a or "--help" in a:
        print(__doc__)
        return 0
    lan = "--lan" in a
    puerto = int(a[a.index("--port") + 1]) if "--port" in a else 8765
    extra = [a[i + 1] for i, x in enumerate(a) if x == "--env" and i + 1 < len(a)]
    if not extra:   # si se corre dentro de un proyecto, ese primero
        for d in (os.getcwd(), os.path.dirname(os.getcwd())):
            if os.path.isfile(os.path.join(d, "autopilot.env")):
                extra.append(os.path.join(d, "autopilot.env"))
                wi.registrar_proyecto(extra[0])
                break
    srv = Servidor(("0.0.0.0" if lan else "127.0.0.1", puerto), Handler)
    srv.extra = extra
    srv.con_clave = lan
    srv.clave = clave_web() if lan else ""
    srv.sesion = hashlib.sha256(("ap:" + srv.clave).encode()).hexdigest()
    print("App web del autopilot: http://localhost:%d/" % puerto)
    if lan:
        print("En la red local:        http://%s:%d/   (clave en %s)" % (ip_local(), puerto, os.path.join(CONF, "web.env")))
        print("Aviso: va sin HTTPS; usala solo en redes de confianza.")
    print("Proyectos: %s" % (", ".join(p["nombre"] for p in proyectos(extra)) or "ninguno (corre /autopilot-init)"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
