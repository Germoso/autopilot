#!/usr/bin/env python3
"""
e2e.py — Herramientas del agente e2e-tester (se usa via e2e.sh). Nunca contra produccion.

El agente E2E recorre el flujo real (app/BackOffice -> backend -> base de datos) en SUS copias
(~/.cache/autopilot-kit/e2e/<repo>-<clave>). Los backends corren LOCALES con aenv.sh --e2e
(.env.autopilot.e2e si el humano lo creo; si no, .env.autopilot: la base de QA). Las apps se apuntan
a ese backend local:

  api <worktree> <web|android> [<backend>]
        Aplica E2E_API.<repo> (autopilot.env) en la copia E2E de una app Flutter: reemplaza la linea
        de la URL del API por http://localhost:<PORT> (web) o http://10.0.2.2:<PORT> (android, el
        localhost de la maquina visto desde el emulador). <PORT> sale del ambiente E2E del backend
        (.env.autopilot.e2e o .env.autopilot; si no lo define, el .env del repo). Backend: E2E_CLIENTS. El agente no elige la URL: solo puede ser local.
  app <worktree> -- <comando>
        Corre flutter (build, drive, test, install...) en la copia E2E SOLO si el override de la API
        sigue aplicado y es local (si alguien edito ese archivo despues, no corre).
  servir <carpeta>              sirve un build web (p. ej. <worktree>/build/web) en 127.0.0.1:<puerto libre>
  web <worktree> <spec> [--project web-movil|web-escritorio] [args de playwright...]
        Playwright (Chromium) con la config del kit: capturas y video siempre, y el navegador NO
        resuelve ningun host salvo localhost y los CDN estaticos de fuentes de Google: una llamada a
        cualquier otro servidor (p. ej. produccion) falla y queda en red-bloqueada.txt.
  emulador arrancar <worktree> | parar <serial> | estado
        Un emulador Android headless por tarea (AVD autopilot_e2e, -read-only: arranca limpio y no
        guarda nada), SIN DNS: la app solo alcanza 10.0.2.2 (el backend local). Arranca dentro de la
        copia E2E: el vigia lo termina si la tarea deja de estar en probando-e2e.
  adb <args...>                 adb del kit (capturas: adb -s <serial> exec-out screencap -p > x.png)
  cuentas <worktree>            cuentas de prueba (E2E_*) de cuentas-e2e.env, junto a autopilot.env
  doctor                        herramientas E2E (JSON)

Herramientas en ~/.local/share/autopilot-e2e (AUTOPILOT_E2E_HOME), las instala e2e-setup.sh.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import entorno  # noqa: E402
import workitems as wi  # noqa: E402

E2E_HOME = os.path.expanduser(os.environ.get("AUTOPILOT_E2E_HOME") or "~/.local/share/autopilot-e2e")
SDK = os.path.join(E2E_HOME, "android-sdk")
JDK = os.path.join(E2E_HOME, "jdk")
AVD_HOME = os.path.join(E2E_HOME, "avd")
AVD = "autopilot_e2e"
NODE_MODULES = os.path.join(E2E_HOME, "node", "node_modules")
ARCHIVO_CUENTAS = "cuentas-e2e.env"   # junto a autopilot.env; lo crea el humano (secretos, fuera de git)
HOSTS_LOCALES = ("localhost", "127.0.0.1", "10.0.2.2")
DNS_MUERTO = "127.0.0.2"   # loopback donde no escucha nadie: el emulador no resuelve ningun nombre


class Error(Exception):
    pass


# ----------------------------------------------------------------- utilidades
def tipo_repo(path):
    """flutter | backend | web | otro."""
    if os.path.isfile(os.path.join(path, "pubspec.yaml")):
        return "flutter"
    try:
        pkg = json.load(open(os.path.join(path, "package.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return "otro"
    deps = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    if deps & {"react", "react-dom", "vue", "@angular/core", "svelte", "next", "vite"}:
        return "web"
    if deps & {"@nestjs/core", "express", "fastify", "koa", "@hapi/hapi"}:
        return "backend"
    return "otro"


def env_herramientas():
    """Entorno con Java, Android SDK y el AVD del kit (sin tocar la config global del usuario)."""
    env = dict(os.environ)
    env.update({"JAVA_HOME": JDK, "ANDROID_HOME": SDK, "ANDROID_SDK_ROOT": SDK, "ANDROID_AVD_HOME": AVD_HOME,
                "GRADLE_OPTS": (env.get("GRADLE_OPTS", "") + " -Dorg.gradle.daemon=false").strip(),
                "NODE_PATH": NODE_MODULES, "E2E_NODE_MODULES": NODE_MODULES,
                "E2E_PASOS": os.path.join(AQUI, "e2e-pasos.cjs")})
    env["PATH"] = os.pathsep.join([os.path.join(JDK, "bin"), os.path.join(SDK, "platform-tools"),
                                   os.path.join(SDK, "emulator"), os.path.join(SDK, "cmdline-tools", "latest", "bin"),
                                   env.get("PATH", "")])
    return env


def herramientas_faltantes():
    faltan = []
    if not os.access(os.path.join(JDK, "bin", "java"), os.X_OK):
        faltan.append("Java 17")
    if not os.access(os.path.join(SDK, "platform-tools", "adb"), os.X_OK):
        faltan.append("adb")
    if not os.access(os.path.join(SDK, "emulator", "emulator"), os.X_OK):
        faltan.append("emulador Android")
    if not os.path.isfile(os.path.join(AVD_HOME, AVD + ".ini")):
        faltan.append("AVD %s" % AVD)
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        faltan.append("acceso a /dev/kvm (sudo usermod -aG kvm $USER y cerrar sesion)")
    if not os.path.isdir(os.path.join(NODE_MODULES, "@playwright", "test")):
        faltan.append("Playwright")
    navegadores = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser("~/.cache/ms-playwright")
    if not any(n.startswith("chromium") for n in (os.listdir(navegadores) if os.path.isdir(navegadores) else [])):
        faltan.append("Chromium de Playwright")
    return faltan


def config_de(path):
    """autopilot.env del repo (o de su carpeta padre, en un workspace) de una copia de trabajo."""
    repo = entorno.repo_principal(path)
    for env in (os.path.join(repo, "autopilot.env"), os.path.join(os.path.dirname(repo), "autopilot.env")):
        if os.path.isfile(env):
            return wi.cargar_config(env)
    raise Error("no encuentro el autopilot.env de %s" % path)


def cuentas(cfg):
    """Variables E2E_* de cuentas-e2e.env (junto a autopilot.env). Compatibilidad: si no existe, el
    .env.autopilot.e2e de esa carpeta (donde iban antes)."""
    path = os.path.join(cfg["raiz"], ARCHIVO_CUENTAS)
    if not os.path.isfile(path):
        path = os.path.join(cfg["raiz"], entorno.ARCHIVO_E2E)
    return {k: v for k, v in entorno.leer(path).items() if k.startswith("E2E_") and v}


def worktree_e2e(path):
    """(raiz del worktree, repo, clave) si path esta dentro de una copia E2E del kit."""
    real = os.path.realpath(os.path.expanduser(path))
    raiz = os.path.realpath(wi.cache_kit("e2e")) + os.sep
    if not real.startswith(raiz):
        raise Error("%s no es una copia E2E (%s<repo>-<clave>). Pidela con wi.sh e2e-worktree <clave>" % (path, raiz))
    nombre = real[len(raiz):].split(os.sep)[0]
    m = wi.RE_WT.match(nombre)
    if not m:
        raise Error("%s no es una copia E2E valida" % path)
    return raiz + nombre, m.group("repo"), m.group("clave")


def marca(wt):
    return wi.cache_kit("e2e", ".api", os.path.basename(wt) + ".json")


def olvidar_api(wt):
    try:
        os.remove(marca(wt))
    except OSError:
        pass


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def puerto_backend(repo):
    """PORT del backend: el de su ambiente E2E y, si no lo define, el de sus .env (no es un secreto)."""
    candidatos = [entorno.archivo_e2e(repo), ".env.local", ".env"]
    for n in candidatos:
        p = entorno.leer(os.path.join(repo, n)).get("PORT", "").strip()
        if p.isdigit():
            return p
    return None


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def url_local(url):
    m = re.match(r"^https?://([^/:]+)", url)
    return bool(m) and m.group(1) in HOSTS_LOCALES


# ----------------------------------------------------------------- API de la app
def aplicar_api(path, plataforma, backend=None):
    wt, repo, clave = worktree_e2e(path)
    if plataforma not in ("web", "android"):
        raise Error("plataforma invalida: %s (web|android)" % plataforma)
    if tipo_repo(wt) != "flutter":
        raise Error("e2e.sh api es para apps Flutter (%s es %s). Un front web se apunta solo al backend local "
                    "al levantarlo con aenv.sh --e2e (E2E_API.%s=env:<variables>)" % (repo, tipo_repo(wt), repo))
    cfg = config_de(wt)
    api = cfg["e2e"]["api"].get(repo)
    if not api or "invalido" in api or "env" in api:
        raise Error("falta E2E_API.%s en autopilot.env (<archivo>|<regex de la linea>|<reemplazo con {API}>). "
                    "Sin eso no se puede apuntar la app al backend local: NO CERTIFICABLE" % repo)
    backs = [be for be, fs in cfg["e2e"]["clients"].items() if repo in fs]
    if backend:
        if backend not in backs:
            raise Error("%s no es backend de %s segun E2E_CLIENTS (%s)" % (backend, repo, ", ".join(backs) or "ninguno"))
        backs = [backend]
    if len(backs) != 1:
        raise Error("no se de que backend es %s: %s. Define E2E_CLIENTS.<backend>=%s o pasalo como tercer argumento"
                    % (repo, ", ".join(backs) or "ninguno en E2E_CLIENTS", repo))
    be, puerto = backend_local(cfg, backs[0])
    url = "http://%s:%s" % ("localhost" if plataforma == "web" else "10.0.2.2", puerto)
    return _aplicar_linea(wt, repo, api, url, plataforma, backs[0])


def backend_local(cfg, nombre):
    """(repo, puerto) del backend que el E2E levanta en local; valida su ambiente."""
    be = cfg["repos"].get(nombre)
    if not be:
        raise Error("el backend %s no esta en autopilot.env (REPO.%s)" % (nombre, nombre))
    backs = [nombre]
    archivo_env = entorno.archivo_e2e(be["path"])
    v = entorno.validar(be["path"], archivo_env)
    if v["estado"] != "ok":
        raise Error("%s de %s: %s. %s" % (archivo_env, backs[0], v["estado"], v.get("recomendacion", "")))
    puerto = puerto_backend(be["path"])
    if not puerto:
        raise Error("no se en que puerto corre %s: define PORT en su %s" % (backs[0], archivo_env))
    return be, puerto


def _aplicar_linea(wt, repo, api, url, plataforma, backend):
    archivo = os.path.join(wt, api["archivo"])
    if not os.path.isfile(archivo):
        raise Error("E2E_API.%s: no existe %s" % (repo, api["archivo"]))
    texto = open(archivo, encoding="utf-8").read()
    patron = re.compile(api["regex"], re.M)
    hits = patron.findall(texto)
    if len(hits) != 1:
        raise Error("E2E_API.%s: la regex encuentra %d lineas en %s (debe ser exactamente 1)" % (repo, len(hits), api["archivo"]))
    if "{API}" not in api["reemplazo"]:
        raise Error("E2E_API.%s: el reemplazo debe contener {API} (donde va la URL del backend local)" % repo)
    linea = api["reemplazo"].replace("{API}", url)
    nuevo = patron.sub(lambda m: linea, texto)
    for u in re.findall(r"https?://[^\s'\"]+", linea):
        if not url_local(u):
            raise Error("el reemplazo de E2E_API.%s deja una URL que no es local (%s): no se aplica" % (repo, u))
    open(archivo, "w", encoding="utf-8").write(nuevo)
    os.makedirs(os.path.dirname(marca(wt)), exist_ok=True)
    wi.escribir_atomico(marca(wt), json.dumps({"archivo": archivo, "sha": sha(archivo), "url": url,
                                                "plataforma": plataforma, "backend": backend}))
    return {"repo": repo, "archivo": api["archivo"], "url": url, "plataforma": plataforma, "backend": backend,
            "linea": linea,
            "nota": "cambio TEMPORAL solo en la copia E2E (nunca se commitea). Levanta %s con: "
                    "aenv.sh --e2e <su copia E2E> -- <comando de arranque>" % backend}


def url_a_local(valor, puerto):
    """Misma URL (ruta, query) pero en localhost:<puerto>; https->http y wss->ws (el backend local no usa TLS)."""
    from urllib.parse import urlsplit, urlunsplit
    u = urlsplit(valor)
    esquema = {"https": "http", "wss": "ws"}.get(u.scheme, u.scheme or "http")
    return urlunsplit((esquema, "localhost:%s" % puerto, u.path, u.query, u.fragment))


def web_env(path):
    """Para aenv.sh --e2e en un front web con E2E_API.<repo>=env:VARS: {VAR: URL al backend local}."""
    try:
        wt, repo, clave = worktree_e2e(path)
    except Error:
        return {}
    cfg = config_de(wt)
    api = cfg["e2e"]["api"].get(repo) or {}
    if "env" not in api:
        return {}
    backs = [be for be, fs in cfg["e2e"]["clients"].items() if repo in fs]
    if len(backs) != 1:
        raise Error("no se de que backend es %s (E2E_CLIENTS): %s" % (repo, ", ".join(backs) or "ninguno"))
    _, puerto = backend_local(cfg, backs[0])
    vals = entorno.leer(os.path.join(entorno.repo_principal(wt), entorno.archivo_e2e(wt)))
    return {var: url_a_local(vals.get(var) or "http://localhost/", puerto) for var in api["env"]}


def verificar_api(wt):
    try:
        m = json.load(open(marca(wt)))
    except (OSError, ValueError):
        raise Error("la app no esta apuntada al backend local. Primero: e2e.sh api %s <web|android>" % wt)
    if not os.path.isfile(m["archivo"]) or sha(m["archivo"]) != m["sha"]:
        raise Error("%s cambio despues de apuntarlo al backend local: no se ejecuta. Vuelve a correr "
                    "e2e.sh api %s %s (y no edites ese archivo)" % (m["archivo"], wt, m["plataforma"]))
    if not url_local(m["url"]):
        raise Error("la URL aplicada no es local: %s" % m["url"])
    return m


def cfg_timeout(wt):
    try:
        return config_de(wt)["e2e"]["timeout"]
    except Exception:
        return 2400


def app(path, cmd):
    wt, repo, clave = worktree_e2e(path)
    if tipo_repo(wt) != "flutter":
        raise Error("e2e.sh app es para apps Flutter. Un backend o un front web se levanta con "
                    "aenv.sh --e2e <copia E2E> -- <comando>")
    prog = os.path.basename(cmd[0]) if cmd else ""
    if prog not in ("flutter", "fvm", "dart"):
        raise Error("e2e.sh app solo corre flutter / fvm flutter / dart (recibi: %s)" % (prog or "nada"))
    m = verificar_api(wt)
    print("e2e: %s apunta a %s (%s)" % (repo, m["url"], m["plataforma"]), file=sys.stderr)
    env = env_herramientas()
    env["E2E_CAPTURAS"] = os.path.join(wt, ".e2e-capturas", "android")
    os.makedirs(env["E2E_CAPTURAS"], exist_ok=True)
    os.chdir(wt)
    os.execvpe("timeout", ["timeout", "--kill-after=30", str(cfg_timeout(wt))] + cmd, env)


# ----------------------------------------------------------------- web
def servir(carpeta):
    real = os.path.realpath(carpeta)
    worktree_e2e(real)
    if not os.path.isfile(os.path.join(real, "index.html")):
        raise Error("%s no tiene index.html (compila antes: e2e.sh app <wt> -- fvm flutter build web ...)" % carpeta)
    p = puerto_libre()
    subprocess.Popen(["timeout", str(cfg_timeout(real)), sys.executable, "-m", "http.server", str(p),
                      "--bind", "127.0.0.1", "--directory", real], cwd=real, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % p, timeout=1)
            return {"url": "http://localhost:%d/" % p}
        except OSError:
            time.sleep(0.2)
    raise Error("el servidor web no respondio")


def web(path, spec, extra):
    wt, repo, clave = worktree_e2e(path)
    spec = os.path.realpath(spec if os.path.isabs(spec) else os.path.join(wt, spec))
    if not spec.startswith(wt + os.sep) or not os.path.exists(spec):
        raise Error("la prueba %s debe existir dentro de la copia E2E %s" % (spec, wt))
    cli = os.path.join(NODE_MODULES, "@playwright", "test", "cli.js")
    if not os.path.isfile(cli):
        raise Error("falta Playwright: corre e2e-setup.sh")
    env = env_herramientas()
    env["E2E_SPEC"] = spec
    env["E2E_SALIDA"] = os.path.join(wt, ".e2e-capturas", "web")
    os.makedirs(env["E2E_SALIDA"], exist_ok=True)
    os.chdir(wt)
    os.execvpe("timeout", ["timeout", "--kill-after=30", str(cfg_timeout(wt)), "node", cli, "test",
                           "--config", os.path.join(AQUI, "e2e-playwright.config.cjs")] + extra, env)


# ----------------------------------------------------------------- emulador
def adb(*args, timeout=60):
    return subprocess.run([os.path.join(SDK, "platform-tools", "adb")] + list(args), capture_output=True,
                          text=True, timeout=timeout, env=env_herramientas())


def emuladores():
    out = adb("devices").stdout.splitlines()[1:]
    return [l.split()[0] for l in out if l.startswith("emulator-")]


def emulador_arrancar(path):
    wt, repo, clave = worktree_e2e(path)
    falta = [f for f in herramientas_faltantes() if f not in ("Playwright", "Chromium de Playwright")]
    if falta:
        raise Error("faltan herramientas: %s. Corre ~/.local/share/autopilot-kit/e2e-setup.sh" % ", ".join(falta))
    usados = set(emuladores())
    puerto = next((p for p in range(5554, 5586, 2) if "emulator-%d" % p not in usados), None)
    if not puerto:
        raise Error("no hay puertos libres para otro emulador")
    serial = "emulator-%d" % puerto
    logs = wi.cache_kit("e2e", ".logs")
    os.makedirs(logs, exist_ok=True)
    log = open(os.path.join(logs, "%s-%s.log" % (clave, serial)), "w")
    # cwd = la copia E2E: asi el vigia sabe de que tarea es y lo termina si queda huerfano.
    subprocess.Popen([os.path.join(SDK, "emulator", "emulator"), "-avd", AVD, "-read-only", "-no-window",
                      "-no-audio", "-no-boot-anim", "-no-snapshot", "-gpu", "swiftshader_indirect",
                      "-memory", "2048", "-port", str(puerto), "-dns-server", DNS_MUERTO],
                     cwd=wt, env=env_herramientas(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    fin = time.time() + 420
    while time.time() < fin:
        r = adb("-s", serial, "shell", "getprop", "sys.boot_completed", timeout=20)
        if r.stdout.strip() == "1":
            break
        time.sleep(3)
    else:
        emulador_parar(serial)
        raise Error("el emulador no termino de arrancar en 7 min (log: %s)" % log.name)
    for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        adb("-s", serial, "shell", "settings", "put", "global", k, "0")
    # Sin DNS: ningun nombre resuelve. La app solo llega a 10.0.2.2 (el backend local).
    r = adb("-s", serial, "shell", "ping", "-c", "1", "-W", "3", "google.com", timeout=30)
    if "unknown host" not in (r.stdout + r.stderr).lower() and r.returncode == 0:
        emulador_parar(serial)
        raise Error("el emulador resuelve nombres de internet: no es seguro (podria llegar a produccion)")
    return {"serial": serial, "red": "sin DNS: solo alcanza 10.0.2.2 (localhost de esta maquina)",
            "log": log.name, "capturas": "e2e.sh adb -s %s exec-out screencap -p > <archivo>.png" % serial}


def emulador_parar(serial):
    adb("-s", serial, "emu", "kill", timeout=30)
    puerto = serial.split("-")[-1]
    fin = time.time() + 30
    while time.time() < fin and serial in emuladores():
        time.sleep(1)
    subprocess.run(["pkill", "-f", "emulator.*-port %s " % puerto], capture_output=True)
    subprocess.run(["pkill", "-f", "qemu-system.*-port %s " % puerto], capture_output=True)
    return {"parado": serial}


# ----------------------------------------------------------------- CLI
def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, r = a[0], a[1:]
    out = None
    if cmd == "web-env" and r:
        for k, v in web_env(r[0]).items():
            sys.stdout.write("%s\0%s\0" % (k, v))
        return 0
    elif cmd == "doctor":
        out = {"home": E2E_HOME, "faltan": herramientas_faltantes()}
    elif cmd == "api" and len(r) >= 2:
        out = aplicar_api(r[0], r[1], r[2] if len(r) > 2 else None)
    elif cmd == "app" and len(r) >= 3 and r[1] == "--":
        app(r[0], r[2:])
    elif cmd == "servir" and r:
        out = servir(r[0])
    elif cmd == "web" and len(r) >= 2:
        web(r[0], r[1], r[2:])
    elif cmd == "emulador" and r and r[0] == "arrancar" and len(r) > 1:
        out = emulador_arrancar(r[1])
    elif cmd == "emulador" and r and r[0] == "parar" and len(r) > 1:
        out = emulador_parar(r[1])
    elif cmd == "emulador" and r and r[0] == "estado":
        out = {"emuladores": emuladores()}
    elif cmd == "adb":
        os.execvpe(os.path.join(SDK, "platform-tools", "adb"), ["adb"] + r, env_herramientas())
    elif cmd == "cuentas" and r:
        c = cuentas(config_de(worktree_e2e(r[0])[0]))
        if not c:
            raise Error("no hay cuentas de prueba (variables E2E_*, p. ej. E2E_<ROL>_USER / E2E_<ROL>_PASSWORD) en "
                        "%s junto a autopilot.env" % ARCHIVO_CUENTAS)
        print("\n".join("%s=%s" % kv for kv in sorted(c.items())))
        return 0
    else:
        print(__doc__, file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (Error, wi.Error) as e:
        print("e2e: NO SE EJECUTA: %s" % e, file=sys.stderr)
        sys.exit(3)
