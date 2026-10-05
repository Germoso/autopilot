// tests/test_web_dashboard.js — verificación del dashboard (harness de node con stubs de DOM).
// Correr: node tests/test_web_dashboard.js
//
// Cubre la Fase 1 de la auditoría de UI/UX (y el panel Git de la tarea, caso 9):
//  1. index.html: skip link, main tabindex, avisos con aria-live/role.
//  2. tablero: <h1> de vista; filtros corruptos en localStorage no rompen la vista.
//  3. tarea: aria-label en los botones de edición (✎).
//  4. herramientas: la tabla se actualiza al terminar un trabajo (bug de vistaHerramientasLista).
//  5. tarea: auto-refresco de datos (15 s) sin recargar.
//  6. log: auto-refresco preservando el filtro.
const fs = require("fs");
const path = require("path");

const BASE = path.join(__dirname, "..", "lib", "web", "estatico");
const APP = fs.readFileSync(path.join(BASE, "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(BASE, "index.html"), "utf8");

const fallos = [];
const ok = (cond, msg) => { if (!cond) fallos.push(msg); };
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

let elementos, controles, intervalos, fetches, cfg;

// El DOM real destruye los hijos al reemplazar el innerHTML de #vista: emulamos invalidando el cache.
const CONSERVAR = ["#vista", "#estado-autopilot", "#aviso", "#proyecto", ".skip-link"];

function el(sel) {
  const o = {
    _sel: sel, _html: "", textContent: "", hidden: false, value: "", checked: false,
    onclick: null, oninput: null, onchange: null, dataset: {}, style: {},
    scrollTop: 0, scrollHeight: 0,
    focus() {},
    addEventListener(ev, fn) { (this._ev = this._ev || {})[ev] = fn; },
    removeEventListener() {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, remove() {}, appendChild() {},
  };
  Object.defineProperty(o, "innerHTML", {
    get() { return this._html; },
    set(v) {
      this._html = String(v);
      if (sel === "#vista") {
        for (const k of [...elementos.keys()]) if (!CONSERVAR.includes(k)) elementos.delete(k);
      }
    },
  });
  return o;
}

function resp(o) { return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(o)) }; }

const TAREAS = [{ clave: "task-uno", titulo: "Título A", estado: "done", repo: "jobradar",
  prioridad: "High", intento: "1", actualizado: "2026-10-03", espera: null, depende: "" }];

function nuevoCfg() {
  return {
    tablero: {
      watcher: true, e2e: false, telegram: true, pausa: false, auto_merge: true,
      cadena: { parada: false, pendiente: { done: 0, stopped: 0, en_espera: 0 }, asignables: 0, minutos: null },
      repos: ["jobradar"], estados: ["new", "in-progress", "qa", "validando", "done", "reviewed"],
      capacidad: { coder: 1, qa: 1, e2e: 1 },
      tareas: JSON.parse(JSON.stringify(TAREAS)),
    },
    tarea: {
      clave: "task-uno", estado: "done", titulo: "Título A",
      meta: { prioridad: "High", intento: "1", rama: "task-uno", repo: "jobradar", repos_extra: "", espera: null, depende: "" },
      descripcion: "descripción", criterio: "criterio", adjuntos_md: "", repos_modificados: "", resultado: "ok", motivo: "",
      entradas: [], adjuntos: [], log: [], borradores: { qa: false, e2e: false },
    },
    logFilas: [{ hora: "2026-10-03T10:00", origen: "sistema", tarea: "-", evento: "Evento antiguo", detalle: "" }],
    trabajos: [],
    git: { clave: "task-uno", estado: "done", rama: "task-uno", repos: [{
      repo: "jobradar", base: "dev", rama: "task-uno", existe_rama: true, integrada: false, modificada: true, pr: null, avisos: [],
      remoto: { tipo: "azure", url: "https://dev.azure.com/o/p/_git/r" }, base_vs_origin: { adelante: 0, atras: 0 },
      commits: [{ hash: "abc123", asunto: "agrega app", autor: "Coder", fecha: "2026-10-05T10:00:00" }],
      archivos: [{ ruta: "src/app.txt", estado: "A", binario: false, mas: 2, menos: 0 }] }] },
    trabajo: { que: "health", rc: null, salida: "", inicio: "10:00" },
  };
}

async function cargar(hash, opts = {}) {
  cfg = opts.cfg || nuevoCfg();
  elementos = new Map();
  controles = {
    "[data-correr]": [el("c0", { dataset: { correr: "health" } }), el("c1", { dataset: { correr: "run-tests" } })],
    "[data-ver]": [],
  };
  intervalos = [];
  fetches = [];
  global.localStorage = {
    store: Object.assign({}, opts.store),
    getItem: (k) => (k in global.localStorage.store ? global.localStorage.store[k] : null),
    setItem: (k, v) => { global.localStorage.store[k] = v; },
  };
  global.location = { hash };
  global.document = {
    querySelector: (s) => { if (!elementos.has(s)) elementos.set(s, el(s)); return elementos.get(s); },
    querySelectorAll: (s) => controles[s] || [],
    addEventListener() {}, hidden: false, activeElement: null, body: el("body"),
  };
  global.window = globalThis;
  global.setInterval = (fn, ms) => { intervalos.push({ fn, ms }); };
  global.Markdown = { esc: (s) => String(s), render: (t) => String(t) };
  global.fetch = async (u) => {
    const s = String(u);
    fetches.push(s);
    if (s === "/api/sesion") return resp({ ok: true });
    if (s === "/api/proyectos") return resp([{ id: "p1", nombre: "jobradar" }]);
    if (s.includes("/p1/tarea/")) return resp(cfg.tarea);
    if (s.includes("/p1/git/")) return resp(cfg.git);
    if (s.includes("/p1/log")) return resp(cfg.logFilas);
    if (s.includes("/p1/trabajos")) return resp(cfg.trabajos);
    if (s.includes("/p1/trabajo/")) return resp(cfg.trabajo);
    if (s.includes("/p1/correr")) { cfg.trabajos = [{ id: "x", que: "health", rc: null, inicio: "10:00" }]; return resp({ ok: true, id: "x" }); }
    if (s.includes("/p1/tablero")) return resp(cfg.tablero);
    return resp({});
  };
  eval(APP);
  await esperar(150);   // iniciar() -> ruta() -> vista
}

const tick = () => { const i = intervalos.find((x) => x.ms === 15000); ok(!!i, "no hay tick de refresco de 15s"); return i && i.fn(); };

(async () => {
  // 1) index.html accesibilidad estatica + handler del skip link
  ok(/class="skip-link"/.test(HTML), "index.html: falta el skip link");
  ok(/<main id="vista" tabindex="-1"/.test(HTML), "index.html: main sin tabindex (skip link inutil)");
  ok(/aria-live="polite"/.test(HTML) && /role="status"/.test(HTML), "index.html: #aviso sin aria-live/role");
  await cargar("#/");
  const sl = elementos.get(".skip-link");
  ok(!!(sl && sl._ev && sl._ev.click), "app.js: skip link sin handler (romperia el hash routing)");

  // 2) tablero: h1 de vista
  ok(el0("#vista").includes('<h1'), "tablero: sin <h1> de vista");
  ok(el0("#vista").includes("vista-titulo"), "tablero: sin clase de titulo de vista");

  // 3) filtros corruptos no rompen la vista
  await cargar("#/", { store: { filtros: "{corrompido" } });
  ok(!el0("#vista").includes("❌"), "filtros corruptos: el tablero se rompe");
  ok(el0("#vista").includes('<h1'), "filtros corruptos: no se pudo pintar el tablero");

  // 4) tarea: aria-label en ediciones
  await cargar("#/tarea/task-uno");
  const vt = el0("#vista");
  ok(vt.includes('aria-label="Editar título"'), "tarea: botón ✎ título sin aria-label");
  ok(vt.includes('aria-label="Editar descripción"'), "tarea: botón ✎ descripción sin aria-label");
  ok(vt.includes('aria-label="Editar criterio de aceptación"'), "tarea: botón ✎ criterio sin aria-label");

  // 5) herramientas: la tabla se actualiza al terminar el trabajo
  await cargar("#/herramientas");
  ok(el0("#trabajos").includes("Nada corrió"), "herramientas: estado inicial vacío incorrecto");
  await controles["[data-correr]"][0].onclick();   // Correr health check
  await esperar(150);
  ok(el0("#trabajos").includes("corriendo"), "herramientas: no refleja el trabajo iniciado");
  cfg.trabajos[0].rc = 0;
  cfg.trabajo.rc = 0;
  await esperar(2000);                               // el seguimiento reactiva a los 1500ms
  ok(el0("#trabajos").includes("✅ ok"), "herramientas: la tabla no se actualiza al terminar el trabajo");

  // 6) tarea: auto-refresco de datos
  await cargar("#/tarea/task-uno");
  ok(el0("#vista").includes("Título A"), "tarea: no se pintó el título inicial");
  cfg.tarea.titulo = "Título renovado";
  await tick();
  await esperar(200);
  ok(el0("#vista").includes("Título renovado"), "tarea: no se auto-refrescan los datos");

  // 7) log: auto-refresco preservando el filtro (las filas viven en #l-tabla)
  await cargar("#/log");
  ok(el0("#l-tabla").includes("Evento antiguo"), "log: no se pintó el log inicial");
  elementos.get("#l-texto").value = "nuevo";
  cfg.logFilas = [{ hora: "2026-10-03T10:05", origen: "sistema", tarea: "-", evento: "Evento nuevo", detalle: "" }];
  await tick();
  await esperar(200);
  ok(el0("#l-tabla").includes("Evento nuevo"), "log: no se auto-refresca");
  ok(elementos.get("#l-texto").value === "nuevo", "log: se pierde el filtro al refrescar");

  // 8) tablero: refresco refleja cambios de datos sin recargar (barra, columnas y banner de cadena)
  const ct = nuevoCfg();
  ct.tablero.cadena = { parada: true, pendiente: { done: 3, stopped: 0, en_espera: 0 }, asignables: 0, minutos: 5 };
  await cargar("#/", { cfg: ct });
  ok(el0("#avisos").includes("Cadena detenida"), "tablero: no se muestra el banner de cadena");
  cfg.tablero.watcher = false;
  cfg.tablero.cadena = { parada: false, pendiente: { done: 0, stopped: 0, en_espera: 0 }, asignables: 0, minutos: null };
  cfg.tablero.tareas.push({ clave: "task-nueva", titulo: "Recién creada", estado: "new", repo: "jobradar",
    prioridad: "Medium", intento: "0", actualizado: "2026-10-03", espera: null, depende: "" });
  await tick();
  await esperar(200);
  ok(elementos.get("#estado-autopilot").innerHTML.includes("watcher detenido"), "tablero: la barra no refleja el cambio");
  ok(el0("#columnas").includes("task-nueva"), "tablero: las columnas no se repintan");
  ok(!el0("#avisos").includes("Cadena detenida"), "tablero: el banner de cadena no se quita al destrabarse");
  ok(global.location.hash === "#/", "el refresco navega sin querer (hash cambió)");

  // 9) tarea: panel Git (commits, archivos y botones según el estado)
  await cargar("#/tarea/task-uno");
  await esperar(100);
  const g = el0("#panel-git");
  ok(g.includes("agrega app") && g.includes("src/app.txt") && g.includes("+2"), "git: no muestra commits/archivos");
  ok(g.includes("Mergear a la base") && g.includes("Crear PR"), "git: faltan los botones de merge/PR en done");
  ok(!g.includes("Push de la base"), "git: muestra push sin nada que subir");
  ok(g.includes("Push de las ramas"), "git: falta el push de las ramas modificadas sin publicar");
  ok(fetches.filter((u) => u.includes("/p1/git/")).length === 1, "git: no se pidió el estado git una sola vez");
  await tick();
  await esperar(200);
  ok(fetches.filter((u) => u.includes("/p1/git/")).length === 1, "git: el refresco automático vuelve a pedir git");
  ok(el0("#panel-git").includes("src/app.txt"), "git: el refresco borra el panel");
  const cq = nuevoCfg();
  cq.tarea.estado = "qa"; cq.git.estado = "qa";
  cq.git.repos[0].base_vs_origin = { adelante: 2, atras: 0 };
  await cargar("#/tarea/task-uno", { cfg: cq });
  await esperar(100);
  ok(!el0("#panel-git").includes("Mergear a la base"), "git: deja mergear una tarea que no está en done/reviewed");
  ok(el0("#panel-git").includes("2 sin subir"), "git: no avisa la base sin subir");
  const cp = nuevoCfg();
  cp.git.repos[0].rama_vs_origin = { adelante: 0, atras: 0 };
  await cargar("#/tarea/task-uno", { cfg: cp });
  await esperar(100);
  ok(!el0("#panel-git").includes("Push de las ramas"), "git: ofrece push de una rama ya publicada")

  if (fallos.length) {
    console.error("FALLÓ " + fallos.length + ":");
    for (const f of fallos) console.error(" - " + f);
    process.exit(1);
  }
  console.log("OK: dashboard (accesibilidad, bug herramientas, refresco) — 9/9");
})().catch((e) => { console.error("ERROR:", e.stack || e.message); process.exit(1); });

function el0(sel) { const e = elementos.get(sel); return e ? e.innerHTML : ""; }
