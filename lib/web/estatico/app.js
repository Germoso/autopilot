// app.js — app web del autopilot (sin dependencias). Rutas: #/ tablero · #/tarea/<clave> · #/nueva ·
// #/herramientas · #/pruebas · #/prueba/<archivo> · #/log
(function () {
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = Markdown.esc;
  const ESTADO_NOMBRE = { "new": "Nuevas", "in-progress": "Coder trabajando", "qa": "Cola QA", "validando": "QA certificando",
    "e2e": "Cola E2E", "probando-e2e": "E2E probando", "bug-fix": "Bug-fix", "stopped": "Detenidas", "done": "Listas (revisar)",
    "reviewed": "Revisadas" };
  const TIPO_NOMBRE = { notas_dev: "Notas del desarrollador", reporte_qa: "Reporte de QA", feedback_qa: "Feedback de QA",
    reporte_e2e: "Reporte E2E", feedback_e2e: "Feedback de E2E" };
  const ORDEN_TIPO = ["notas_dev", "reporte_qa", "feedback_qa", "reporte_e2e", "feedback_e2e"];
  const PASO_ADJUNTO = { original: "Tarea original", humano: "Subidos por ti", coder: "Coder", qa: "QA", e2e: "E2E" };
  let proyectos = [], pid = null, tablero = null;
  const REFRESCO_SEG = 15;                  // refresco automatico de la web (s)
  let vistaActual = "", pintarTablero = null, refrescoEnVuelo = false;
  let editando = false, intentoSel = null, tareaActual = null;
  // Panel Git de la tarea abierta: se pide aparte (no frena la vista) y sobrevive al refresco automatico.
  let gitDatos = null, gitAbiertos = {}, gitOcupado = false, gitResultado = "";

  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin storage */ } };
  const leer = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const leerJSON = (k, def) => { try { return JSON.parse(leer(k)) || def; } catch (e) { return def; } };

  // Navega a un hash: si es identico al actual no hay hashchange, asi que llamamos a ruta() a mano.
  function ir(h) {
    if (location.hash !== h) location.hash = h;
    else ruta();
  }

  function aviso(txt, ms) {
    const el = $("#aviso");
    el.textContent = txt; el.hidden = false;
    clearTimeout(aviso.t); aviso.t = setTimeout(() => (el.hidden = true), ms || 3500);
  }

  async function api(ruta, datos) {
    const op = { headers: { "X-Autopilot": "1" }, credentials: "same-origin" };
    if (datos !== undefined) { op.method = "POST"; op.headers["Content-Type"] = "application/json"; op.body = JSON.stringify(datos); }
    const r = await fetch(ruta, op);
    if (r.status === 401) { login(); throw new Error("sin sesion"); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || j.salida || ("error " + r.status));
    return j;
  }
  const papi = (sub, datos) => api("/api/p/" + pid + "/" + sub, datos);

  const archivoUrl = (ruta, base) => "/api/p/" + pid + "/archivo?" + (base ? "base=" + base + "&" : "") + "ruta=" + encodeURIComponent(ruta);
  function resolverTablero(u) {
    const i = u.indexOf("adjuntos/");
    if (i >= 0 && !/^https?:/.test(u)) return archivoUrl(u.slice(i));
    return u;
  }
  const md = (texto, resolver) => '<div class="md">' + Markdown.render(texto || "", resolver || resolverTablero) + "</div>";
  // Texto de una tarea: las imagenes van referenciadas (`📷 nombre.png`), no incrustadas. Cada 📷 pasa a
  // un chip que abre esa imagen en el visor (se busca primero en `preferidos`, el intento de la entrada).
  const RE_REF = /📷 ([\w.-]+?\.(?:png|jpe?g|gif|webp|bmp|svg))(?![\w.])/gi;
  function mdTarea(texto, todos, preferidos) {
    const buscar = (n) => (preferidos || []).concat(todos || []).find((a) => a.ruta.split("/").pop() === n);
    return md(RE_LINEA_CARPETA_QUITAR(texto)).replace(RE_REF, (m, n) => {
      const a = buscar(n);
      return a ? '<button type="button" class="ref-img" data-src="' + esc(archivoUrl(a.ruta)) + '">📷 ' + esc(n) + "</button>" : m;
    });
  }
  // La linea `📎 N capturas → carpeta/` es para el .md; en la web la reemplaza la galeria del intento.
  const RE_LINEA_CARPETA_QUITAR = (t) => (t || "").replace(/^📎 .*$/gm, "").trim();
  const ORIGEN_TIPO = { notas_dev: "coder", reporte_qa: "qa", reporte_e2e: "e2e" };

  function login() {
    $("#vista").innerHTML = '<div class="panel login"><h1 class="vista-titulo">Clave de acceso</h1><p class="vacio">Está en ~/.config/autopilot-kit/web.env de la máquina del autopilot.</p>' +
      '<form id="f-login" class="formulario"><label for="clave">Clave de acceso</label>' +
      '<input id="clave" name="clave" type="password" autocomplete="current-password" aria-label="Clave de acceso" required><button class="primario">Entrar</button></form></div>';
    $("#f-login").onsubmit = async (e) => {
      e.preventDefault();
      try { await api("/api/login", { clave: $("#clave").value }); iniciar(); } catch (err) { aviso(err.message); }
    };
  }

  async function iniciar() {
    const s = await (await fetch("/api/sesion", { credentials: "same-origin" })).json();
    if (!s.ok) return login();
    proyectos = await api("/api/proyectos");
    const sel = $("#proyecto");
    sel.innerHTML = proyectos.map((p) => '<option value="' + p.id + '">' + esc(p.nombre) + "</option>").join("");
    pid = proyectos.some((p) => p.id === leer("proyecto")) ? leer("proyecto") : (proyectos[0] || {}).id;
    sel.value = pid || "";
    sel.onchange = () => { pid = sel.value; guardar("proyecto", pid); location.hash = "#/"; ruta(); };
    if (!pid) { $("#vista").innerHTML = '<div class="panel">No hay proyectos. Corre <code>/autopilot-init</code> en uno.</div>'; return; }
    window.onhashchange = ruta;
    ruta();
    setInterval(refrescar, REFRESCO_SEG * 1000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refrescar(); });
  }

  async function ruta() {
    const h = location.hash.replace(/^#\/?/, "");
    vistaActual = h.split("/")[0] || "tablero";
    document.querySelectorAll(".barra nav a").forEach((a) => a.classList.toggle("activo", a.getAttribute("href") === "#/" + h.split("/")[0]));
    try {
      await estadoAutopilot();
      if (h.startsWith("tarea/")) return vistaTarea(h.slice(6));
      if (h === "nueva") return vistaNueva();
      if (h === "herramientas") return vistaHerramientas();
      if (h === "pruebas") return vistaPruebas();
      if (h.startsWith("prueba/")) return vistaPrueba(decodeURIComponent(h.slice(7)));
      if (h === "log") return vistaLog();
      return vistaTablero();
    } catch (e) { if (e.message !== "sin sesion") $("#vista").innerHTML = '<div class="panel">❌ ' + esc(e.message) + "</div>"; }
  }

  async function estadoAutopilot() {
    tablero = await papi("tablero");
    pintarEstado();
  }

  function pintarEstado() {
    const el = $("#estado-autopilot");
    if (!el) return;
    const hora = new Date().toLocaleTimeString();
    el.innerHTML = '<span class="punto ' + (tablero.watcher ? "ok" : "mal") + '"></span>' + (tablero.watcher ? "watcher corriendo" : "watcher detenido") +
      (tablero.e2e ? ' · <span class="chip">E2E</span>' : "") + (tablero.telegram ? '<span class="chip">Telegram</span>' : "") +
      (tablero.auto_merge ? '<span class="chip" title="Al aprobar: merge automatico de la rama a la base (local)">AUTO_MERGE</span>' : "") +
      (tablero.cadena && tablero.cadena.parada ? ' <span class="chip mal" title="Esperando tu revision">🧊 cadena detenida</span>' : "") +
      ' <button id="b-pausa">' + (tablero.pausa ? "▶️ Seguir" : "⏸️ Pausar") + "</button>" +
      ' <span class="vacio" id="actualizado" title="Ultima actualizacion">🔄 ' + hora + "</span>";
    const bp = $("#b-pausa");
    if (!bp) return;
    bp.onclick = async () => {
      await papi("pausa", { pausa: !tablero.pausa });
      aviso(tablero.pausa ? "Seguimos: se toman tareas" : "Pausado: no se toman tareas nuevas");
      ruta();
    };
  }

  async function refrescar() {
    // Refresco automatico: la barra siempre; tablero preserva filtros; tarea/log/herramientas se
    // actualizan sin pisar lo que el usuario este haciendo (edicion o filtro en curso).
    if (document.hidden || refrescoEnVuelo || !pid) return;
    refrescoEnVuelo = true;
    const v = vistaActual;
    try {
      tablero = await papi("tablero");
      if (vistaActual !== v) return;          // navego mientras esperabamos
      pintarEstado();
      if (v === "tablero") {
        if (pintarTablero && $("#columnas")) pintarTablero();
      } else if (v === "tarea") {
        if (!editando && !gitOcupado) await refrescarTarea();
      } else if (v === "log") {
        await refrescarLog();
      } else if (v === "herramientas") {
        await pintarTrabajos();
      }
    } catch (e) { /* sin red o server ocupado: se reintenta en la proxima vuelta */ }
    finally { refrescoEnVuelo = false; }
  }

  async function refrescarTarea() {
    const clave = location.hash.replace(/^#\/tarea\//, "");
    if (!clave) return;
    const y = window.scrollY || 0;
    await vistaTarea(clave);
    if (window.scrollTo) window.scrollTo(0, y);
  }

  async function refrescarLog() {
    const antes = $("#l-texto");
    if (antes && document.activeElement === antes) return;   // no pisar mientras escribe
    const f = (antes && antes.value) || "";
    await vistaLog();
    const inp = $("#l-texto");
    if (inp && f) { inp.value = f; if (inp.oninput) inp.oninput(); }
  }

  // ---------------------------------------------------------------- tablero
  function vistaTablero() {
    const f = leerJSON("filtros", {});
    const repos = tablero.repos;
    $("#vista").innerHTML =
      '<h1 class="vista-titulo">Tablero</h1>' +
      '<div class="filtros"><input id="f-texto" placeholder="Buscar por clave o título…" aria-label="Buscar tareas" value="' + esc(f.texto || "") + '">' +
      '<select id="f-repo"><option value="">Todos los repos</option>' + repos.map((r) => "<option" + (f.repo === r ? " selected" : "") + ">" + esc(r) + "</option>").join("") + "</select>" +
      '<select id="f-prio"><option value="">Toda prioridad</option>' + ["Critical", "High", "Medium", "Low"].map((p) => "<option" + (f.prio === p ? " selected" : "") + ">" + p + "</option>").join("") + "</select>" +
      '<label><input type="checkbox" id="f-rev"' + (f.rev ? " checked" : "") + "> Mostrar revisadas</label>" +
      '<label><input type="checkbox" id="f-vacias"' + (f.vacias ? " checked" : "") + "> Columnas vacías</label></div>" +
      '<div class="resumen" id="resumen"></div>' +
      '<div id="avisos"></div>' +
      '<div class="tablero" id="columnas"></div>';
    const pintar = () => {
      const texto = $("#f-texto").value.toLowerCase(), repo = $("#f-repo").value, prio = $("#f-prio").value, rev = $("#f-rev").checked,
        vacias = $("#f-vacias").checked;
      guardar("filtros", JSON.stringify({ texto, repo, prio, rev, vacias }));
      $("#avisos").innerHTML =
        (tablero.cadena && tablero.cadena.parada ? cadenaPanel(tablero.cadena) : "") +
        (tablero.pausa ? '<div class="panel">⏸️ <strong>En pausa:</strong> el autopilot no toma tareas nuevas.</div>' : "");
      const ts = tablero.tareas.filter((t) => (!texto || (t.clave + " " + t.titulo).toLowerCase().includes(texto)) &&
        (!repo || t.repo === repo || (t.repos_extra || "").includes(repo)) && (!prio || t.prioridad === prio));
      const estados = tablero.estados.filter((e) => (e !== "e2e" && e !== "probando-e2e") || tablero.e2e).filter((e) => rev || e !== "reviewed");
      const cuenta = (e) => ts.filter((t) => t.estado === e).length;
      $("#resumen").innerHTML = estados.filter(cuenta).map((e) => '<span class="chip' + (e === "stopped" ? " mal" : e === "done" ? " ok" : "") + '">' +
        esc(ESTADO_NOMBRE[e] || e) + ": " + cuenta(e) + "</span>").join("") || '<span class="vacio">No hay tareas con esos filtros.</span>';
      $("#columnas").innerHTML = estados.filter((e) => vacias || cuenta(e)).map((e) => {
        const lista = ts.filter((t) => t.estado === e).sort((a, b) => (b.actualizado || "").localeCompare(a.actualizado || ""));
        return '<section class="columna"><h3>' + esc(ESTADO_NOMBRE[e] || e) + "<span>" + lista.length + "</span></h3>" +
          (lista.map(tarjeta).join("") || '<p class="vacio">—</p>') + "</section>";
      }).join("");
    };
    ["#f-texto", "#f-repo", "#f-prio", "#f-rev", "#f-vacias"].forEach((s) => ($(s).oninput = pintar));
    pintarTablero = pintar;
    pintar();
  }
  function cadenaPanel(c) {
    const p = c.pendiente || {};
    const partes = [];
    if (p.done) partes.push(p.done + " en done sin revisar");
    if (p.en_espera) partes.push(p.en_espera + " bloqueadas por dependencias");
    if (p.stopped) partes.push(p.stopped + " en stopped");
    return '<div class="panel" style="border-color:var(--mal)">🧊 <strong>Cadena detenida' + (c.minutos ? " hace " + c.minutos + " min" : "") +
      ':</strong> esperando tu revisión — ' + esc(partes.join(" · ") || "sin detalle") + '. <a href="#/log">Ver log</a></div>';
  }
  function tarjeta(t) {
    return '<a class="tarjeta" href="#/tarea/' + t.clave + '"><div class="clave"><span>' + t.clave + '</span><span class="chip ' + t.prioridad + '">' + t.prioridad + "</span></div>" +
      '<div class="titulo">' + esc(t.titulo) + "</div>" +
      '<div class="clave"><span>' + esc(t.repo || "") + (t.repos_extra ? " +" + esc(t.repos_extra) : "") + "</span><span>" + (t.intento !== "0" ? "intento " + esc(t.intento) : "") + "</span></div>" +
      (t.espera ? '<span class="chip aviso">espera a ' + esc(t.espera) + "</span>" : "") +
      (t.depende ? '<span class="chip">depende de ' + esc(t.depende) + "</span>" : "") + "</a>";
  }

  // ---------------------------------------------------------------- tarea
  async function vistaTarea(clave) {
    const t = await papi("tarea/" + clave);
    if (tareaActual !== clave) { tareaActual = clave; intentoSel = null; gitDatos = null; gitAbiertos = {}; gitResultado = ""; }
    editando = false;
    const e = t.estado, m = t.meta;
    const acciones = [];
    if (["done", "reviewed"].includes(e)) acciones.push(["cambios", "✏️ Pedir cambios"]);
    if (["stopped", "done", "reviewed", "bug-fix", "new"].includes(e)) acciones.push(["reqa", "↺ Devolver a QA"]);
    if (tablero.e2e && ["stopped", "done", "reviewed", "bug-fix"].includes(e)) acciones.push(["re-e2e", "↺ Devolver a E2E"]);
    if (e === "done") acciones.push(["reviewed", "✓ Marcar revisada"]);
    if (!["new", "reviewed"].includes(e)) acciones.push(["new", "Volver a nuevas"]);
    if (!["stopped", "reviewed"].includes(e)) acciones.push(["stop", "⛔ Detener"]);
    const porIntento = {};
    t.entradas.forEach((x) => { const k = x.intento === null ? "—" : x.intento; (porIntento[k] = porIntento[k] || []).push(x); });
    const intentos = Object.keys(porIntento).sort((a, b) => (a === "—") - (b === "—") || b - a);
    // Adjuntos por paso (mismo orden que `wi.sh get <clave> adjuntos`): tarea original, humano, y cada
    // paso en el orden en que ocurrio (coder intento 0 -> QA 1 -> E2E 1 -> coder 1 -> QA 2 ...).
    const grupos = {};
    t.adjuntos.forEach((a) => {
      const o = a.origen || "original", n = a.intento || 0;
      const g = ["coder", "qa", "e2e"].includes(o)
        ? { orden: [2, o === "coder" ? n + 1 : n, ["coder", "qa", "e2e"].indexOf(o)], nombre: PASO_ADJUNTO[o] + " · intento " + n, origen: o }
        : { orden: [o === "original" ? 0 : 1, 0, 0], nombre: PASO_ADJUNTO[o] || o, origen: o };
      (grupos[g.nombre] = grupos[g.nombre] || Object.assign(g, { lista: [] })).lista.push(a);
    });
    const listaGrupos = Object.values(grupos).sort((x, y) => x.orden[0] - y.orden[0] || x.orden[1] - y.orden[1] || x.orden[2] - y.orden[2]);
    const origenes = [...new Set(listaGrupos.map((g) => g.origen))];
    const originales = t.adjuntos.filter((a) => !["coder", "qa", "e2e"].includes(a.origen));
    const ultimoGrupo = listaGrupos[listaGrupos.length - 1];
    const figura = (a) => "<figure>" + (a.tipo === "video" ? '<video src="' + archivoUrl(a.ruta) + '" preload="metadata" controls></video>' :
      a.tipo === "imagen" ? '<img src="' + archivoUrl(a.ruta) + '" loading="lazy" alt="">' : '<a class="boton" href="' + archivoUrl(a.ruta) + '" target="_blank" rel="noopener">📄 abrir</a>') +
      "<figcaption>" + esc(a.ruta.split("/").pop()) + "</figcaption></figure>";
    const htmlGrupo = (g) => {
      const frames = g.lista.filter((a) => /\.frames\//.test(a.ruta)), resto = g.lista.filter((a) => !/\.frames\//.test(a.ruta));
      const abierto = !["coder", "qa", "e2e"].includes(g.origen) || g === ultimoGrupo;
      return '<details class="grupo-adjuntos" data-origen="' + esc(g.origen) + '"' + (abierto ? " open" : "") + "><summary>" + esc(g.nombre) + ' <span class="vacio">(' + g.lista.length + ")</span></summary>" +
        '<div class="galeria">' + resto.map(figura).join("") + "</div>" +
        (frames.length ? "<details><summary>Fotogramas de videos (" + frames.length + ')</summary><div class="galeria">' + frames.map(figura).join("") + "</div></details>" : "") + "</details>";
    };
    $("#vista").innerHTML =
      '<div class="panel"><div class="cabecera-tarea"><div><div class="clave vacio">' + clave + " · " + esc(ESTADO_NOMBRE[e] || e) + "</div>" +
      '<h1 id="t-titulo">' + esc(t.titulo) + ' <button data-editar="titulo" title="Editar título" aria-label="Editar título">✎</button></h1>' +
      '<div style="margin-top:6px"><select id="t-prio">' + ["Critical", "High", "Medium", "Low"].map((p) => "<option" + (m.prioridad === p ? " selected" : "") + ">" + p + "</option>").join("") + "</select> " +
      '<span class="chip">intento ' + esc(m.intento || "0") + '</span><span class="chip">rama ' + esc(m.rama || clave) + '</span><span class="chip">' + esc(m.repo || "-") + (m.repos_extra ? " + " + esc(m.repos_extra) : "") + "</span>" +
      (m.espera ? '<span class="chip aviso">espera a ' + esc(m.espera) + "</span>" : "") +
      (m.depende ? '<span class="chip" title="El coder la toma cuando estas estén en reviewed (mergeadas)">depende de ' + esc(m.depende) + "</span>" : "") +
      (t.borradores.qa || t.borradores.e2e ? '<span class="chip">borrador de pruebas: ' + ["qa", "e2e"].filter((k) => t.borradores[k]).join(", ") + "</span>" : "") +
      '</div></div><div class="acciones">' + acciones.map(([a, n]) => '<button data-accion="' + a + '"' + (a === "stop" ? ' class="peligro"' : "") + ">" + n + "</button>").join("") + "</div></div></div>" +
      (t.motivo ? '<div class="panel" style="border-color:var(--mal)"><h2>⛔ Motivo de detención</h2>' + md(t.motivo) + "</div>" : "") +
      (t.resultado ? '<div class="panel"><h2>Resultado</h2>' + md(t.resultado) + "</div>" : "") +
      '<div class="dos"><div class="panel"><h2>Descripción <button data-editar="descripcion" title="Editar descripción" aria-label="Editar descripción">✎</button></h2>' + mdTarea(t.descripcion, t.adjuntos, originales) + "</div>" +
      '<div class="panel"><h2>Criterio de aceptación <button data-editar="criterio" title="Editar criterio de aceptación" aria-label="Editar criterio de aceptación">✎</button></h2>' + mdTarea(t.criterio, t.adjuntos, originales) + "</div></div>" +
      (t.repos_modificados ? '<div class="panel"><h2>Repos modificados</h2>' + md(t.repos_modificados) + "</div>" : "") +
      '<div class="panel" id="panel-git"></div>' +
      '<div class="panel"><h2>Historial por intento</h2>' + (intentos.length ?
        '<div class="intentos">' + intentos.map((k, i) => '<button data-intento="' + k + '"' + (i === 0 ? ' class="activo"' : "") + ">" + (k === "—" ? "Otros" : "Intento " + k) + "</button>").join("") + '</div><div id="historial"></div>'
        : '<p class="vacio">Todavía no hay notas ni reportes.</p>') + "</div>" +
      '<div class="panel"><h2>Adjuntos (' + t.adjuntos.length + ")</h2>" +
      (origenes.length > 1 ? '<div class="intentos" id="filtro-adjuntos"><button data-origen="" class="activo">Todos</button>' +
        origenes.map((o) => '<button data-origen="' + esc(o) + '">' + esc(PASO_ADJUNTO[o] || o) + "</button>").join("") + "</div>" : "") +
      (listaGrupos.map(htmlGrupo).join("") || '<p class="vacio">Sin adjuntos.</p>') +
      '<p><label class="boton">📎 Subir archivos<input id="t-subir" type="file" multiple hidden></label></p></div>' +
      '<div class="panel"><details><summary>Log de la tarea (' + t.log.length + ')</summary><div class="tabla-scroll"><table class="tabla"><tr><th>Hora</th><th>Quién</th><th>Evento</th><th>Detalle</th></tr>' +
      t.log.map((l) => "<tr><td>" + esc((l.hora || "").replace("T", " ").slice(0, 16)) + "</td><td>" + esc(l.origen) + "</td><td>" + esc(l.evento) + "</td><td>" + esc(l.detalle || "") + "</td></tr>").join("") +
      "</table></div></details></div>";

    const propios = (x) => t.adjuntos.filter((a) => a.origen === ORIGEN_TIPO[x.tipo] && x.intento !== null && Number(a.intento) === Number(x.intento));
    const galeriaEntrada = (x) => {
      const l = propios(x);
      return l.length ? '<details class="galeria-entrada"><summary>📎 ' + l.length + (l.length === 1 ? " captura" : " capturas") +
        '</summary><div class="galeria">' + l.map(figura).join("") + "</div></details>" : "";
    };
    const pintarIntento = (k) => {
      intentoSel = k;   // sobrevive al refresco automatico
      document.querySelectorAll("[data-intento]").forEach((b) => b.classList.toggle("activo", b.dataset.intento === k));
      const es = porIntento[k].slice().sort((a, b) => ORDEN_TIPO.indexOf(a.tipo) - ORDEN_TIPO.indexOf(b.tipo));
      $("#historial").innerHTML = es.map((x) => {
        const ver = /RECHAZADO/.test(x.titulo || "") ? "mal" : /APROBADO/.test(x.titulo || "") ? "ok" : /BLOQUEO|NO CERTIFICABLE/.test(x.titulo || "") ? "aviso" : "";
        return '<div class="entrada"><details open><summary>' + esc(TIPO_NOMBRE[x.tipo] || x.tipo) + (x.titulo ? ' <span class="chip ' + ver + '">' + esc(x.titulo) + "</span>" : "") +
          "</summary>" + mdTarea(x.texto, t.adjuntos, propios(x)) + galeriaEntrada(x) + "</details></div>";
      }).join("");
    };
    if (intentos.length) {
      document.querySelectorAll("[data-intento]").forEach((b) => (b.onclick = () => pintarIntento(b.dataset.intento)));
      pintarIntento(porIntento[intentoSel] ? intentoSel : intentos[0]);
    }
    document.querySelectorAll("#filtro-adjuntos [data-origen]").forEach((b) => (b.onclick = () => {
      document.querySelectorAll("#filtro-adjuntos [data-origen]").forEach((x) => x.classList.toggle("activo", x === b));
      document.querySelectorAll(".grupo-adjuntos").forEach((g) => (g.hidden = !!b.dataset.origen && g.dataset.origen !== b.dataset.origen));
    }));
    document.querySelectorAll("[data-accion]").forEach((b) => (b.onclick = async () => {
      let texto;
      if (b.dataset.accion === "cambios") return pedirCambios(clave);
      if (b.dataset.accion === "stop") { texto = prompt("¿Por qué se detiene?"); if (!texto) return; }
      else if (!confirm(b.textContent + " " + clave + "?")) return;
      try { await papi("accion", { accion: b.dataset.accion, clave, texto }); aviso("✅ Hecho"); ruta(); } catch (err) { aviso("❌ " + err.message, 6000); }
    }));
    pintarGit(clave, e);
    if (!gitDatos) cargarGit(clave, false, e);
    document.querySelectorAll("[data-editar]").forEach((b) => (b.onclick = () => editar(clave, b.dataset.editar, b.dataset.editar === "titulo" ? t.titulo : t[b.dataset.editar])));
    $("#t-prio").onchange = async (ev) => {
      try { await papi("accion", { accion: "prioridad", clave, texto: ev.target.value }); aviso("Prioridad cambiada"); } catch (err) { aviso("❌ " + err.message); }
    };
    $("#t-subir").onchange = async (ev) => {
      const archivos = await Promise.all([...ev.target.files].map((f) => new Promise((ok) => {
        const r = new FileReader(); r.onload = () => ok({ nombre: f.name, datos: r.result.split(",")[1] }); r.readAsDataURL(f);
      })));
      try { await papi("subir", { clave, archivos }); aviso("📎 Subido"); ruta(); } catch (err) { aviso("❌ " + err.message); }
    };
    // Visor delegado: sirve tambien para lo que se pinta despues (historial al cambiar de intento).
    $("#vista").onclick = (ev) => {
      const el = ev.target.closest(".md img, .galeria img, .galeria video, .ref-img");
      if (!el || (el.tagName === "VIDEO" && el.controls)) return;
      const src = el.dataset.src || el.src;
      if (el.tagName === "VIDEO") return visor([src], 0, true);
      // Se navega por las imagenes del mismo grupo: la galeria donde esta, o (desde un 📷) la galeria de su
      // intento; si no hay galeria, los 📷 / imagenes del mismo texto.
      const abs = (u) => new URL(u, location.href).href;
      const entrada = el.closest(".entrada");
      let lista = el.closest(".galeria") ? [...el.closest(".galeria").querySelectorAll("img")].map((i) => i.src)
        : entrada && entrada.querySelector(".galeria-entrada") ? [...entrada.querySelectorAll(".galeria-entrada img")].map((i) => i.src)
        : [...(el.closest(".md") || document).querySelectorAll(".ref-img, img")].map((x) => x.dataset.src || x.src);
      lista = [...new Set(lista.map(abs))];
      let i = lista.indexOf(abs(src));
      if (i < 0) { lista = [abs(src)]; i = 0; }
      visor(lista, i);
    };
  }

  // Visor de imagenes a pantalla completa, con anterior/siguiente (botones, flechas del teclado o deslizar).
  function visor(lista, i, esVideo) {
    const v = document.createElement("div"); v.className = "visor";
    const nombre = (u) => { try { return decodeURIComponent((u.split("ruta=")[1] || u).split("&")[0]).split("/").pop(); } catch (e) { return ""; } };
    const varias = lista.length > 1 && !esVideo;
    v.innerHTML = (varias ? '<button class="visor-nav anterior" aria-label="Anterior">‹</button><button class="visor-nav siguiente" aria-label="Siguiente">›</button>' : "") +
      '<button class="visor-cerrar" aria-label="Cerrar">✕</button><div class="visor-pie"></div>' +
      (esVideo ? '<video src="' + lista[0] + '" controls autoplay></video>' : '<img alt="">');
    const img = v.querySelector("img"), pie = v.querySelector(".visor-pie");
    const mostrar = (n) => {
      i = (n + lista.length) % lista.length;
      if (img) img.src = lista[i];
      pie.textContent = (varias ? (i + 1) + " / " + lista.length + " · " : "") + nombre(lista[i]);
    };
    const cerrar = () => { v.remove(); document.removeEventListener("keydown", teclas); };
    const teclas = (e) => {
      if (e.key === "Escape") cerrar();
      else if (varias && e.key === "ArrowLeft") { e.preventDefault(); mostrar(i - 1); }
      else if (varias && e.key === "ArrowRight") { e.preventDefault(); mostrar(i + 1); }
    };
    v.onclick = (e) => {
      if (e.target.closest(".anterior")) mostrar(i - 1);
      else if (e.target.closest(".siguiente")) mostrar(i + 1);
      else if (e.target === v || e.target.closest(".visor-cerrar")) cerrar();
    };
    let x0 = null;   // deslizar en el celular
    v.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    v.addEventListener("touchend", (e) => {
      const dx = x0 === null ? 0 : e.changedTouches[0].clientX - x0;
      if (varias && Math.abs(dx) > 50) mostrar(i + (dx < 0 ? 1 : -1));
      x0 = null;
    });
    document.addEventListener("keydown", teclas);
    document.body.appendChild(v);
    mostrar(i);
  }

  function editar(clave, campo, valor) {
    const nombres = { titulo: "Título", descripcion: "Descripción", criterio: "Criterio de aceptación" };
    editando = true;
    $("#vista").innerHTML = '<div class="panel formulario"><h1 class="vista-titulo">' + nombres[campo] + " — " + clave + "</h1>" +
      (campo === "titulo" ? '<input id="e-texto" aria-label="' + nombres[campo] + '">' : '<textarea id="e-texto" aria-label="' + nombres[campo] + '" style="min-height:50vh"></textarea>') +
      '<div class="fila"><button class="primario" id="e-ok">Guardar</button><a class="boton" id="e-cancelar" href="#/tarea/' + clave + '">Cancelar</a></div></div>';
    $("#e-texto").value = valor || "";
    const volver = () => ir("#/tarea/" + clave);
    $("#e-cancelar").onclick = (ev) => { ev.preventDefault(); volver(); };
    $("#e-ok").onclick = async () => {
      try { await papi("accion", { accion: campo, clave, texto: $("#e-texto").value }); aviso("Guardado"); volver(); } catch (err) { aviso("❌ " + err.message); }
    };
  }

  // ---------------------------------------------------------------- git de la tarea
  // Ver commits y diffs de la rama contra la base, y (done/reviewed) mergear, hacer push o abrir PR.
  async function cargarGit(clave, fetch, estado) {
    try { gitDatos = await papi("git/" + clave + (fetch ? "?fetch=1" : "")); }
    catch (err) { gitDatos = { error: err.message, repos: [] }; }
    if (tareaActual === clave) pintarGit(clave, estado);
  }

  function htmlDiff(texto) {
    return '<pre class="diff">' + (texto || "").split("\n").map((l) => {
      const c = /^(diff |index |--- |\+\+\+ |new file|deleted file|similarity|rename |Binary )/.test(l) ? "meta"
        : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "";
      return '<span class="' + c + '">' + esc(l) + "</span>";
    }).join("") + "</pre>";
  }

  function pintarGit(clave, estado) {
    const panel = $("#panel-git");
    if (!panel) return;
    const d = gitDatos;
    if (!d) { panel.innerHTML = '<h2>Git</h2><p class="vacio">Cargando ramas y cambios…</p>'; return; }
    const repos = d.repos || [];
    const pendientes = repos.filter((r) => r.existe_rama && !r.integrada && r.commits.length);
    const sinSubir = repos.filter((r) => r.base_vs_origin && r.base_vs_origin.adelante > 0);
    const ramasSinSubir = repos.filter((r) => r.modificada && (!r.rama_vs_origin || r.rama_vs_origin.adelante > 0));
    const conRemoto = pendientes.filter((r) => r.remoto && ["github", "azure"].includes(r.remoto.tipo));
    const cerrada = ["done", "reviewed"].includes(estado);
    const botones = [];
    if (cerrada && pendientes.length) botones.push(["merge", "⤵ Mergear a la base", "primario"]);
    if (cerrada && sinSubir.length) botones.push(["push-base", "⬆ Push de la base", ""]);
    if (cerrada && ramasSinSubir.length) botones.push(["push-rama", "⬆ Push de las ramas", ""]);
    if (cerrada && conRemoto.length) botones.push(["pr", pendientes.some((r) => r.pr) ? "⬆ Actualizar PR" : "⬆ Crear PR", ""]);
    const chipsRepo = (r) => '<span class="chip">' + esc(r.rama) + " → " + esc(r.base || "?") + "</span>" +
      (!r.existe_rama ? '<span class="chip aviso">sin rama local</span>'
        : r.integrada ? '<span class="chip ok">✓ integrada en ' + esc(r.base) + "</span>"
        : '<span class="chip">' + r.commits.length + " commit" + (r.commits.length === 1 ? "" : "s") + " sin integrar</span>") +
      (r.base_vs_origin && r.base_vs_origin.adelante ? '<span class="chip aviso">' + esc(r.base) + ": " + r.base_vs_origin.adelante + " sin subir a origin</span>" : "") +
      (r.base_vs_origin && r.base_vs_origin.atras ? '<span class="chip aviso">origin/' + esc(r.base) + " va " + r.base_vs_origin.atras + " adelante</span>" : "") +
      (r.rama_vs_origin ? '<span class="chip">rama publicada' + (r.rama_vs_origin.adelante ? " (" + r.rama_vs_origin.adelante + " sin subir)" : "") + "</span>" : "") +
      (r.pr ? '<a class="chip ok" href="' + esc(r.pr) + '" target="_blank" rel="noopener">↗ PR</a>' : "") +
      (r.remoto && r.remoto.tipo !== "ninguno" ? '<span class="chip">' + esc(r.remoto.tipo) + "</span>" : "") +
      (r.avisos || []).map((a) => '<span class="chip mal">' + esc(a) + "</span>").join("");
    const htmlRepo = (r) => {
      const archivos = r.archivos || [];
      return '<div class="git-repo"><h3>' + esc(r.repo) + "</h3><div>" + chipsRepo(r) + "</div>" +
        (r.commits.length ? "<details><summary>Commits (" + r.commits.length + ')</summary><ul class="git-commits">' +
          r.commits.map((c) => "<li><code>" + esc(c.hash) + "</code> " + esc(c.asunto) + ' <span class="vacio">' + esc(c.autor || "") + " · " + esc((c.fecha || "").slice(0, 10)) + "</span></li>").join("") + "</ul></details>" : "") +
        (archivos.length ? '<details open><summary>Archivos (' + archivos.length + ")</summary>" +
          archivos.map((a) => {
            const k = r.repo + "|" + a.ruta, abierto = Object.prototype.hasOwnProperty.call(gitAbiertos, k);
            return '<div class="git-archivo"><button type="button" data-diff="' + esc(k) + '" aria-expanded="' + abierto + '">' +
              '<span class="git-est est-' + esc(a.estado) + '">' + esc(a.estado) + "</span> " + esc(a.ruta) + " " +
              (a.binario ? '<span class="vacio">binario</span>' : '<span class="mas">+' + a.mas + '</span> <span class="menos">−' + a.menos + "</span>") + "</button>" +
              (abierto ? (gitAbiertos[k] === null ? '<p class="vacio">Cargando diff…</p>' : gitAbiertos[k]) : "") + "</div>";
          }).join("") + "</details>" : (r.existe_rama ? '<p class="vacio">Sin cambios contra la base.</p>' : "")) + "</div>";
    };
    panel.innerHTML = '<h2>Git <button type="button" data-git="fetch" title="Traer lo último de origin y recalcular">↻ Actualizar</button></h2>' +
      (d.error ? '<p class="vacio">No se pudo leer git: ' + esc(d.error) + "</p>" : "") +
      repos.map(htmlRepo).join("") +
      (botones.length ? '<div class="acciones git-acciones">' + botones.map(([op, n, c]) => '<button type="button" data-git="' + op + '"' + (c ? ' class="' + c + '"' : "") + (gitOcupado ? " disabled" : "") + ">" + n + "</button>").join("") + "</div>"
        : (!cerrada && repos.some((r) => r.commits.length) ? '<p class="vacio">Mergear, push y PR se habilitan cuando la tarea está en Listas o Revisadas.</p>' : "")) +
      (gitResultado ? '<div class="git-resultado">' + gitResultado + "</div>" : "");

    panel.querySelectorAll("[data-diff]").forEach((b) => (b.onclick = async () => {
      const k = b.dataset.diff;
      if (Object.prototype.hasOwnProperty.call(gitAbiertos, k)) { delete gitAbiertos[k]; return pintarGit(clave, estado); }
      gitAbiertos[k] = null; pintarGit(clave, estado);
      const [repo, ...resto] = k.split("|");
      try {
        const x = await papi("diff/" + clave + "?repo=" + encodeURIComponent(repo) + "&archivo=" + encodeURIComponent(resto.join("|")));
        gitAbiertos[k] = htmlDiff(x.diff) + (x.recortado ? '<p class="vacio">Diff recortado: es muy grande.</p>' : "");
      } catch (err) { gitAbiertos[k] = '<p class="vacio">❌ ' + esc(err.message) + "</p>"; }
      if (Object.prototype.hasOwnProperty.call(gitAbiertos, k)) pintarGit(clave, estado);
    }));
    panel.querySelectorAll("[data-git]").forEach((b) => (b.onclick = async () => {
      const op = b.dataset.git;
      if (op === "fetch") { b.disabled = true; gitResultado = ""; return cargarGit(clave, true, estado); }
      const lista = (rs, f) => rs.map((r) => "• " + r.repo + ": " + f(r)).join("\n");
      const texto = {
        "merge": "Mergear la rama en la base (local, sin push):\n" + lista(pendientes, (r) => r.rama + " → " + r.base + " (" + r.commits.length + " commits)") + "\n\nSi sale bien, la tarea pasa a Revisadas. Si hay conflicto, la base queda intacta.",
        "push-base": "Subir la base a origin (sin --force):\n" + lista(sinSubir, (r) => r.base + " (" + r.base_vs_origin.adelante + " commits)"),
        "push-rama": "Subir a origin solo la rama de la tarea en los repos que modificó (sin --force, no toca la base):\n" +
          lista(ramasSinSubir, (r) => r.rama + (r.rama_vs_origin ? " (" + r.rama_vs_origin.adelante + " commits nuevos)" : " (nueva en origin)")),
        "pr": "Subir la rama y abrir un Pull Request contra la base en:\n" + lista(conRemoto, (r) => r.rama + " → " + r.base + " (" + r.remoto.tipo + ")") + "\n\nSi ya hay un PR abierto, se reusa.",
      }[op];
      if (!confirm(texto)) return;
      gitOcupado = true; gitResultado = '<p class="vacio">Trabajando…</p>'; pintarGit(clave, estado);
      try {
        const res = await papi("git", { op, clave });
        gitResultado = '<p><strong>' + (res.ok ? "✅ Hecho" : "⚠️ No se completó") + "</strong>" + (res.motivo ? " — " + esc(res.motivo) : "") + "</p><ul>" +
          (res.repos || []).map((h) => "<li><strong>" + esc(h.repo) + "</strong>: " + esc(h.accion) + " — " +
            (/^https?:\/\//.test(h.detalle || "") ? '<a href="' + esc(h.detalle) + '" target="_blank" rel="noopener">' + esc(h.detalle) + "</a>" : esc(h.detalle || "")) + "</li>").join("") + "</ul>";
        aviso(res.ok ? "✅ Hecho" : "⚠️ Revisa el resultado en el panel Git", 6000);
      } catch (err) { gitResultado = '<p class="vacio">❌ ' + esc(err.message) + "</p>"; aviso("❌ " + err.message, 6000); }
      gitOcupado = false; gitDatos = null;
      await vistaTarea(clave);   // el estado puede haber cambiado (merge -> reviewed); gitResultado se conserva
    }));
  }

  // Revisada (done/reviewed) pero hace falta otro cambio: vuelve al coder con este pedido, que tambien se
  // suma al criterio para que QA lo certifique. Los adjuntos se suben antes, para que el coder ya los vea.
  function pedirCambios(clave) {
    editando = true;
    $("#vista").innerHTML = '<div class="panel formulario"><h1 class="vista-titulo">Pedir cambios — ' + clave + "</h1>" +
      '<p class="vacio">La tarea vuelve al coder con este pedido (en la misma rama) y pasa otra vez por QA' + (tablero.e2e ? " y E2E" : "") +
      ". El pedido también se agrega al criterio de aceptación. El contador de intentos vuelve a 0.</p>" +
      '<label>¿Qué quieres cambiar? (Markdown)<textarea id="c-texto" style="min-height:40vh" placeholder="Qué está mal, qué esperas y dónde"></textarea></label>' +
      '<label>Capturas o archivos (opcional)<input id="c-adjuntos" type="file" multiple></label>' +
      '<div class="fila"><button class="primario" id="c-ok">Enviar al coder</button><a class="boton" id="c-cancelar" href="#/tarea/' + clave + '">Cancelar</a></div></div>';
    const volver = () => ir("#/tarea/" + clave);
    $("#c-cancelar").onclick = (ev) => { ev.preventDefault(); volver(); };
    $("#c-texto").focus();
    $("#c-ok").onclick = async () => {
      const texto = $("#c-texto").value.trim();
      if (!texto) { aviso("Escribe qué quieres cambiar"); return $("#c-texto").focus(); }
      $("#c-ok").disabled = true;
      try {
        const archivos = await Promise.all([...$("#c-adjuntos").files].map((f) => new Promise((ok) => {
          const r = new FileReader(); r.onload = () => ok({ nombre: f.name, datos: r.result.split(",")[1] }); r.readAsDataURL(f);
        })));
        if (archivos.length) await papi("subir", { clave, archivos });
        await papi("accion", { accion: "cambios", clave, texto });
        aviso("✅ Enviada al coder"); volver();
      } catch (err) { $("#c-ok").disabled = false; aviso("❌ " + err.message, 6000); }
    };
  }

  // ---------------------------------------------------------------- nueva
  function vistaNueva() {
    $("#vista").innerHTML = '<div class="panel"><h1 class="vista-titulo">Nueva tarea</h1><form id="f-nueva" class="formulario">' +
      '<div class="fila"><label>Tipo<select name="tipo"><option>bug</option><option>task</option></select></label>' +
      '<label>Identificador<input name="numero" required pattern="[A-Za-z0-9_]+" title="Número o texto: letras, dígitos y _ (sin espacios ni -)" placeholder="123 o login_social"></label>' +
      '<label>Prioridad<select name="prioridad"><option>High</option><option selected>Medium</option><option>Low</option><option>Critical</option></select></label>' +
      '<label>Repo<select name="repo">' + tablero.repos.map((r) => "<option>" + esc(r) + "</option>").join("") + "</select></label></div>" +
      '<label>Título<input name="titulo" required></label><label>Descripción (Markdown)<textarea name="descripcion"></textarea></label>' +
      '<label>Criterio de aceptación (Markdown)<textarea name="criterio" required></textarea></label>' +
      '<label>Adjuntos (opcional)<input type="file" name="adjuntos" multiple></label>' +
      '<div><button class="primario">Crear</button></div></form></div>';
    $("#f-nueva").onsubmit = async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(e.target).entries());
      const archivos = [...e.target.adjuntos.files];
      delete d.adjuntos;
      try {
        await papi("crear", d);
        const clave = (d.tipo + "-" + d.numero).toLowerCase();
        if (archivos.length) {
          const datos = await Promise.all(archivos.map((f) => new Promise((ok) => { const r = new FileReader(); r.onload = () => ok({ nombre: f.name, datos: r.result.split(",")[1] }); r.readAsDataURL(f); })));
          await papi("subir", { clave, archivos: datos });
        }
        aviso("Tarea creada"); location.hash = "#/tarea/" + clave;
      } catch (err) { aviso("❌ " + err.message, 6000); }
    };
  }

  // ---------------------------------------------------------------- herramientas
  async function vistaHerramientas() {
    const claves = tablero.tareas.map((t) => t.clave).sort();
    $("#vista").innerHTML = '<h1 class="vista-titulo">Herramientas</h1><div class="dos"><div class="panel"><h2>🩺 Health check</h2><p class="vacio">Qué falta para que las pruebas E2E funcionen.</p>' +
      '<div class="fila"><select id="h-clave"><option value="">Todo el proyecto</option>' + claves.map((c) => "<option>" + c + "</option>").join("") + '</select><button class="primario" data-correr="health">Correr</button></div></div>' +
      '<div class="panel"><h2>🧪 Pruebas guardadas</h2><p class="vacio">Vuelve a correr los casos guardados (run-tests).</p>' +
      '<div class="fila"><select id="r-clave"><option value="--all">Todas (regresión)</option><option value="smoke">Pruebas de humo</option>' + claves.map((c) => "<option>" + c + "</option>").join("") + "</select>" +
      '<select id="r-filtro"><option value="">QA + E2E</option><option>--qa</option><option>--e2e</option><option>--web</option><option>--android</option></select><button class="primario" data-correr="run-tests">Correr</button></div></div></div>' +
      '<div class="panel"><h2>Trabajos</h2><div id="trabajos"></div><pre class="salida" id="salida" hidden></pre></div>';
    document.querySelectorAll("[data-correr]").forEach((b) => (b.onclick = async () => {
      const que = b.dataset.correr;
      const d = { que, clave: que === "health" ? $("#h-clave").value : que === "run-tests" ? $("#r-clave").value : "", filtro: que === "run-tests" ? $("#r-filtro").value : "" };
      try { const r = await papi("correr", d); seguir(r.id); pintarTrabajos(); } catch (err) { aviso("❌ " + err.message); }
    }));
    pintarTrabajos();
  }
  async function pintarTrabajos() {
    const c = $("#trabajos");
    if (!c) return;
    const ts = await papi("trabajos");
    c.innerHTML = ts.length ? '<table class="tabla">' + ts.slice().reverse().map((t) => "<tr><td>" + esc(t.inicio) + "</td><td>" + esc(t.que) + "</td><td>" +
      (t.rc === null ? "⏳ corriendo" : t.rc === 0 ? "✅ ok" : "❌ salió " + t.rc) + '</td><td><button data-ver="' + t.id + '">Ver</button></td></tr>').join("") + "</table>"
      : '<p class="vacio">Nada corrió todavía.</p>';
    document.querySelectorAll("[data-ver]").forEach((b) => (b.onclick = () => seguir(b.dataset.ver)));
  }
  function seguir(id) {
    clearTimeout(seguir.t);
    const paso = async () => {
      if (!$("#salida")) return;
      const t = await papi("trabajo/" + id);
      const s = $("#salida"); s.hidden = false; s.textContent = t.salida || "(sin salida todavía)"; s.scrollTop = s.scrollHeight;
      if (t.rc === null) seguir.t = setTimeout(paso, 1500); else { aviso(t.que + (t.rc === 0 ? " terminó ✅" : " terminó con error ❌")); pintarTrabajos(); }
    };
    paso();
  }

  // ---------------------------------------------------------------- pruebas y log
  async function vistaPruebas() {
    const lista = await papi("pruebas");
    $("#vista").innerHTML = '<div class="panel"><h1 class="vista-titulo">Reportes de pruebas</h1>' + (lista.length ? "<ul>" + lista.map((f) => '<li><a href="#/prueba/' + encodeURIComponent(f) + '">' + esc(f) + "</a></li>").join("") + "</ul>" : '<p class="vacio">Todavía no hay reportes (se generan con run-tests).</p>') + "</div>";
  }
  async function vistaPrueba(nombre) {
    const r = await papi("prueba/" + encodeURIComponent(nombre));
    const resolver = (u) => (/^https?:/.test(u) ? u : archivoUrl(u, "pruebas"));
    $("#vista").innerHTML = '<div class="panel"><p><a href="#/pruebas">← Reportes</a></p>' + md(r.texto, resolver) + "</div>";
  }
  async function vistaLog() {
    const filas = await papi("log?n=500");
    $("#vista").innerHTML = '<div class="panel"><h1 class="vista-titulo">Log de actividad</h1><div class="filtros"><input id="l-texto" placeholder="Filtrar…" aria-label="Filtrar el log"></div><div class="tabla-scroll"><table class="tabla" id="l-tabla"></table></div></div>';
    const pintar = () => {
      const f = $("#l-texto").value.toLowerCase();
      $("#l-tabla").innerHTML = "<tr><th>Hora</th><th>Quién</th><th>Tarea</th><th>Evento</th><th>Detalle</th></tr>" +
        filas.filter((l) => !f || JSON.stringify(l).toLowerCase().includes(f)).map((l) => "<tr><td>" + esc((l.hora || "").replace("T", " ").slice(0, 16)) + "</td><td>" + esc(l.origen) +
          "</td><td>" + (/^(task|bug)-[a-z0-9_]+$/.test(l.tarea) ? '<a href="#/tarea/' + l.tarea + '">' + l.tarea + "</a>" : esc(l.tarea || "")) + "</td><td>" + esc(l.evento) + "</td><td>" + esc(l.detalle || "") + "</td></tr>").join("");
    };
    $("#l-texto").oninput = pintar;
    pintar();
  }

  iniciar().catch((e) => { if (e.message !== "sin sesion") $("#vista").innerHTML = '<div class="panel">❌ ' + esc(e.message) + "</div>"; });
  // Skip link: sin esto el href="#vista" cambiaria el hash y romperia el enrutado.
  const skip = $(".skip-link");
  if (skip) skip.addEventListener("click", (ev) => { ev.preventDefault(); const m = $("#vista"); if (m) m.focus(); });
})();
