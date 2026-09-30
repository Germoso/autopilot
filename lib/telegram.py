#!/usr/bin/env python3
"""
telegram.py — el autopilot por Telegram: avisos y responder desde Telegram.

Se activa con TELEGRAM=true en autopilot.env (TELEGRAM_ALERTS_ONLY=true: solo lo que necesita tu
intervencion). Usa un bot PROPIO del autopilot (no el del plugin de Claude Code: Telegram deja un solo
lector por bot). Credenciales en ~/.config/autopilot-kit/telegram.env (TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID, permiso 600); se crean con `setup`.

Salida: enviar(cfg, texto, alerta) — nunca bloquea (manda en segundo plano), filtra secretos (valores
de los .env y de cuentas-e2e.env) y no repite el mismo mensaje en 10 minutos.
Entrada: el watcher llama `poll` en cada vuelta. Solo acepta mensajes de TELEGRAM_CHAT_ID.
  /estado /cola /tarea <clave> /health /ayuda            consultar (sin IA)
  /reqa /re-e2e /stop <clave> <motivo> /reviewed <clave>  actuar sobre tareas (via wi.sh)
  /pausa /seguir                                          dejar de tomar tareas nuevas / volver
  texto libre                                             al orquestador (evento `mensajes` del watcher)

uso: telegram.py <autopilot.env> send "<texto>" [--alert]    manda un aviso (respeta TELEGRAM)
     telegram.py <autopilot.env> test                         mensaje de prueba (aunque TELEGRAM=false)
     telegram.py <autopilot.env> setup                        crea las credenciales (interactivo)
     telegram.py <autopilot.env> poll                         lee mensajes nuevos (JSON: texto libre)
     telegram.py <autopilot.env> check                        estado para el health check (JSON)
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import entorno  # noqa: E402
import workitems as wi  # noqa: E402

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autopilot-kit")
CREDENCIALES = os.path.join(CONFIG, "telegram.env")
DEDUP_SEG = 600
AYUDA = ("Comandos:\n"
         "/estado — que hace cada agente y la cola\n"
         "/cola — tareas por estado\n"
         "/tarea <clave> — estado, motivo y ultima nota\n"
         "/health — health check E2E resumido\n"
         "/reqa <clave> — devolver a QA\n"
         "/re-e2e <clave> — devolver a E2E\n"
         "/stop <clave> <motivo> — detener una tarea\n"
         "/reviewed <clave> — marcar como revisada (desde done)\n"
         "/pausa — no tomar tareas nuevas · /seguir — volver a tomarlas\n"
         "Texto libre: se lo paso al orquestador (si /autopilot esta corriendo).")


# ----------------------------------------------------------------- credenciales y API
def credenciales():
    c = entorno.leer(CREDENCIALES)
    return c.get("TELEGRAM_BOT_TOKEN", ""), c.get("TELEGRAM_CHAT_ID", "")


def api(token, metodo, params=None, timeout=15):
    data = urllib.parse.urlencode(params or {}).encode()
    base = os.environ.get("AUTOPILOT_TELEGRAM_API", "https://api.telegram.org")   # solo para pruebas
    req = urllib.request.Request("%s/bot%s/%s" % (base, token, metodo), data=data)
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"ok": False, "error_code": e.code, "description": str(e)}


def proyecto(cfg):
    return os.path.basename(cfg["raiz"].rstrip("/")) or "autopilot"


def secretos(cfg):
    """Valores que nunca pueden salir en un mensaje: los de todos los .env* de los repos y las cuentas."""
    vals = set()
    for r in cfg["repos"].values():
        if os.path.isdir(r["path"]):
            for n in os.listdir(r["path"]):
                if n.startswith(".env") and not n.endswith((".example", ".sample", ".template")):
                    vals |= {v for v in entorno.leer(os.path.join(r["path"], n)).values() if len(v) >= 6}
    for n in ("cuentas-e2e.env", ".env.autopilot.e2e"):
        vals |= {v for v in entorno.leer(os.path.join(cfg["raiz"], n)).values() if len(v) >= 6}
    vals.add(credenciales()[0])
    return sorted((v for v in vals if v), key=len, reverse=True)


def limpiar(cfg, texto):
    for v in secretos(cfg):
        texto = texto.replace(v, "***")
    return texto[:3900]


# ----------------------------------------------------------------- salida
def enviar(cfg, texto, alerta=False, forzar=False, dedup=False):
    """Manda un aviso sin bloquear. Nunca lanza excepciones: un aviso que falla no rompe nada."""
    try:
        t = cfg.get("telegram", {})
        if not forzar and (not t.get("activo") or (t.get("solo_alertas") and not alerta)):
            return False
        token, chat = credenciales()
        if not token or not chat:
            return False
        texto = "%s[%s] %s" % ("🚨 " if alerta and not texto.startswith("🚨") else "", proyecto(cfg), limpiar(cfg, texto))
        if dedup and not forzar and repetido(texto):   # solo para avisos que se pueden repetir (vigia, arranque)
            return False
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "-", "_enviar"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        p.stdin.write(texto.encode())
        p.stdin.close()                     # no se espera: el hijo manda solo (con reintentos)
        return True
    except Exception:
        return False


def repetido(texto):
    path = wi.cache_kit("telegram-dedup.json")
    h = hashlib.sha1(texto.encode()).hexdigest()
    ahora = time.time()
    try:
        d = json.load(open(path))
    except (OSError, ValueError):
        d = {}
    d = {k: v for k, v in d.items() if ahora - v < DEDUP_SEG}
    if h in d:
        return True
    d[h] = ahora
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wi.escribir_atomico(path, json.dumps(d))
    return False


def _enviar_ahora(texto):
    token, chat = credenciales()
    for _ in range(3):
        r = api(token, "sendMessage", {"chat_id": chat, "text": texto, "disable_web_page_preview": "true"})
        if r.get("ok"):
            return True
        time.sleep(3)
    return False


def responder(cfg, texto):
    """Respuesta inmediata a un mensaje (sin dedup ni filtro de alertas, pero con secretos filtrados)."""
    token, chat = credenciales()
    return api(token, "sendMessage", {"chat_id": chat, "text": limpiar(cfg, texto)[:3900],
                                      "disable_web_page_preview": "true"}).get("ok", False)


# ----------------------------------------------------------------- entrada
def poll(env_path):
    """Lee mensajes nuevos del bot. Resuelve los comandos y devuelve el texto libre (para el orquestador)."""
    cfg = wi.cargar_config(env_path)
    if not cfg["telegram"]["activo"]:
        return []
    token, chat = credenciales()
    if not token or not chat:
        return []
    bot = hashlib.sha1(token.encode()).hexdigest()[:10]
    os.makedirs(wi.cache_kit(), exist_ok=True)
    lk = open(wi.cache_kit("telegram-%s.lock" % bot), "w")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)   # un solo lector por bot
    except OSError:
        return []
    off_path = wi.cache_kit("telegram-%s.offset" % bot)
    try:
        offset = int(open(off_path).read())
    except (OSError, ValueError):
        offset = 0
    r = api(token, "getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": '["message"]'}, timeout=20)
    if not r.get("ok"):
        return []
    libres = []
    b = wi.Board(cfg)
    for u in r.get("result", []):
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message") or {}
        texto = (m.get("text") or "").strip()
        if str((m.get("chat") or {}).get("id")) != str(chat):
            b.log("Telegram: mensaje de un chat no autorizado (ignorado)", "telegram", "nota")
            continue
        if not texto:
            continue
        if texto.startswith("/"):
            try:
                resp = comando(cfg, env_path, texto)
            except Exception as e:
                resp = "❌ %s" % e
            responder(cfg, resp)
        else:
            libres.append({"texto": texto, "fecha": m.get("date")})
            responder(cfg, "📨 Recibido. Se lo paso al orquestador; te respondo por aqui.")
    wi.escribir_atomico(off_path, str(offset))
    return libres


def wi_cmd(env_path, *args):
    r = subprocess.run([sys.executable, os.path.join(AQUI, "workitems.py"), env_path] + list(args),
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def comando(cfg, env_path, texto):
    partes = texto.split()
    cmd = partes[0].split("@")[0].lower()
    args = partes[1:]
    b = wi.Board(cfg)
    clave = args[0].lower() if args else ""
    if cmd in ("/start", "/ayuda", "/help"):
        return AYUDA
    if cmd == "/estado":
        p = b.plan()
        oc = p["ocupados"]
        lineas = ["%s: %s" % (k, ", ".join(v) or "libre") for k, v in oc.items() if k != "e2e" or p.get("e2e")]
        c = p["cola"]
        lineas.append("cola: bug-fix %d · new %d · qa %d%s" % (c["bugfix"], c["new"], c["qa"],
                                                              " · e2e %d" % c["e2e"] if p.get("e2e") else ""))
        lineas.append("stopped: %s" % (", ".join(p["stopped"]) or "ninguna"))
        if os.path.exists(os.path.join(b.dir, ".pausa")):
            lineas.append("⏸️ en pausa: no toma tareas nuevas (/seguir)")
        return "📊 Estado\n" + "\n".join(lineas)
    if cmd == "/cola":
        por = {}
        for t in b.todas():
            por.setdefault(t["estado"], []).append(t["id"])
        return "📋 Cola\n" + "\n".join("%s: %s" % (e, ", ".join(v)) for e, v in por.items() if e != "reviewed") or "vacia"
    if cmd == "/tarea":
        if not clave:
            return "uso: /tarea <clave>"
        estado, _, meta, titulo, secs = b.leer(clave)
        ultimo = lambda s: (re.split(r"(?m)^### ", secs.get(s, ""))[-1].strip()[:500]) if secs.get(s) else ""
        out = ["📄 %s — %s" % (clave, titulo), "estado: %s · intento %s" % (estado, meta.get("intento", "0"))]
        for sec in ("Motivo de stopped", "Resultado", "Feedback de E2E", "Feedback de QA"):
            if secs.get(sec, "").strip():
                out.append("%s:\n%s" % (sec, ultimo(sec)))
                break
        return "\n".join(out)
    if cmd == "/health":
        import salud
        items = salud.Salud(env_path).correr()
        malos = [i for i in items if i["nivel"] != "ok"]
        e = sum(1 for i in items if i["nivel"] == "error")
        out = ["🩺 Health check: %s" % ("❌ %d bloquean" % e if e else "✅ listo")]
        out += ["%s %s%s" % ("❌" if i["nivel"] == "error" else "⚠️", i["mensaje"][:200],
                             ("\n   → " + i["solucion"][:150]) if i["solucion"] else "") for i in malos[:10]]
        return "\n".join(out)
    if cmd == "/pausa":
        open(os.path.join(b.dir, ".pausa"), "w").write(time.strftime("%Y-%m-%d %H:%M"))
        b.log("Pausa pedida por Telegram", "telegram", "nota")
        return "⏸️ Pausado: no se toman tareas nuevas. Lo que esta en curso termina. /seguir para volver."
    if cmd == "/seguir":
        try:
            os.remove(os.path.join(b.dir, ".pausa"))
        except OSError:
            pass
        b.log("Pausa quitada por Telegram", "telegram", "nota")
        return "▶️ Seguimos: se vuelven a tomar tareas."
    acciones = {"/reqa": "reqa", "/re-e2e": "re-e2e", "/reviewed": "reviewed", "/stop": "stopped"}
    if cmd in acciones:
        if not clave:
            return "uso: %s <clave>%s" % (cmd, " <motivo>" if cmd == "/stop" else "")
        extra = [" ".join(args[1:]) or "Detenida desde Telegram"] if cmd == "/stop" else []
        ok, out = wi_cmd(env_path, acciones[cmd], clave, *extra)
        b.log("Telegram: %s" % texto[:80], "telegram", "nota", clave, clave)
        return ("✅ %s %s" % (cmd, clave)) if ok else ("❌ %s" % out.replace("ERROR: ", "")[:500])
    return "No conozco %s.\n\n%s" % (cmd, AYUDA)


# ----------------------------------------------------------------- setup y check
def setup(env_path):
    import getpass
    print("1) En Telegram, habla con @BotFather: /newbot, ponle un nombre (p. ej. 'Autopilot %s')."
          % os.path.basename(os.path.dirname(os.path.abspath(env_path))))
    token = getpass.getpass("2) Pega aqui el token que te dio (no se muestra): ").strip()
    me = api(token, "getMe")
    if not me.get("ok"):
        print("❌ Ese token no es valido: %s" % me.get("description", ""))
        return 1
    usuario = me["result"].get("username")
    print("3) Abre https://t.me/%s y mandale /start (espero hasta 3 minutos)..." % usuario)
    fin, chat, off = time.time() + 180, None, 0
    while time.time() < fin and not chat:
        r = api(token, "getUpdates", {"offset": off, "timeout": 20}, timeout=30)
        if r.get("error_code") == 409:
            print("❌ Otro programa ya lee los mensajes de este bot (¿es el del plugin de Claude Code?). Crea uno nuevo.")
            return 1
        for u in r.get("result", []):
            off = u["update_id"] + 1
            c = ((u.get("message") or {}).get("chat") or {}).get("id")
            if c:
                chat = str(c)
    if not chat:
        print("❌ No llego ningun mensaje. Vuelve a intentarlo.")
        return 1
    os.makedirs(CONFIG, exist_ok=True)
    os.chmod(CONFIG, 0o700)
    fd = os.open(CREDENCIALES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n" % (token, chat))
    api(token, "getUpdates", {"offset": off, "timeout": 0})   # descarta el /start
    api(token, "sendMessage", {"chat_id": chat, "text": "✅ Autopilot conectado. Te aviso por aqui.\n\n" + AYUDA})
    print("✅ Listo: @%s conectado a tu chat. Credenciales en %s (600). Activa TELEGRAM=true en autopilot.env."
          % (usuario, CREDENCIALES))
    return 0


def check(cfg):
    """Para el health check: (nivel, mensaje, solucion)."""
    out = []
    token, chat = credenciales()
    if not token or not chat:
        return [("error", "TELEGRAM=true pero no hay credenciales (%s)" % CREDENCIALES,
                 "wi.sh autopilot.env telegram-setup (en tu terminal)")]
    modo = os.stat(CREDENCIALES).st_mode & 0o777
    if modo & 0o077:
        out.append(("aviso", "%s tiene permisos %o: cualquiera en la maquina puede leer el token" % (CREDENCIALES, modo),
                    "chmod 600 %s" % CREDENCIALES))
    me = api(token, "getMe", timeout=10)
    if not me.get("ok"):
        return out + [("error", "el token del bot no es valido o no hay red (%s)" % me.get("description", "sin respuesta"),
                       "wi.sh autopilot.env telegram-setup")]
    r = api(token, "getUpdates", {"timeout": 0, "limit": 1, "offset": -1}, timeout=10)
    if r.get("error_code") == 409:
        out.append(("error", "otro programa lee los mensajes de @%s (¿el bot del plugin de Claude Code?)"
                    % me["result"]["username"], "crea un bot propio para el autopilot: wi.sh autopilot.env telegram-setup"))
    else:
        out.append(("ok", "Telegram: @%s conectado a tu chat%s" % (me["result"]["username"],
                    " (solo alertas)" if cfg["telegram"]["solo_alertas"] else ""), ""))
    return out


def main(a):
    if len(a) < 2 or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[1] == "_enviar":                   # proceso hijo de enviar(): texto por stdin
        return 0 if _enviar_ahora(sys.stdin.read()) else 1
    env_path, cmd = a[0], a[1]
    if cmd == "setup":
        return setup(env_path)
    cfg = wi.cargar_config(env_path)
    if cmd == "send":
        texto = " ".join(x for x in a[2:] if x != "--alert") or sys.stdin.read()
        return 0 if enviar(cfg, texto, "--alert" in a) else 1
    if cmd == "test":
        ok = enviar(cfg, "🔔 Prueba: el autopilot puede avisarte por aqui.", forzar=True)
        print("enviado" if ok else "no se pudo enviar (credenciales: %s)" % CREDENCIALES)
        return 0 if ok else 1
    if cmd == "poll":
        print(json.dumps(poll(env_path), ensure_ascii=False))
        return 0
    if cmd == "check":
        print(json.dumps(check(cfg), ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
