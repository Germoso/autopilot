#!/usr/bin/env python3
"""orca-board — tablero agnostico de tareas de Orca (orchestration).

Lee las tareas directamente del CLI de Orca (`orca orchestration task-list/run-list`),
asi funciona con CUALQUIER agente (pi, opencode, claude, codex...) y desde cualquier
dispositivo. Orca sigue siendo la unica fuente de verdad; esto solo la muestra.

Uso:
  orca-board                     TUI interactiva (si el terminal lo permite); si no, lista
  orca-board tui                 fuerza la TUI interactiva
  orca-board --run <id>          fija la run con la que arranca la TUI (o filtra la lista)
  orca-board --status <est>      filtra por estado (ready, dispatched, completed, ...)
  orca-board --json              salida JSON cruda (para scripts / otros agentes)
  orca-board web [--port N]      servidor web: tarjetas por estado + iniciar tarea
  orca-board web --lan           expuesto a la red local (celular, otra PC)
  orca-board --orca <ruta>       usa otro binario de orca (por defecto: el del PATH)

Sin dependencias: solo stdlib (curses para la TUI). El binario de orca se busca en el
PATH, en ORCA_CLI_BIN_DIR o en ~/.orca/cli/bin/orca.
"""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ESTADOS = ["pending", "ready", "dispatched", "completed", "failed", "blocked"]
COLOR = {  # para la salida de terminal (si el pipe no es tty se apaga solo)
    "pending": "90", "ready": "32", "dispatched": "33", "completed": "36",
    "failed": "31", "blocked": "35",
}
ETIQUETA = {"pending": "pendiente", "ready": "lista", "dispatched": "en curso",
            "completed": "completada", "failed": "fallida", "blocked": "bloqueada"}


def buscar_orca(explicita):
    if explicita:
        return explicita
    env = os.environ.get("ORCA_CLI_BIN_DIR")
    if env and os.path.isfile(os.path.join(env, "orca")):
        return os.path.join(env, "orca")
    en_path = shutil.which("orca")
    if en_path:
        return en_path
    home = os.path.join(os.path.expanduser("~"), ".orca", "cli", "bin", "orca")
    if os.path.isfile(home):
        return home
    sys.exit("orca-board: no encuentro el binario de orca (usa --orca <ruta>)")


def orca(binario, *args):
    proc = subprocess.run([binario, *args], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("orca %s fallo: %s" % (" ".join(args), proc.stderr.strip() or proc.stdout.strip()))
    return json.loads(proc.stdout)


def runs(binario):
    return (orca(binario, "orchestration", "run-list", "--json").get("result", {}).get("runs") or [])


def tareas(binario, run_id):
    return (orca(binario, "orchestration", "task-list", "--run", run_id, "--json")
            .get("result", {}).get("tasks") or [])


def cortar(s, n=160):
    s = (s or "").replace("\\n", " ").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------- CLI
def cli(args):
    binario = buscar_orca(args.orca)
    todo = runs(binario)
    if args.json:
        datos = {"runs": []}
        for r in todo:
            t = tareas(binario, r["id"])
            datos["runs"].append({"run": r, "tasks": t})
        print(json.dumps(datos, ensure_ascii=False, indent=2))
        return 0
    tty = sys.stdout.isatty()
    def color(cod, s):
        return "\033[%sm%s\033[0m" % (cod, s) if tty else s
    if not todo:
        print("No hay runs de orquestacion (orca orchestration run-create ...)")
        return 0
    ninguna = True
    for r in todo:
        if r.get("legacy"):
            continue
        if args.run and r["id"] != args.run:
            continue
        ts = tareas(binario, r["id"])
        if args.status:
            ts = [t for t in ts if t.get("status") == args.status]
        if not ts and not args.run:
            continue
        ninguna = False
        print(color("1;36", "RUN %s") % r["id"])
        print("  objetivo: %s" % cortar(r.get("objective"), 120))
        for t in ts:
            est = t.get("status", "?")
            marca = color(COLOR.get(est, "90"), "[%-9s]" % est)
            print("  %s %s  %s" % (marca, t.get("id", "?"), cortar(t.get("task_title"), 90)))
        print()
    if ninguna:
        print("No hay tareas que mostrar" + (" (filtro: --status %s)" % args.status if args.status else ""))
    return 0


# ---------------------------------------------------------------- TUI


def _cargar(binario, solo_run=None, filtro=None):
    """Lista de {run, tasks} (salta runs legacy y aplica filtro de estado)."""
    todo = []
    for r in runs(binario):
        if r.get("legacy"):
            continue
        if solo_run and r["id"] != solo_run:
            continue
        ts = tareas(binario, r["id"])
        if filtro:
            ts = [t for t in ts if t.get("status") == filtro]
        todo.append({"run": r, "tasks": ts})
    return todo


def _tui_loop(std, binario, solo_run, filtro_inicial):
    import curses
    curses.curs_set(0)
    curses.use_default_colors()
    curses.start_color()
    for i, est in enumerate(ESTADOS, 1):
        curses.init_pair(i, int(COLOR[est]), -1)
    PAR = {e: curses.color_pair(i) for i, e in enumerate(ESTADOS, 1)}
    RESALT = curses.A_REVERSE
    A = {"title": curses.A_BOLD | curses.color_pair(4)}

    st = {"filtro": filtro_inicial, "idx_run": 0, "idx_task": 0, "foco": "runs",
          "datos": [], "msj": "", "inicio": None}

    def an(y, x, s, n=None, attr=0):
        """addnstr seguro: no pisa el borde derecho (evita el scroll por la ultima celda)."""
        _m, mx = std.getmaxyx()
        if x >= mx:
            return
        if n is None:
            n = mx - x
        std.addnstr(y, x, s, max(0, min(n, mx - x - (1 if y == _m - 1 else 0))), attr)

    def recargar():
        st["datos"] = _cargar(binario, solo_run, st["filtro"])
        st["idx_run"] = min(st["idx_run"], max(0, len(st["datos"]) - 1))
        st["idx_task"] = 0
        st["msj"] = "Refrescado %s" % time.strftime("%H:%M:%S")

    def lanzar(tid):
        def correr():
            cmd = [binario, "orchestration", "worker-start", "--task", tid, "--json"]
            if st["inicio"].get("agente"):
                cmd += ["--agent", st["inicio"]["agente"]]
            if st["inicio"].get("base"):
                cmd += ["--base-branch", st["inicio"]["base"]]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                salida = (proc.stdout.strip() or proc.stderr.strip() or "(sin salida)")
                if proc.returncode == 0:
                    try:
                        salida = json.dumps(json.loads(salida), ensure_ascii=False)
                    except Exception:
                        pass
                    st["msj"] = "OK: %s" % cortar(salida, 180)
                else:
                    st["msj"] = "ERROR: %s" % cortar(salida, 180)
            except Exception as e:
                st["msj"] = "ERROR: %s" % e
            st["inicio"] = None
        st["inicio"] = {"tid": tid}
        st["msj"] = "Iniciando %s..." % tid
        threading.Thread(target=correr, daemon=True).start()

    def linea(prompt, por_defecto):
        """Input de una linea en la barra inferior. Devuelve str (vacia = cancelar)."""
        curses.curs_set(1)
        curses.echo()
        try:
            std.addstr(std.getmaxyx()[0] - 1, 0, prompt + por_defecto)
            std.clrtoeol()
            std.refresh()
            buf = ""
            while True:
                ch = std.getch()
                if ch in (curses.KEY_ENTER, 10, 13):
                    break
                if ch == 27:  # Esc
                    buf = ""
                    break
                if ch == curses.KEY_BACKSPACE or ch == 127:
                    buf = buf[:-1]
                elif 32 <= ch < 127:
                    buf += chr(ch)
                std.addstr(std.getmaxyx()[0] - 1, 0, prompt + por_defecto)
                std.clrtoeol()
                std.addstr(std.getmaxyx()[0] - 1, 0, prompt + buf)
                std.refresh()
            return buf
        finally:
            curses.noecho()
            curses.curs_set(0)

    recargar()
    ultimo_poll = time.time()
    while True:
        maxy, maxx = std.getmaxyx()
        if maxy < 8 or maxx < 40:
            std.erase()
            std.addstr(0, 0, "Terminal muy chica (min 40x8)")
            std.refresh()
            ch = std.getch()
            if ch in (ord("q"), 27):
                return
            continue
        std.erase()

        # --- cabecera
        an(0, 0, "ORCA BOARD", None, A["title"])
        if st["datos"]:
            r = st["datos"][st["idx_run"]]["run"]
            an(0, 12, "%s  %s" % (r["id"], cortar(r.get("objective"), maxx - 46)))
        an(0, maxx - 14, "filtro: %s" % (st["filtro"] or "todos"))
        std.hline(1, 0, "-", maxx)

        # --- panel izquierdo: runs
        ancho_run = 34
        y = 2
        an(y, 0, "RUNS (%d)" % len(st["datos"]), None, curses.A_BOLD)
        y += 1
        for i, d in enumerate(st["datos"]):
            if y >= maxy - 3:
                break
            r = d["run"]
            linea_txt = " %s %s" % (r["id"], cortar(r.get("objective"), ancho_run - 8))
            attr = RESALT if (st["foco"] == "runs" and i == st["idx_run"]) else 0
            an(y, 0, linea_txt, ancho_run, attr)
            y += 1
        std.vline(2, ancho_run, "|", maxy - 4)

        # --- panel derecho: tareas
        x = ancho_run + 2
        if not st["datos"]:
            an(2, x, "Sin runs de orquestacion (orca orchestration run-create ...)")
        else:
            d = st["datos"][st["idx_run"]]
            run_id = d["run"]["id"]
            an(2, x, "TAREAS  %s" % run_id, None, curses.A_BOLD)
            y = 3
            # items planos: (tipo, payload); navegables solo las tareas
            items = []
            for est in ESTADOS:
                grp = [t for t in d["tasks"] if t.get("status") == est]
                if not grp:
                    continue
                items.append(("header", est, None))
                for t in grp:
                    items.append(("task", est, t))
            st["idx_task"] = min(st["idx_task"], max(0, sum(1 for it in items if it[0] == "task") - 1))
            idx_t = -1
            for it in items:
                if y >= maxy - 3:
                    break
                tipo, est, t = it
                if tipo == "header":
                    an(y, x, "  %s (%d)" % (ETIQUETA[est],
                        sum(1 for q in items if q[0] == "task" and q[1] == est)), None,
                        curses.A_BOLD | PAR[est])
                else:
                    idx_t += 1
                    sel = (st["foco"] == "tasks" and idx_t == st["idx_task"])
                    attr = PAR[est] | (RESALT if sel else 0)
                    txt = "  %s  %s" % (t.get("id", "?"), cortar(t.get("task_title"), maxx - x - 2))
                    an(y, x, txt, maxx - x - 1, attr)
                y += 1

        # --- barra inferior
        std.hline(maxy - 2, 0, "-", maxx)
        if st["inicio"]:
            msj = "worker-start en curso para %s..." % st["inicio"]["tid"]
        else:
            msj = st["msj"]
        an(maxy - 2, 0, msj)
        an(maxy - 1, 0, "[Tab] panel   [Up/Dn] mover   [Enter] ver   [i] iniciar   [s] filtro   [r] refrescar   [q] salir")
        std.refresh()

        # --- entrada
        std.timeout(500)
        ch = std.getch()
        if ch == -1:
            if st["inicio"] is None and time.time() - ultimo_poll > 10:
                ultimo_poll = time.time()
                recargar()
            continue
        ultimo_poll = time.time()
        if ch == ord("q") or ch == 27:
            return
        if ch == ord("r"):
            recargar()
        elif ch == ord("s"):
            orden = [None] + ESTADOS
            st["filtro"] = orden[(orden.index(st["filtro"]) + 1) % len(orden)]
            recargar()
        elif ch == 9 or ch == curses.KEY_RIGHT or ch == curses.KEY_LEFT:  # Tab
            st["foco"] = "tasks" if st["foco"] == "runs" else "runs"
        elif ch == curses.KEY_UP or ch == ord("k"):
            if st["foco"] == "runs":
                st["idx_run"] = max(0, st["idx_run"] - 1)
            else:
                st["idx_task"] = max(0, st["idx_task"] - 1)
        elif ch == curses.KEY_DOWN or ch == ord("j"):
            if st["foco"] == "runs":
                n = max(0, len(st["datos"]) - 1)
                st["idx_run"] = min(n, st["idx_run"] + 1)
            else:
                st["idx_task"] += 1
        elif ch in (curses.KEY_ENTER, 10, 13) and st["foco"] == "tasks" and st["datos"]:
            d = st["datos"][st["idx_run"]]
            items = [it for it in (
                (est, t) for est in ESTADOS for t in d["tasks"] if t.get("status") == est)]
            if st["idx_task"] < len(items):
                _tarea_popup(std, binario, d["run"], items[st["idx_task"]][1], st)
        elif ch == ord("i") and st["foco"] == "tasks" and st["datos"]:
            d = st["datos"][st["idx_run"]]
            items = [it for it in (
                (est, t) for est in ESTADOS for t in d["tasks"] if t.get("status") == est)]
            if st["idx_task"] < len(items):
                tid = items[st["idx_task"]][1]["id"]
                ag = linea("agente [opencode]: ", "") or "opencode"
                if ag:
                    base = linea("base branch (enter = omite): ", "")
                    st["inicio"] = {"tid": tid, "agente": ag, "base": base or None}
                    lanzar(tid)


def _tarea_popup(std, binario, run, t, st):
    """Popup con el detalle de la tarea: spec completa + acciones."""
    import curses
    maxy, maxx = std.getmaxyx()
    ah = min(maxy - 2, 22)
    aw = min(maxx - 2, 100)
    x0 = max(0, (maxx - aw) // 2)
    y0 = max(0, (maxy - ah) // 2)

    def borde(attr=0):
        std.addnstr(y0, x0, "+" + "-" * (aw - 2) + "+", 0, attr)
        for yy in range(y0 + 1, y0 + ah - 1):
            std.addnstr(yy, x0, "|", 0, attr)
            std.addnstr(yy, x0 + aw - 1, "|", 0, attr)
        std.addnstr(y0 + ah - 1, x0, "+" + "-" * (aw - 2) + "+", 0, attr)

    est = t.get("status", "?")
    titulo = " %s  %s " % (t.get("id", "?"), cortar(t.get("task_title"), aw - 18))

    cuerpo = []
    cuerpo.append("run:      %s  %s" % (run["id"], cortar(run.get("objective"), 56)))
    cuerpo.append("estado:   %s" % est)
    deps = t.get("deps") or []
    if isinstance(deps, str):
        deps = [d for d in deps.strip("[]").split(",") if d.strip()]
    cuerpo.append("deps:     %s" % (", ".join(deps) if deps else "(ninguna)"))
    if t.get("parent_id"):
        cuerpo.append("padre:    %s" % t["parent_id"])
    if t.get("created_at"):
        cuerpo.append("creada:   %s" % t["created_at"])
    if t.get("completed_at"):
        cuerpo.append("fin:      %s" % t["completed_at"])
    res = t.get("result")
    if res:
        cuerpo.append("resultado:")
        cuerpo += ["  " + l for l in str(res).splitlines()]
    cuerpo.append("spec:")
    spec = (t.get("spec") or "(sin spec)").splitlines() or ["(sin spec)"]
    cuerpo += ["  " + l for l in spec]
    cuerpo.append("")
    cuerpo.append("  [q] cerrar   (inicia desde la lista con i)")
    despl = 0
    visibles = ah - 3
    while True:
        borde()
        std.addnstr(y0, x0 + 2, titulo, aw - 4, curses.A_BOLD)
        std.addnstr(y0, x0 + aw - len(est) - 2, "[%s]" % est, 0)
        yy = y0 + 1
        for l in cuerpo[despl: despl + visibles]:
            std.addstr(yy, x0 + 1, l[: aw - 2])
            yy += 1
        if len(cuerpo) > visibles:
            std.addnstr(y0 + ah - 1, x0 + 1, "(arriba/abajo para desplazar)")
        std.refresh()
        std.timeout(-1)
        ch = std.getch()
        if ch == ord("q") or ch == 27:
            break
        if ch == curses.KEY_UP:
            despl = max(0, despl - 1)
        if ch == curses.KEY_DOWN:
            despl = min(max(0, len(cuerpo) - visibles), despl + 1)


def tui(args):
    binario = buscar_orca(args.orca)
    import curses
    curses.wrapper(_tui_loop, binario, args.run, args.status)
    return 0


# ---------------------------------------------------------------- Web
HTML_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orca Board</title><style>
:root{color-scheme:light dark}
body{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--fg)}
body{--bg:#f5f6f8;--fg:#1b1f24;--card:#fff;--line:#e2e5e9}
@media(prefers-color-scheme:dark){body{--bg:#101318;--fg:#e6e8ec;--card:#191d23;--line:#2a2f37}}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{font-size:18px;margin:0}
button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
main{padding:16px 20px;display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.col{flex:1 1 240px;min-width:240px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.col h2{font-size:13px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.05em;opacity:.8}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px}
.card b{font-size:13px}
.card p{margin:4px 0 0;font-size:12px;opacity:.75}
.card .id{font-family:ui-monospace,monospace;font-size:11px;opacity:.6}
.card .acc{margin-top:6px}
.run{font-size:11px;opacity:.7;margin-bottom:12px}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;background:#eef2ff;color:#3730a3;margin-left:6px}
</style></head><body>
<header><h1>Orca Board</h1>
<button id="ref" class="ghost">Refrescar</button>
<button id="ini" class="ghost">Iniciar</button>
<label class="run">Run <select id="run"></select></label></header>
<main id="tab"></main>
<div id="pop" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center">
<div style="background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:320px">
<h3 id="pop-t"></h3>
<label>Agente<br><select id="pop-ag"></select></label><br><br>
<label>Base branch (opcional)<br><input id="pop-base" placeholder="dev" style="width:100%"></label><br><br>
<button id="pop-ok">Iniciar worker-start</button> <button id="pop-no" class="ghost">Cancelar</button>
<div id="pop-out" style="font-size:12px;margin-top:8px"></div></div></div>
<div id="det" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);align-items:center;justify-content:center">
<div style="background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;max-width:760px;width:92%;max-height:86vh;overflow:auto">
<h3 id="det-t" style="margin-top:0"></h3>
<div id="det-body" style="font-size:13px;white-space:pre-wrap;word-break:break-word"></div>
<br><button id="det-ok" class="ghost">Cerrar</button></div></div>
<script>
const $=s=>document.querySelector(s);
const ESTADOS=["pending","ready","dispatched","completed","failed","blocked"];
const ETIQ={pending:"Pendiente",ready:"Listas",dispatched:"En curso",completed:"Completadas",failed:"Fallidas",blocked:"Bloqueadas"};
const COLOR={pending:"#94a3b8",ready:"#22c55e",dispatched:"#f59e0b",completed:"#06b6d4",failed:"#ef4444",blocked:"#a855f7"};
let DATOS=null,AGENTES=["opencode","claude","pi","codex"];
async function api(p,rb){const r=await fetch(p);return r.ok?await r.json():null}
async function cargar(){
  const d=await api("/api/tareas");
  if(!d)return;DATOS=d;$("#tab").innerHTML="";
  for(const r of d.runs){
    const secc=document.createElement("section");secc.className="col";secc.style.cssText="flex:1 1 100%";
    const h=document.createElement("h2");h.textContent=r.objective||r.id;secc.appendChild(h);
    const runp=document.createElement("div");runp.className="run";runp.textContent=r.id;secc.appendChild(runp);
    const cols=document.createElement("div");cols.style.cssText="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start";
    for(const est of ESTADOS){
      const ts=(r.tasks||[]).filter(t=>t.status===est);
      const c=document.createElement("div");c.className="col";c.style.borderTop="3px solid "+(COLOR[est]||"#888");
      c.innerHTML="<h2>"+ETIQ[est]+" ("+ts.length+")</h2>";
      for(const t of ts){
        const d=document.createElement("div");d.className="card";d.style.borderLeftColor=COLOR[est]||"#888";
        d.innerHTML="<b>"+esc(t.task_title||t.id)+'</b> <span class="id">'+t.id+"</span>"
          +"<p>"+esc((t.spec||"").slice(0,200))+"</p>"
          +'<div class="acc"><button class="ghost" data-id="'+t.id+'" data-t="'+esc(t.task_title||"")+'" data-ver="1">Ver</button> '
          +'<button class="ghost" data-id="'+t.id+'" data-t="'+esc(t.task_title||"")+'">Iniciar</button></div>';
        c.appendChild(d);
      }
      cols.appendChild(c);
    }
    secc.appendChild(cols);$("#tab").appendChild(secc);
  }
}
function esc(s){return s.replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function tareaPorId(id){
  for(const r of (DATOS||[])){const t=(r.tasks||[]).find(x=>x.id===id);if(t)return {run:r,task:t}}
  return null;
}
function fmtLista(s){
  if(Array.isArray(s))return s.join(", ");
  if(typeof s==="string"&&/^\\[/.test(s.trim())){try{return JSON.parse(s).join(", ")}catch(e){}}
  return s||"";
}
function verDetalle(id){
  const f=tareaPorId(id);if(!f)return;
  const t=f.task,r=f.run;
  const est=t.status||"?";
  const dep=fmtLista(t.deps);
  let b="";
  b+="[estado: "+esc(est)+"]\n";
  b+="run:       "+esc(r.id)+"  "+esc(r.objective||"")+"\n";
  b+="id:        "+esc(t.id)+"\n";
  if(t.parent_id)b+="padre:     "+esc(t.parent_id)+"\n";
  if(t.created_at)b+="creada:    "+esc(t.created_at)+"\n";
  if(t.completed_at)b+="fin:       "+esc(t.completed_at)+"\n";
  b+="deps:      "+esc(dep||"(ninguna)")+"\n";
  if(t.result)b+="resultado: \n"+esc(t.result)+"\n";
  b+="\nDESCRIPCION:\n"+esc(t.spec||"(sin spec)");
  $("#det-t").textContent="Detalle: "+(t.task_title||t.id);
  $("#det-body").textContent=b;
  $("#det").style.display="flex";
}
async function iniciar(id,ag,base){
  const r=await fetch("/api/iniciar",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({id,agente:ag,base:base||null})});
  const out=r.ok?await r.text():"HTTP "+r.status;
  $("#pop-out").textContent=out;
}
$("#tab").addEventListener("click",e=>{
  const b=e.target.closest("button[data-id]");if(!b)return;
  if(b.dataset.ver){verDetalle(b.dataset.id);return;}
  $("#pop").style.display="flex";$("#pop-t").textContent="Iniciar: "+b.dataset.t;
  $("#pop-ag").innerHTML=AGENTES.map(a=>"<option>"+a+"</option>").join("");
  $("#pop-base").value="";$("#pop-out").textContent="";
  $("#pop").dataset.id=b.dataset.id;
});
$("#det-ok").onclick=()=>$("#det").style.display="none";
$("#det").onclick=e=>{if(e.target.id==="det")$("#det").style.display="none"};
$("#pop-ok").onclick=()=>iniciar($("#pop").dataset.id,$("#pop-ag").value,$("#pop-base").value);
$("#pop-no").onclick=()=>$("#pop").style.display="none";
$("#ref").onclick=cargar;
setInterval(cargar,10000);
cargar();
</script></body></html>"""


def web(args):
    binario = buscar_orca(args.orca)
    puerto = args.port or 8766
    dir_m = os.path.dirname(os.path.abspath(__file__))

    def respuesta(handler, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        handler.send_response(codigo)
        handler.send_header("Content-Type", tipo)
        handler.send_header("Content-Length", str(len(cuerpo)))
        handler.end_headers()
        handler.wfile.write(cuerpo)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/":
                respuesta(self, 200, HTML_PAGE.encode(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/tareas"):
                todo = []
                for r in runs(binario):
                    if r.get("legacy"):
                        continue
                    todo.append({"id": r["id"], "objective": r.get("objective"),
                                 "tasks": tareas(binario, r["id"])})
                respuesta(self, 200, json.dumps(todo, ensure_ascii=False).encode())
            else:
                respuesta(self, 404, b"not found", "text/plain")

        def do_POST(self):
            if not self.path.startswith("/api/iniciar"):
                respuesta(self, 404, b"not found", "text/plain")
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            tid = body.get("id")
            if not tid:
                respuesta(self, 400, b"falta id", "text/plain")
                return
            cmd = [binario, "orchestration", "worker-start", "--task", tid, "--json"]
            if body.get("agente"):
                cmd += ["--agent", str(body["agente"])]
            if body.get("base"):
                cmd += ["--base-branch", str(body["base"])]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                salida = proc.stdout.strip() or proc.stderr.strip() or "(sin salida)"
                if proc.returncode == 0:
                    try:
                        salida = json.dumps(json.loads(salida), ensure_ascii=False)
                    except Exception:
                        pass
                respuesta(self, 200 if proc.returncode == 0 else 500,
                          salida.encode(), "text/plain; charset=utf-8")
            except Exception as e:
                respuesta(self, 500, str(e).encode(), "text/plain; charset=utf-8")

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print("orca-board web: http://%s:%d  (Ctrl+C para salir)" %
          ("localhost" if not args.lan else "<ip-de-esta-pc>", puerto))
    ThreadingHTTPServer((host, puerto), H).serve_forever()


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("modo", nargs="?", default="cli")
    p.add_argument("--run")
    p.add_argument("--status")
    p.add_argument("--json", action="store_true")
    p.add_argument("--port", type=int)
    p.add_argument("--lan", action="store_true")
    p.add_argument("--orca")
    p.add_argument("-h", "--help", action="store_true")
    a = p.parse_args()
    if a.help:
        print(__doc__)
        return 0
    if a.modo == "web":
        web(a)
        return 0
    if a.modo == "tui" or (a.modo == "cli" and not a.json and sys.stdout.isatty()):
        # Sin flags y con terminal interactivo: TUI; con --json o pipe: lista simple.
        return tui(a)
    return cli(a)


if __name__ == "__main__":
    sys.exit(main())
