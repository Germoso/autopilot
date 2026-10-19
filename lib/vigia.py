#!/usr/bin/env python3
"""
vigia.py — Vigilante periodico: procesos colgados, huerfanos y tareas atascadas.

Lo corre el watcher cada WATCHDOG_INTERVAL segundos (no gasta tokens). Los agentes trabajan en
sus worktrees (~/.cache/autopilot-kit/coder|qa|e2e/<repo>-<clave>), asi que cada proceso se asocia a
su tarea por su carpeta de trabajo (/proc/<pid>/cwd) o la de un proceso padre.

  huerfanos   procesos de un worktree cuya tarea ya no esta en ese puesto (done, stopped,
              reviewed, qa, new...) o cuyo worktree ya se borro -> se matan.
  colgados    procesos de una tarea activa cuyo CPU total no avanzo nada durante HUNG_MINUTES
              (estan vivos pero no hacen nada, p. ej. un test esperando una animacion infinita)
              -> se matan; el comando del agente termina con error y el agente sigue.
  atascadas   tarea en su puesto sin ninguna actividad (archivos, commits, CPU) durante
              STALE_MINUTES -> se avisa al orquestador (no se mata al agente).

Solo mata procesos de trabajo (node, dart, flutter, mongod, java, tests...). Nunca terminales,
editores ni los propios clientes, aunque esten parados dentro de un worktree. Solo mira worktrees
de repos y tareas de ESTE board.

uso: vigia.py <autopilot.env> [--simular]      JSON con lo que hizo (o haria)
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workitems as wi  # noqa: E402

INTOCABLES = {"bash", "sh", "zsh", "fish", "dash", "ksh", "tmux", "screen", "vim", "nvim", "vi", "nano",
              "emacs", "less", "more", "code", "code-oss", "cursor", "claude", "opencode", "ssh", "sudo",
              "su", "login", "systemd", "watcher.sh"}
PUESTO_DE = dict(wi.PUESTOS)  # coder, qa, e2e (el emulador del E2E arranca en su copia: tambien se vigila)
ESTADO = wi.cache_kit("vigia.json")
GRACIA = int(os.environ.get("AUTOPILOT_VIGIA_GRACIA", "60"))  # s: un proceso recien nacido no es huerfano


def ticks():
    return os.sysconf("SC_CLK_TCK")


def arranque_sistema():
    for l in open("/proc/stat"):
        if l.startswith("btime"):
            return int(l.split()[1])
    return 0


def procesos():
    """{pid: {ppid, cwd, cpu (s), edad (s), comm, cmd}} de todos los procesos legibles del usuario."""
    out, tk, btime, ahora = {}, ticks(), arranque_sistema(), time.time()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            cwd = os.readlink("/proc/%s/cwd" % d)
            st = open("/proc/%s/stat" % d).read()
            cmd = open("/proc/%s/cmdline" % d, "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            continue
        comm = st[st.index("(") + 1:st.rindex(")")]
        f = st[st.rindex(")") + 2:].split()
        out[int(d)] = {"ppid": int(f[1]), "cwd": cwd, "cpu": (int(f[11]) + int(f[12])) / tk,
                       "edad": ahora - (btime + int(f[19]) / tk), "comm": comm, "cmd": cmd[:160]}
    return out


def worktree_de(cwd):
    """(puesto, repo, clave, ruta) si cwd esta dentro de un worktree del kit; si no None."""
    borrado = cwd.endswith(" (deleted)")
    cwd = cwd[:-len(" (deleted)")] if borrado else cwd
    for puesto in PUESTO_DE:
        raiz = os.path.realpath(wi.cache_kit(puesto)) + os.sep
        if cwd.startswith(raiz):
            nombre = cwd[len(raiz):].split(os.sep)[0]
            m = wi.RE_WT.match(nombre)
            if m:
                return puesto, m.group("repo"), m.group("clave"), raiz + nombre, borrado
    return None


def agrupar(procs):
    """{(puesto, repo, clave): {"pids": [...], "ruta": ..., "borrado": bool}} incluyendo descendientes."""
    grupos, dueno = {}, {}
    for pid, p in procs.items():
        w = worktree_de(p["cwd"])
        if w:
            dueno[pid] = w
    for pid in procs:
        if pid in dueno:
            continue
        cur, n = procs[pid]["ppid"], 0
        while cur in procs and n < 30:  # hereda el worktree del ancestro mas cercano
            if cur in dueno:
                dueno[pid] = dueno[cur]
                break
            cur, n = procs[cur]["ppid"], n + 1
    for pid, (puesto, repo, clave, ruta, borrado) in dueno.items():
        if procs[pid]["comm"] in INTOCABLES or pid == os.getpid():
            continue
        g = grupos.setdefault((puesto, repo, clave), {"pids": [], "ruta": ruta, "borrado": False})
        g["pids"].append(pid)
        g["borrado"] = g["borrado"] or borrado
    return grupos


def matar(pids, procs):
    vivos = [p for p in pids if p in procs]
    for p in vivos:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    fin = time.time() + 10
    while time.time() < fin and any(os.path.exists("/proc/%d" % p) for p in vivos):
        time.sleep(0.5)
    for p in vivos:
        if os.path.exists("/proc/%d" % p):
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
    return [{"pid": p, "cmd": procs[p]["cmd"], "min": round(procs[p]["edad"] / 60, 1)} for p in vivos]


def matar_en(ruta):
    """Mata los procesos de trabajo cuyo cwd esta dentro de `ruta` (al borrar un worktree)."""
    procs = procesos()
    ruta = os.path.realpath(ruta) + os.sep
    pids = []
    for g in agrupar(procs).values():
        if os.path.realpath(g["ruta"]) + os.sep == ruta:
            pids += g["pids"]
    return matar(pids, procs)


def sesion_actualizada(ses):
    """Epoch de la ultima actualizacion de una sesion de OpenCode (0 si no se sabe)."""
    try:
        import oc_sesion
        t = oc_sesion.api("GET", "/api/session/%s" % ses, timeout=20)["data"].get("time", {})
        return max(t.get("updated") or 0, t.get("idle") or 0) / 1000
    except Exception:
        return 0


def ultima_actividad(ruta, meta_path):
    """Epoch de la ultima senal de vida de una tarea: commit, archivo cambiado o su .md."""
    marcas = [os.path.getmtime(meta_path)] if os.path.exists(meta_path) else []
    if os.path.isdir(ruta):
        r = subprocess.run(["git", "-C", ruta, "log", "-1", "--format=%ct"], capture_output=True, text=True)
        if r.stdout.strip().isdigit():
            marcas.append(int(r.stdout.strip()))
        r = subprocess.run(["git", "-C", ruta, "status", "--porcelain", "-uall"], capture_output=True, text=True)
        for l in r.stdout.splitlines()[:500]:
            f = os.path.join(ruta, l[3:].strip().strip('"'))
            if os.path.exists(f):
                marcas.append(os.path.getmtime(f))
    return max(marcas) if marcas else 0


def revisar(env, simular=False):
    b = wi.Board(wi.cargar_config(env))
    cfg = b.cfg["vigia"]
    ahora = time.time()
    try:
        estado = json.load(open(ESTADO))
    except (OSError, ValueError):
        estado = {}
    cpu_hist, reportadas = estado.get("cpu", {}), estado.get("reportadas", {})
    mis_repos = {(n or os.path.basename(r["path"])) for n, r in b.cfg["repos"].items()}
    tareas = {c: e for e, c, _ in b.archivos()}
    procs = procesos()
    out = {"huerfanos": [], "colgados": [], "atascadas": [], "simulado": simular}

    for (puesto, repo, clave), g in agrupar(procs).items():
        if repo not in mis_repos or clave not in tareas:
            continue  # worktree de otro board: no es asunto de este vigia
        clave_hist = "%s:%s:%s" % (puesto, repo, clave)
        activa = tareas[clave] == PUESTO_DE[puesto] and not g["borrado"]
        viejos = [p for p in g["pids"] if procs[p]["edad"] > GRACIA]
        if not activa:
            if viejos:
                muertos = viejos if simular else matar(viejos, procs)
                out["huerfanos"].append({"tarea": clave, "puesto": puesto, "repo": repo, "estado": tareas[clave],
                                         "procesos": muertos if not simular else [procs[p]["cmd"] for p in viejos]})
            cpu_hist.pop(clave_hist, None)
            continue
        total = round(sum(procs[p]["cpu"] for p in g["pids"]), 2)
        h = cpu_hist.get(clave_hist)
        if not h or h["cpu"] != total:
            cpu_hist[clave_hist] = {"cpu": total, "desde": ahora}
        elif ahora - h["desde"] >= cfg["hung_min"] * 60:
            quietos = round((ahora - h["desde"]) / 60, 1)
            muertos = [procs[p]["cmd"] for p in g["pids"]] if simular else matar(g["pids"], procs)
            out["colgados"].append({"tarea": clave, "puesto": puesto, "repo": repo, "minutos_sin_cpu": quietos,
                                    "procesos": muertos})
            cpu_hist.pop(clave_hist, None)
    vivos = {"%s:%s:%s" % k for k in agrupar(procs)}
    cpu_hist = {k: v for k, v in cpu_hist.items() if k in vivos}

    for t in b.todas():
        puesto = next((p for p, e in PUESTO_DE.items() if e == t["estado"]), None)
        if not puesto:
            reportadas.pop(t["id"], None)
            continue
        rutas = [{"coder": b.coder_worktree_path, "qa": b.qa_worktree_path, "e2e": b.e2e_worktree_path}[puesto](
            {"nombre": r["nombre"], "path": r["path"]}, t["id"]) for r in t.get("repos", [])]
        ult = max([ultima_actividad(r, t["archivo"]) for r in rutas] or [os.path.getmtime(t["archivo"])])
        ult = max([ult] + [v["desde"] for k, v in cpu_hist.items() if k.endswith(":" + t["id"])])
        if t.get("sesion") and str(t["sesion"]).startswith("ses_"):  # OpenCode: la sesion registra cuando se movio
            ult = max(ult, sesion_actualizada(t["sesion"]))
        quieta = (ahora - ult) / 60
        ya = reportadas.get(t["id"])
        if quieta >= cfg["stale_min"] and (not ya or ult > ya or ahora - ya >= cfg["stale_min"] * 60):
            out["atascadas"].append({"tarea": t["id"], "puesto": puesto, "minutos_sin_actividad": round(quieta, 1),
                                     "sesion": t.get("sesion")})
            reportadas[t["id"]] = ahora

    if not simular:
        os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
        wi.escribir_atomico(ESTADO, json.dumps({"cpu": cpu_hist, "reportadas": reportadas}, indent=1))
        for h in out["huerfanos"]:
            b.log("Vigia: procesos huerfanos terminados", "vigia", "recuperacion", h["tarea"], h["tarea"], "-",
                  "%s (tarea en %s): %s" % (h["puesto"], h["estado"], "; ".join(x["cmd"] for x in h["procesos"])))
        for c in out["colgados"]:
            b.log("Vigia: proceso colgado terminado", "vigia", "recuperacion", c["tarea"], c["tarea"], "-",
                  "%s: %s min sin CPU: %s" % (c["puesto"], c["minutos_sin_cpu"],
                                              "; ".join(x["cmd"] for x in c["procesos"])))
        for a in out["atascadas"]:
            b.log("Vigia: tarea sin actividad", "vigia", "nota", a["tarea"], a["tarea"], "-",
                  "%s: %s min sin archivos, commits ni CPU" % (a["puesto"], a["minutos_sin_actividad"]))
            b.avisar("🚨 %s lleva %s min sin actividad en %s (posible atasco). El orquestador lo revisa; "
                     "si no se mueve: /stop %s <motivo>" % (a["tarea"], int(a["minutos_sin_actividad"]), a["puesto"],
                                                           a["tarea"]), alerta=True, dedup=True)
        for c in out["colgados"]:
            b.avisar("⚠️ Vigia: termino un proceso colgado de %s (%s, %s min sin CPU). El agente sigue."
                     % (c["tarea"], c["puesto"], c["minutos_sin_cpu"]), dedup=True)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    try:
        print(json.dumps(revisar(sys.argv[1], "--simular" in sys.argv), ensure_ascii=False, indent=2))
    except wi.Error as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(3)
