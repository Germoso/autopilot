#!/usr/bin/env python3
"""
salud.py — health check de las pruebas E2E: dice ANTES de ejecutar que falta para que funcionen.

uso: salud.py <autopilot.env> [<clave>|smoke|--all] [--web|--android] [--deep] [--json]

Revisa, para cualquier proyecto:
  herramientas   Java, Android SDK, emulador, AVD, Playwright, Chromium, flutter/fvm, node
  kvm            acceso a /dev/kvm (si el usuario esta en el grupo pero la sesion no lo ve: aviso)
  config         E2E, E2E_CLIENTS, E2E_PLATFORMS, E2E_API (la linea existe en la rama a probar)
  ambientes      .env.autopilot(.e2e) de backends y fronts web, PORT definido y distinto, puertos libres
  cuentas        cuentas-e2e.env y los roles que piden los casos guardados
  compila        imports Dart con mayusculas que no existen, Java de otra maquina en gradle.properties,
                 app Flutter que no soporta web (Firebase sin opciones de web)
  casos          cases.json validos y tests/services.json de los servicios que piden
  produccion     servidores de produccion que se van a bloquear
  --deep         ademas arranca y apaga el emulador y abre Chromium
Cada punto: ✅ ok, ⚠️ aviso (se puede correr), ❌ bloquea (con que hacer). Sale con 1 si hay ❌.
Cada ❌ dice QUIEN lo resuelve: [coder] = se arregla con un commit en la rama (p. ej. un import roto; el
orquestador devuelve la tarea al coder, sin molestar al humano) o [humano] = herramienta, ambiente,
cuenta o configuracion (la tarea se detiene y se le avisa).
"""
import json
import os
import re
import socket
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import e2e  # noqa: E402
import entorno  # noqa: E402
import workitems as wi  # noqa: E402


class Salud:
    def __init__(self, env_path, objetivo=None, plataforma=None, deep=False):
        self.cfg = wi.cargar_config(env_path)
        self.b = wi.Board(self.cfg)
        self.objetivo = objetivo          # None | clave | "smoke" | "all"
        self.plataforma = plataforma      # None | web | android
        self.deep = deep
        self.items = []
        self.alcance = None               # repos que usan los casos elegidos (None = todos)

    def add(self, nivel, area, msg, solucion="", responsable=None):
        # compila (codigo del repo) lo resuelve el coder; lo demas (herramientas, ambientes, cuentas,
        # configuracion del kit) el humano.
        responsable = responsable or ("coder" if area == "compila" else "humano")
        self.items.append({"nivel": nivel, "area": area, "mensaje": msg, "solucion": solucion,
                           "responsable": responsable if nivel == "error" else None})

    # -- utilidades git
    def git(self, repo, *a):
        return subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)

    def ref(self, r):
        if self.objetivo and self.objetivo not in ("smoke", "all") and \
                self.git(r["path"], "rev-parse", "--verify", "-q", "refs/heads/" + self.objetivo).returncode == 0:
            return self.objetivo
        if self.objetivo == "smoke" and self.git(r["path"], "rev-parse", "--verify", "-q", "refs/heads/smoke-tests").returncode == 0:
            return "smoke-tests"
        base = r["base"]
        return base if self.git(r["path"], "rev-parse", "--verify", "-q", "refs/heads/" + base).returncode == 0 \
            else "origin/" + base

    def show(self, repo, ref, path):
        r = self.git(repo, "show", "%s:%s" % (ref, path))
        return r.stdout if r.returncode == 0 else None

    def plataformas(self, nombre, tipo):
        return self.cfg["e2e"]["platforms"].get(nombre) or (["web", "android"] if tipo == "flutter" else ["web"])

    def quiere(self, plat):
        return self.plataforma in (None, plat)

    # -- chequeos
    def herramientas(self):
        faltan = [f for f in e2e.herramientas_faltantes() if "kvm" not in f]
        web = [f for f in faltan if f in ("Playwright", "Chromium de Playwright")]
        android = [f for f in faltan if f not in web]
        for grupo, plat in ((web, "web"), (android, "android")):
            if grupo and self.quiere(plat):
                self.add("error", "herramientas", "faltan: %s" % ", ".join(grupo),
                         "~/.local/share/autopilot-kit/e2e-setup.sh")
        if not faltan:
            self.add("ok", "herramientas", "Java, Android SDK, emulador, AVD, Playwright y Chromium instalados")
        estado = e2e.kvm()
        if estado == "ok":
            self.add("ok", "kvm", "acceso a /dev/kvm")
        elif estado == "sg":
            self.add("aviso", "kvm", "estas en el grupo kvm pero esta sesion aun no lo ve; el kit usa `sg kvm` solo",
                     "cierra sesion y vuelve a entrar para que quede fijo")
        elif self.quiere("android"):
            self.add("error", "kvm", "sin acceso a /dev/kvm: el emulador no arranca",
                     "sudo usermod -aG kvm $USER (en una terminal) y cerrar sesion")

    def config(self):
        c = self.cfg["e2e"]
        if not c["activo"]:
            self.add("aviso", "config", "E2E=false: /autopilot no hace pruebas E2E (run-tests si funciona)",
                     "E2E=true en autopilot.env")
        clientes = {f for fs in c["clients"].values() for f in fs}
        for n, r in self.repos():
            if not os.path.isdir(r["path"]):
                self.add("error", "config", "%s: no existe la carpeta %s" % (n, r["path"]))
                continue
            tipo = e2e.tipo_repo(r["path"])
            if tipo in ("flutter", "web") and self.cfg["workspace"] and n not in clientes:
                self.add("aviso", "config", "%s (%s) no esta en ningun E2E_CLIENTS: no se sabe que backend usa" % (n, tipo),
                         "E2E_CLIENTS.<backend>=...,%s en autopilot.env" % n)

    def repos(self):
        return [(n, r) for n, r in sorted(self.cfg["repos"].items()) if self.alcance is None or n in self.alcance]

    def ambientes(self):
        puertos = {}
        for n, r in self.repos():
            if not os.path.isdir(r["path"]):
                continue
            tipo = e2e.tipo_repo(r["path"])
            if tipo not in ("backend", "web"):
                continue
            archivo = entorno.archivo_e2e(r["path"])
            v = entorno.validar(r["path"], archivo, copia=True)
            if v["estado"] != "ok":
                self.add("error", "ambiente", "%s: %s (%s)" % (n, archivo, v["estado"]), v.get("recomendacion", ""))
            else:
                self.add("ok", "ambiente", "%s: %s valido (local/QA)" % (n, archivo))
            if tipo == "backend":
                p = e2e.puerto_backend(r["path"])
                if not p:
                    self.add("error", "ambiente", "%s: sin PORT" % n, "PORT=<puerto> en su %s" % archivo)
                else:
                    puertos.setdefault(p, []).append(n)
            if tipo == "web" and "env" not in (self.cfg["e2e"]["api"].get(n) or {}):
                self.add("aviso", "ambiente", "%s: sin E2E_API.%s=env:<variables de URL>; usara la API de su %s"
                         % (n, n, archivo), "E2E_API.%s=env:VITE_API_URL (o como se llamen) en autopilot.env" % n)
        for p, repos in sorted(puertos.items()):
            if len(repos) > 1:
                self.add("error", "ambiente", "PORT=%s repetido en %s: no pueden correr juntos" % (p, ", ".join(repos)),
                         "un PORT distinto en el .env.autopilot de cada backend")
            s = socket.socket()
            ocupado = s.connect_ex(("127.0.0.1", int(p))) == 0
            s.close()
            if ocupado:
                self.add("aviso", "ambiente", "el puerto %s (%s) ya esta en uso ahora" % (p, ", ".join(repos)),
                         "apaga lo que corre ahi antes de probar")

    def apps(self):
        for n, r in self.repos():
            if not os.path.isdir(r["path"]) or e2e.tipo_repo(r["path"]) != "flutter":
                continue
            ref = self.ref(r)
            plats = self.plataformas(n, "flutter")
            api = self.cfg["e2e"]["api"].get(n)
            if not api or "archivo" not in api:
                self.add("error", "config", "%s: falta E2E_API.%s: no se puede apuntar la app al backend local" % (n, n),
                         "E2E_API.%s=<archivo>|<regex de la linea>|<reemplazo con {API}>" % n)
            else:
                txt = self.show(r["path"], ref, api["archivo"]) or ""
                hits = len(re.findall(api["regex"], txt, re.M))
                if hits != 1:
                    self.add("error", "config", "%s: la regex de E2E_API encuentra %d lineas en %s (%s); debe ser 1"
                             % (n, hits, api["archivo"], ref), "ajusta E2E_API.%s" % n)
                else:
                    self.add("ok", "config", "%s: E2E_API apunta la app al backend local (%s)" % (n, ref))
            # imports con mayusculas que no existen (compila en Mac, falla en Linux)
            pub = self.show(r["path"], ref, "pubspec.yaml") or ""
            m = re.search(r"(?m)^name:\s*(\S+)", pub)
            if m:
                pkg = m.group(1)
                archivos = set(self.git(r["path"], "ls-tree", "-r", "--name-only", ref, "--", "lib").stdout.split())
                grep = self.git(r["path"], "grep", "-h", "-E", "^\\s*(import|export|part) 'package:%s/" % pkg,
                                ref, "--", "lib").stdout   # sin las lineas comentadas
                malos = sorted({x for x in re.findall(r"package:%s/([^']+)" % re.escape(pkg), grep)
                                if "lib/" + x not in archivos})
                if malos:
                    reales = {a.lower(): a for a in archivos}
                    detalle = "; ".join("%s (existe como %s)" % (x, reales.get(("lib/" + x).lower(), "—")) for x in malos[:5])
                    self.add("error", "compila", "%s (%s): imports que no existen en Linux: %s" % (n, ref, detalle),
                             "corregir las mayusculas del import en el repo")
            gp = self.show(r["path"], ref, "android/gradle.properties") or ""
            jh = re.search(r"(?m)^\s*org\.gradle\.java\.home\s*=\s*(.+)$", gp)
            if jh and not os.path.isdir(jh.group(1).strip()):
                self.add("aviso", "compila", "%s: android/gradle.properties fija un Java de otra maquina "
                         "(org.gradle.java.home); el kit usa el suyo" % n, "quitar esa linea del repo")
            main = self.show(r["path"], ref, "lib/main.dart") or ""
            if "web" in plats and re.search(r"Firebase\.initializeApp\(\s*\)", main):
                self.add("aviso", "compila", "%s: Firebase.initializeApp() sin opciones de web: la app no arranca en "
                         "navegador" % n, "E2E_PLATFORMS.%s=android en autopilot.env" % n)

    def casos(self):
        claves_repo = []
        for n, r in sorted(self.cfg["repos"].items()):
            if not os.path.isdir(r["path"]):
                continue
            ref = self.ref(r)
            ls = self.git(r["path"], "ls-tree", "-r", "--name-only", ref, "--", "tests").stdout.split()
            for p in ls:
                m = re.match(r"^tests/([^/]+)/cases\.json$", p)
                if m and (self.objetivo in (None, "all") or m.group(1) == self.objetivo):
                    claves_repo.append((n, r, ref, m.group(1)))
        if self.objetivo and self.objetivo != "all" and not claves_repo:
            self.add("error", "casos", "no hay casos guardados para %s" % self.objetivo,
                     "se guardan al aprobar la tarea (o con wi.sh smoke-save para smoke)")
            return []
        necesita_cuentas, casos = set(), []
        if self.objetivo and self.objetivo != "all":
            self.alcance = set()
        for n, r, ref, clave in claves_repo:
            if self.alcance is not None:
                self.alcance.add(n)
            try:
                lista = json.loads(self.show(r["path"], ref, "tests/%s/cases.json" % clave) or "")
            except ValueError:
                self.add("error", "casos", "%s: tests/%s/cases.json invalido (%s)" % (n, clave, ref),
                         "corregir el JSON en la rama", responsable="coder")
                continue
            for c in lista:
                needs = c.get("needs") or {}
                if self.plataforma and c.get("type") == "e2e" and needs.get("platform", "web") != self.plataforma:
                    continue
                casos.append(c)
                necesita_cuentas |= set(needs.get("accounts", []))
                for s in needs.get("services", []):
                    if self.alcance is not None:
                        self.alcance.add(s)
                    rs = self.cfg["repos"].get(s)
                    if not rs:
                        self.add("error", "casos", "%s/%s pide el servicio %s, que no esta en autopilot.env" % (n, c.get("file"), s))
                    elif self.show(rs["path"], self.ref(dict(rs, nombre=s)), "tests/services.json") is None:
                        self.add("error", "casos", "%s no tiene tests/services.json (como levantarlo) en %s"
                                 % (s, self.ref(dict(rs, nombre=s))), "lo deja el agente E2E al aprobar una tarea")
        if claves_repo:
            self.add("ok", "casos", "%d caso(s) guardado(s) en %d carpeta(s)" % (len(casos), len(claves_repo)))
        cuentas = e2e.cuentas(self.cfg)
        faltan = sorted(a for a in necesita_cuentas if not any(k.startswith(a) for k in cuentas))
        if faltan:
            self.add("error", "cuentas", "faltan cuentas de prueba: %s" % ", ".join(faltan),
                     "agregalas (<ROL>_USER / <ROL>_PASSWORD) a %s junto a autopilot.env" % e2e.ARCHIVO_CUENTAS)
        elif not cuentas:
            self.add("aviso", "cuentas", "no hay %s: los flujos con login no se van a poder probar" % e2e.ARCHIVO_CUENTAS,
                     "crea %s junto a autopilot.env con E2E_<ROL>_USER / E2E_<ROL>_PASSWORD" % e2e.ARCHIVO_CUENTAS)
        else:
            self.add("ok", "cuentas", "cuentas de prueba: %s" % ", ".join(sorted({k.rsplit("_", 1)[0] for k in cuentas})))
        return casos

    def produccion(self):
        hosts = e2e.hosts_produccion(self.cfg)
        if hosts:
            self.add("ok", "produccion", "internet abierto; se bloquean: %s" % ", ".join(hosts))
        else:
            self.add("aviso", "produccion", "no se detecto ningun servidor de produccion para bloquear",
                     "E2E_BLOCK_HOSTS=<host1>,<host2> en autopilot.env si hay alguno")

    def profundo(self):
        if self.quiere("android") and e2e.kvm() != "no":
            wt = wi.cache_kit("run", "salud-all-0")
            os.makedirs(wt, exist_ok=True)
            try:
                s = e2e.emulador_arrancar(wt, self.cfg)
                e2e.emulador_parar(s["serial"])
                self.add("ok", "deep", "el emulador arranca y se apaga (%s)" % s["serial"])
            except Exception as ex:
                self.add("error", "deep", "el emulador no arranca: %s" % ex)
            finally:
                import shutil
                shutil.rmtree(wt, ignore_errors=True)
        if self.quiere("web"):
            cli = os.path.join(e2e.NODE_MODULES, "@playwright", "test", "index.js")
            r = subprocess.run(["node", "-e", "require(%r).chromium.launch().then(b=>b.close()).then(()=>console.log('ok'))" % cli],
                               capture_output=True, text=True, timeout=120, env=e2e.env_herramientas())
            self.add("ok" if "ok" in r.stdout else "error", "deep",
                     "Chromium abre" if "ok" in r.stdout else "Chromium no abre: %s" % r.stderr.strip()[-200:])

    def base(self):
        if not os.path.isdir(self.cfg["dir"]):
            return
        try:
            db = self.b.db
            n = len(db.claves())
        except Exception as ex:
            self.add("error", "tablero", "no se puede abrir la base del tablero: %s" % ex, "revisar .workitems/autopilot.db")
            return
        falt = db.adjuntos_faltantes()
        if falt:
            self.add("aviso", "tablero", "%d adjunto(s) registrados cuyo archivo ya no existe (p. ej. %s)"
                     % (len(falt), falt[0]["ruta"]), "se borraron a mano de .workitems/adjuntos/")
        else:
            self.add("ok", "tablero", "base del tablero ok (%d tareas)" % n)

    def telegram(self):
        tg = self.cfg.get("telegram", {})
        if not tg.get("activo"):
            self.add("ok", "telegram", "TELEGRAM=false (sin avisos por Telegram)")
            return
        import telegram as tgm
        for nivel, msg, sol in tgm.check(self.cfg):
            self.add(nivel, "telegram", msg, sol)
        if self.deep and not any(i["area"] == "telegram" and i["nivel"] == "error" for i in self.items):
            tgm.enviar(self.cfg, "🩺 health-check --deep: prueba de Telegram", forzar=True)
            self.add("ok", "telegram", "mensaje de prueba enviado a tu chat")

    def correr(self):
        self.herramientas()
        self.casos()          # primero: define que repos usan los casos elegidos
        self.config()
        self.ambientes()
        self.apps()
        self.produccion()
        self.base()
        self.telegram()
        if self.deep:
            self.profundo()
        return self.items


ICONO = {"ok": "✅", "aviso": "⚠️ ", "error": "❌"}


def imprimir(items):
    for it in sorted(items, key=lambda x: {"error": 0, "aviso": 1, "ok": 2}[x["nivel"]]):
        quien = " [%s]" % it["responsable"] if it.get("responsable") else ""
        print("%s %-12s %s%s" % (ICONO[it["nivel"]], it["area"], it["mensaje"], quien))
        if it["nivel"] != "ok" and it["solucion"]:
            print("   %-12s → %s" % ("", it["solucion"]))
    e = sum(1 for i in items if i["nivel"] == "error")
    a = sum(1 for i in items if i["nivel"] == "aviso")
    coder = sum(1 for i in items if i["nivel"] == "error" and i.get("responsable") == "coder")
    if e and coder == e:
        print("\n❌ %d problema(s) bloquean, todos de codigo: los corrige el coder en la rama (no necesitan al humano)." % e)
        return 1
    print("\n%s" % ("❌ %d problema(s) bloquean las pruebas E2E (%d los resuelve el humano)." % (e, e - coder) if e else
                    "✅ Listo para correr las pruebas E2E%s." % (" (%d aviso/s)" % a if a else "")))
    return 1 if e else 0


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    env_path, resto = a[0], a[1:]
    pos = [x for x in resto if not x.startswith("--")]
    objetivo = "all" if "--all" in resto else (pos[0].lower() if pos else None)
    plat = "web" if "--web" in resto else "android" if "--android" in resto else None
    items = Salud(env_path, objetivo, plat, "--deep" in resto).correr()
    if "--json" in resto:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 1 if any(i["nivel"] == "error" for i in items) else 0
    return imprimir(items)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (wi.Error, e2e.Error) as ex:
        print("ERROR: %s" % ex, file=sys.stderr)
        sys.exit(3)
