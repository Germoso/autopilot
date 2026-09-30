#!/usr/bin/env python3
"""
pruebas.py — vuelve a correr los casos de prueba guardados en los repos (tests/<clave>/cases.json).

Los casos los dejan el QA y el agente E2E al aprobar una tarea (wi.sh aprobar / aprobar-e2e), como
tests normales del proyecto: tests/<clave>/ con cases.json, y tests/services.json por repo (como
levantarlo). Este comando los corre de nuevo, en copias propias, nunca contra produccion:

  test <clave>   los casos de esa tarea, en su rama (si ya no existe, en la rama base: ya se mergeo)
  test --all     regresion: todos los casos presentes en la rama base de cada repo
  --qa | --e2e   solo un tipo        --ref <rama>   otra rama

Casos QA: su `command` en la raiz del repo (con aenv.sh si needs.db). Casos E2E: levanta los
`needs.services` con aenv.sh --e2e (tests/services.json de cada repo), apunta las apps al backend
local como el agente E2E y corre el caso con e2e.sh (navegador sin red externa / emulador sin DNS).
Deja un reporte .md con capturas en <workspace>/test-results/ y sale con codigo 1 si algo fallo.

uso: pruebas.py <autopilot.env> <clave>|--all [--qa|--e2e] [--ref <rama>]
"""
import datetime
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import e2e  # noqa: E402
import entorno  # noqa: E402
import workitems as wi  # noqa: E402

AENV = os.path.join(AQUI, "aenv.sh")
E2E_SH = os.path.join(AQUI, "e2e.sh")


class Corrida:
    def __init__(self, env_path, clave, solo, ref):
        self.b = wi.Board(wi.cargar_config(env_path))
        self.cfg = self.b.cfg
        self.clave = clave            # None = --all
        self.solo = solo              # None | "qa" | "e2e"
        self.ref = ref
        self.id = clave or "all-%d" % int(time.time())
        self.copias = {}              # repo -> worktree
        self.procesos = []            # Popen de servicios (grupo propio)
        self.emulador = None
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.salida = os.path.join(self.cfg["raiz"], "test-results", "%s-%s" % (stamp, clave or "all"))
        self.resultados = []

    # -- repos y ramas
    def existe(self, repo, ref):
        return self.b.git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0

    def ref_de(self, r):
        if self.ref:
            return self.ref
        if self.clave and self.existe(r["path"], "refs/heads/%s" % self.clave):
            return self.clave
        return r["base"] if self.existe(r["path"], "refs/heads/%s" % r["base"]) else "origin/%s" % r["base"]

    def claves_en(self, r, ref):
        """Claves con tests/<clave>/cases.json en `ref` del repo."""
        ls = self.b.git(r["path"], "ls-tree", "-r", "--name-only", ref, "--", "tests", check=False).stdout.split()
        return sorted({p.split("/")[1] for p in ls if re.match(r"^tests/[^/]+/cases\.json$", p)})

    def copia(self, nombre):
        if nombre in self.copias:
            return self.copias[nombre]
        r = dict(self.cfg["repos"][nombre], nombre=nombre)
        ref = self.ref_de(r)
        wt = wi.cache_kit("run", "%s-%s" % (nombre, self.id))
        if os.path.isdir(wt):
            self.b.git(wt, "checkout", "--detach", "--force", ref)
        else:
            os.makedirs(os.path.dirname(wt), exist_ok=True)
            self.b.git(r["path"], "worktree", "add", "--detach", wt, ref)
        self.copias[nombre] = wt
        print("  %s @ %s (%s)" % (nombre, ref, self.b.git(wt, "rev-parse", "--short", "HEAD").stdout.strip()))
        return wt

    def dependencias(self, wt):
        marca = os.path.join(wt, ".deps-ok")
        if os.path.exists(marca):
            return
        if os.path.isfile(os.path.join(wt, "package.json")) and not os.path.isdir(os.path.join(wt, "node_modules")):
            cmd = "npm ci --no-audit --no-fund" if os.path.isfile(os.path.join(wt, "package-lock.json")) else "npm install --no-audit --no-fund"
            subprocess.run(["bash", "-lc", cmd], cwd=wt, capture_output=True, timeout=900)
        if os.path.isfile(os.path.join(wt, "pubspec.yaml")):
            flutter = "fvm flutter" if os.path.exists(os.path.join(wt, ".fvmrc")) else "flutter"
            subprocess.run(["bash", "-lc", flutter + " pub get"], cwd=wt, capture_output=True, timeout=900)
        open(marca, "w").close()

    # -- casos
    def casos(self):
        out = []
        for nombre, r in sorted(self.cfg["repos"].items()):
            r = dict(r, nombre=nombre)
            if not os.path.isdir(r["path"]):
                continue
            ref = self.ref_de(r)
            claves = self.claves_en(r, ref)
            if self.clave:
                claves = [c for c in claves if c == self.clave]
            if not claves:
                continue
            wt = self.copia(nombre)
            for c in claves:
                try:
                    lista = json.load(open(os.path.join(wt, "tests", c, "cases.json"), encoding="utf-8"))
                except (OSError, ValueError) as e:
                    self.resultados.append({"repo": nombre, "clave": c, "tipo": "?", "archivo": "cases.json",
                                            "ok": False, "segundos": 0, "detalle": "cases.json invalido: %s" % e})
                    continue
                for caso in lista:
                    if self.solo and caso.get("type") != self.solo:
                        continue
                    out.append(dict(caso, repo=nombre, clave=c, wt=wt))
        return out

    def correr(self, argv, cwd, env, timeout):
        t0 = time.time()
        try:
            r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout + 60)
            return r.returncode == 0, time.time() - t0, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired as e:
            return False, time.time() - t0, "tiempo maximo agotado (%ds)\n%s" % (timeout, e.stdout or "")

    def env_casos(self):
        env = dict(os.environ)
        env.update(e2e.cuentas(self.cfg))
        return env

    def caso_qa(self, c):
        self.dependencias(c["wt"])
        cmd = ["bash", "-lc", c["command"]]
        if (c.get("needs") or {}).get("db"):
            cmd = [AENV, c["wt"], "--"] + cmd
        return self.correr(cmd, c["wt"], self.env_casos(), self.cfg["vigia"]["timeout"])

    # -- servicios para E2E
    def servicio(self, nombre):
        if any(p.nombre == nombre for p in self.procesos):
            return next(p.url for p in self.procesos if p.nombre == nombre)
        wt = self.copia(nombre)
        try:
            svc = json.load(open(os.path.join(wt, "tests", "services.json"), encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("%s no tiene tests/services.json (como levantarlo)" % nombre)
        self.dependencias(wt)
        log = open(os.path.join(self.salida, "servicio-%s.log" % nombre), "w")
        p = subprocess.Popen([AENV, "--e2e", wt, "--", "bash", "-lc", svc["start"]], cwd=wt, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
        p.nombre, p.url = nombre, svc.get("ready_url")
        self.procesos.append(p)
        fin = time.time() + int(svc.get("ready_timeout", 300))
        while time.time() < fin:
            if p.poll() is not None:
                raise RuntimeError("%s termino al arrancar (ver %s)" % (nombre, log.name))
            try:
                urllib.request.urlopen(p.url, timeout=3)
                break
            except urllib.error.HTTPError:
                break                 # responde (404 en / es normal)
            except OSError:
                time.sleep(2)
        else:
            raise RuntimeError("%s no respondio en %s" % (nombre, p.url))
        print("  servicio %s listo en %s" % (nombre, p.url))
        return p.url

    def caso_e2e(self, c):
        needs = c.get("needs") or {}
        urls = {s: self.servicio(s) for s in needs.get("services", [])}
        env = self.env_casos()
        capturas = os.path.join(self.salida, "capturas", "%s-%s" % (c["clave"], re.sub(r"[^\w.-]", "_", c["file"])))
        os.makedirs(capturas, exist_ok=True)
        env.update({"SCREENSHOTS_DIR": capturas, "E2E_SALIDA": capturas, "E2E_CAPTURAS": capturas})
        if urls.get(c["repo"]):
            env["BASE_URL"] = urls[c["repo"]]
        if needs.get("platform", "web") == "android":
            e2e.aplicar_api(c["wt"], "android")
            if not self.emulador:
                self.emulador = e2e.emulador_arrancar(c["wt"])["serial"]
            self.dependencias(c["wt"])
            cmd = [E2E_SH, "app", c["wt"], "--"] + c["command"].replace("{device}", self.emulador).split()
        else:
            cmd = [E2E_SH, "web", c["wt"], c["file"], "--project", c.get("project", "web-escritorio")]
        return self.correr(cmd, c["wt"], env, self.cfg["e2e"]["timeout"])

    # -- todo
    def ejecutar(self):
        os.makedirs(self.salida, exist_ok=True)
        print("Preparando copias:")
        casos = self.casos()
        if not casos and not self.resultados:
            print("No hay casos guardados%s." % (" para %s" % self.clave if self.clave else ""))
            return 0
        for c in sorted(casos, key=lambda x: (x.get("type") != "qa", x["clave"], x["repo"])):
            etiqueta = "%s %s %s/%s" % (c["clave"], c.get("type"), c["repo"], c["file"])
            print("▶ %s" % etiqueta, flush=True)
            try:
                ok, seg, log = self.caso_qa(c) if c.get("type") == "qa" else self.caso_e2e(c)
            except Exception as e:  # un servicio que no levanta, una copia que no se crea...
                ok, seg, log = False, 0, "no se pudo correr: %s" % e
            for k, v in e2e.cuentas(self.cfg).items():
                if v:
                    log = log.replace(v, "***")
            self.resultados.append({"repo": c["repo"], "clave": c["clave"], "tipo": c.get("type"),
                                    "archivo": c["file"], "criterio": c.get("criterion", ""), "ok": ok,
                                    "segundos": round(seg), "detalle": log[-3000:]})
            print("  %s (%ds)" % ("✅ pasa" if ok else "❌ falla", seg), flush=True)
        return self.reporte()

    def limpiar(self):
        for p in self.procesos:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(2)
        for p in self.procesos:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        if self.emulador:
            e2e.emulador_parar(self.emulador)
        for nombre, wt in self.copias.items():
            e2e.olvidar_api(wt)
            self.b.git(self.cfg["repos"][nombre]["path"], "worktree", "remove", "--force", wt, check=False)
            self.b.git(self.cfg["repos"][nombre]["path"], "worktree", "prune", check=False)

    def reporte(self):
        fallos = [r for r in self.resultados if not r["ok"]]
        md = ["# Casos de prueba: %s" % (self.clave or "todos (regresión)"), "",
              "**Fecha:** %s  " % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
              "**Resultado:** %s — %d de %d pasan" % ("✅ todo pasa" if not fallos else "❌ hay fallos",
                                                     len(self.resultados) - len(fallos), len(self.resultados)),
              "", "| Tarea | Tipo | Repo | Caso | Resultado | Tiempo |", "|---|---|---|---|---|---|"]
        for r in self.resultados:
            md.append("| %s | %s | %s | `%s` | %s | %ds |" % (r["clave"], r["tipo"], r["repo"], r["archivo"],
                                                            "✅" if r["ok"] else "❌", r["segundos"]))
        for r in self.resultados:
            md += ["", "## %s — %s `%s` %s" % (r["clave"], r["tipo"], r["archivo"], "✅" if r["ok"] else "❌")]
            if r.get("criterio"):
                md.append("**Criterio:** %s" % r["criterio"])
            carpeta = os.path.join(self.salida, "capturas", "%s-%s" % (r["clave"], re.sub(r"[^\w.-]", "_", r["archivo"])))
            for img in sorted(glob.glob(os.path.join(carpeta, "**", "*.png"), recursive=True)):
                md.append("![%s](%s)" % (os.path.basename(img), os.path.relpath(img, os.path.dirname(self.salida))))
            if not r["ok"]:
                md += ["", "```", r["detalle"].strip()[-2500:], "```"]
        path = self.salida + ".md"
        open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
        print("\n%-12s %-4s %-28s %-50s %s" % ("TAREA", "TIPO", "REPO", "CASO", "RESULTADO"))
        for r in self.resultados:
            print("%-12s %-4s %-28s %-50s %s" % (r["clave"], r["tipo"], r["repo"][:28], r["archivo"][-50:],
                                                "✅" if r["ok"] else "❌"))
        print("\n%d de %d pasan. Reporte: %s" % (len(self.resultados) - len(fallos), len(self.resultados), path))
        return 1 if fallos else 0


def main(a):
    if not a or a[0] in ("-h", "--help") or len(a) < 2:
        print(__doc__)
        return 0 if a and a[0] in ("-h", "--help") else 2
    env_path, resto = a[0], a[1:]
    solo = "qa" if "--qa" in resto else "e2e" if "--e2e" in resto else None
    ref = resto[resto.index("--ref") + 1] if "--ref" in resto and resto.index("--ref") + 1 < len(resto) else None
    posicionales = [x for i, x in enumerate(resto) if not x.startswith("--") and (i == 0 or resto[i - 1] != "--ref")]
    if "--all" in resto:
        clave = None
    elif posicionales and re.match(r"^(task|bug)-\d+$", posicionales[0].lower()):
        clave = posicionales[0].lower()
    else:
        print("indica una tarea (bug-123 / task-123) o --all", file=sys.stderr)
        return 2
    c = Corrida(env_path, clave, solo, ref)
    try:
        return c.ejecutar()
    finally:
        c.limpiar()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (wi.Error, e2e.Error) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(3)
