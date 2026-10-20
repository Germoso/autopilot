#!/usr/bin/env python3
"""orca-board — tablero agnostico de tareas de Orca (orchestration).

Lee las tareas directamente del CLI de Orca (`orca orchestration task-list/run-list`),
asi funciona con CUALQUIER agente (pi, opencode, claude, codex...) y desde cualquier
dispositivo. Orca sigue siendo la unica fuente de verdad; esto solo la muestra.

Uso:
  orca-board                     lista todas las runs y sus tareas por estado
  orca-board --run <id>          solo esa run
  orca-board --status <est>      filtra por estado (ready, dispatched, completed, ...)
  orca-board --json              salida JSON cruda (para scripts / otros agentes)
  orca-board web [--port N]      servidor web: tarjetas por estado + iniciar tarea
  orca-board web --lan           expuesto a la red local (celular, otra PC)
  orca-board --orca <ruta>       usa otro binario de orca (por defecto: el del PATH)

Sin dependencias: solo stdlib. El binario de orca se busca en el PATH, en ORCA_CLI_BIN_DIR
o en ~/.orca/cli/bin/orca.
"""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
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
<script>
const $=s=>document.querySelector(s);
const ESTADOS=["pending","ready","dispatched","completed","failed","blocked"];
const ETIQ={pending:"Pendiente",ready:"Listas",dispatched:"En curso",completed:"Completadas",failed:"Fallidas",blocked:"Bloqueadas"};
const COLOR={pending:"#94a3b8",ready:"#22c55e",dispatched:"#f59e0b",completed:"#06b6d4",failed:"#ef4444",blocked:"#a855f7"};
let DATOS=null,AGENTES=["opencode","claude","pi","codex"];
async function api(p,rb){const r=await fetch(p);return r.ok?await r.json():null}
async function cargar(){
  const d=await api("/api/tareas");
  if(!d)return;$("#tab").innerHTML="";
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
          +'<div class="acc"><button class="ghost" data-id="'+t.id+'" data-t="'+esc(t.task_title||"")+'">Iniciar</button></div>';
        c.appendChild(d);
      }
      cols.appendChild(c);
    }
    secc.appendChild(cols);$("#tab").appendChild(secc);
  }
}
function esc(s){return s.replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
async function iniciar(id,ag,base){
  const r=await fetch("/api/iniciar",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({id,agente:ag,base:base||null})});
  const out=r.ok?await r.text():"HTTP "+r.status;
  $("#pop-out").textContent=out;
}
$("#tab").addEventListener("click",e=>{
  const b=e.target.closest("button[data-id]");if(!b)return;
  $("#pop").style.display="flex";$("#pop-t").textContent="Iniciar: "+b.dataset.t;
  $("#pop-ag").innerHTML=AGENTES.map(a=>"<option>"+a+"</option>").join("");
  $("#pop-base").value="";$("#pop-out").textContent="";
  $("#pop").dataset.id=b.dataset.id;
});
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
    return cli(a)


if __name__ == "__main__":
    sys.exit(main())
