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
  const PASO_ADJUNTO = { azure: "Tarea original", humano: "Subidos por ti", coder: "Coder", qa: "QA", e2e: "E2E" };
  let proyectos = [], pid = null, tablero = null;

  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin storage */ } };
  const leer = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };

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
    $("#vista").innerHTML = '<div class="panel login"><h2>Clave de acceso</h2><p class="vacio">Está en ~/.config/autopilot-kit/web.env de la máquina del autopilot.</p>' +
      '<form id="f-login" class="formulario"><input id="clave" type="password" autocomplete="current-password" required><button class="primario">Entrar</button></form></div>';
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
  }

  async function ruta() {
    const h = location.hash.replace(/^#\/?/, "");
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
    const el = $("#estado-autopilot");
    el.innerHTML = '<span class="punto ' + (tablero.watcher ? "ok" : "mal") + '"></span>' + (tablero.watcher ? "watcher corriendo" : "watcher detenido") +
      (tablero.e2e ? ' · <span class="chip">E2E</span>' : "") + (tablero.telegram ? '<span class="chip">Telegram</span>' : "") +
      ' <button id="b-pausa">' + (tablero.pausa ? "▶️ Seguir" : "⏸️ Pausar") + "</button>";
    $("#b-pausa").onclick = async () => {
      await papi("pausa", { pausa: !tablero.pausa });
      aviso(tablero.pausa ? "Seguimos: se toman tareas" : "Pausado: no se toman tareas nuevas");
      ruta();
    };
  }

  // ---------------------------------------------------------------- tablero
  function vistaTablero() {
    const f = JSON.parse(leer("filtros") || "{}");
    const repos = tablero.repos;
    $("#vista").innerHTML =
      '<div class="filtros"><input id="f-texto" placeholder="Buscar por clave o título…" value="' + esc(f.texto || "") + '">' +
      '<select id="f-repo"><option value="">Todos los repos</option>' + repos.map((r) => "<option" + (f.repo === r ? " selected" : "") + ">" + esc(r) + "</option>").join("") + "</select>" +
      '<select id="f-prio"><option value="">Toda prioridad</option>' + ["Critical", "High", "Medium", "Low"].map((p) => "<option" + (f.prio === p ? " selected" : "") + ">" + p + "</option>").join("") + "</select>" +
      '<label><input type="checkbox" id="f-rev"' + (f.rev ? " checked" : "") + "> Mostrar revisadas</label>" +
      '<label><input type="checkbox" id="f-vacias"' + (f.vacias ? " checked" : "") + "> Columnas vacías</label></div>" +
      '<div class="resumen" id="resumen"></div>' +
      (tablero.pausa ? '<div class="panel">⏸️ <strong>En pausa:</strong> el autopilot no toma tareas nuevas.</div>' : "") +
      '<div class="tablero" id="columnas"></div>';
    const pintar = () => {
      const texto = $("#f-texto").value.toLowerCase(), repo = $("#f-repo").value, prio = $("#f-prio").value, rev = $("#f-rev").checked,
        vacias = $("#f-vacias").checked;
      guardar("filtros", JSON.stringify({ texto, repo, prio, rev, vacias }));
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
    pintar();
  }
  function tarjeta(t) {
    return '<a class="tarjeta" href="#/tarea/' + t.clave + '"><div class="clave"><span>' + t.clave + '</span><span class="chip ' + t.prioridad + '">' + t.prioridad + "</span></div>" +
      '<div class="titulo">' + esc(t.titulo) + "</div>" +
      '<div class="clave"><span>' + esc(t.repo || "") + (t.repos_extra ? " +" + esc(t.repos_extra) : "") + "</span><span>" + (t.intento !== "0" ? "intento " + esc(t.intento) : "") + "</span></div>" +
      (t.espera ? '<span class="chip aviso">espera a ' + esc(t.espera) + "</span>" : "") + "</a>";
  }

  // ---------------------------------------------------------------- tarea
  async function vistaTarea(clave) {
    const t = await papi("tarea/" + clave);
    const e = t.estado, m = t.meta;
    const acciones = [];
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
      const o = a.origen || "azure", n = a.intento || 0;
      const g = ["coder", "qa", "e2e"].includes(o)
        ? { orden: [2, o === "coder" ? n + 1 : n, ["coder", "qa", "e2e"].indexOf(o)], nombre: PASO_ADJUNTO[o] + " · intento " + n, origen: o }
        : { orden: [o === "azure" ? 0 : 1, 0, 0], nombre: PASO_ADJUNTO[o] || o, origen: o };
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
      '<h1 id="t-titulo">' + esc(t.titulo) + ' <button data-editar="titulo" title="Editar título">✎</button></h1>' +
      '<div style="margin-top:6px"><select id="t-prio">' + ["Critical", "High", "Medium", "Low"].map((p) => "<option" + (m.prioridad === p ? " selected" : "") + ">" + p + "</option>").join("") + "</select> " +
      '<span class="chip">intento ' + esc(m.intento || "0") + '</span><span class="chip">rama ' + esc(m.rama || clave) + '</span><span class="chip">' + esc(m.repo || "-") + (m.repos_extra ? " + " + esc(m.repos_extra) : "") + "</span>" +
      (m.espera ? '<span class="chip aviso">espera a ' + esc(m.espera) + "</span>" : "") +
      (t.borradores.qa || t.borradores.e2e ? '<span class="chip">borrador de pruebas: ' + ["qa", "e2e"].filter((k) => t.borradores[k]).join(", ") + "</span>" : "") +
      '</div></div><div class="acciones">' + acciones.map(([a, n]) => '<button data-accion="' + a + '"' + (a === "stop" ? ' class="peligro"' : "") + ">" + n + "</button>").join("") + "</div></div></div>" +
      (t.motivo ? '<div class="panel" style="border-color:var(--mal)"><h2>⛔ Motivo de detención</h2>' + md(t.motivo) + "</div>" : "") +
      (t.resultado ? '<div class="panel"><h2>Resultado</h2>' + md(t.resultado) + "</div>" : "") +
      '<div class="dos"><div class="panel"><h2>Descripción <button data-editar="descripcion">✎</button></h2>' + mdTarea(t.descripcion, t.adjuntos, originales) + "</div>" +
      '<div class="panel"><h2>Criterio de aceptación <button data-editar="criterio">✎</button></h2>' + mdTarea(t.criterio, t.adjuntos, originales) + "</div></div>" +
      (t.repos_modificados ? '<div class="panel"><h2>Repos modificados</h2>' + md(t.repos_modificados) + "</div>" : "") +
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
      pintarIntento(intentos[0]);
    }
    document.querySelectorAll("#filtro-adjuntos [data-origen]").forEach((b) => (b.onclick = () => {
      document.querySelectorAll("#filtro-adjuntos [data-origen]").forEach((x) => x.classList.toggle("activo", x === b));
      document.querySelectorAll(".grupo-adjuntos").forEach((g) => (g.hidden = !!b.dataset.origen && g.dataset.origen !== b.dataset.origen));
    }));
    document.querySelectorAll("[data-accion]").forEach((b) => (b.onclick = async () => {
      let texto;
      if (b.dataset.accion === "stop") { texto = prompt("¿Por qué se detiene?"); if (!texto) return; }
      else if (!confirm(b.textContent + " " + clave + "?")) return;
      try { await papi("accion", { accion: b.dataset.accion, clave, texto }); aviso("✅ Hecho"); ruta(); } catch (err) { aviso("❌ " + err.message, 6000); }
    }));
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
      const v = document.createElement("div"); v.className = "visor";
      v.innerHTML = el.tagName === "VIDEO" ? '<video src="' + src + '" controls autoplay></video>' : '<img src="' + src + '">';
      v.onclick = (e2) => { if (e2.target === v || e2.target.tagName === "IMG") v.remove(); };
      document.body.appendChild(v);
    };
  }

  function editar(clave, campo, valor) {
    const nombres = { titulo: "Título", descripcion: "Descripción", criterio: "Criterio de aceptación" };
    $("#vista").innerHTML = '<div class="panel formulario"><h2>' + nombres[campo] + " — " + clave + "</h2>" +
      (campo === "titulo" ? '<input id="e-texto">' : '<textarea id="e-texto" style="min-height:50vh"></textarea>') +
      '<div class="fila"><button class="primario" id="e-ok">Guardar</button><a class="boton" href="#/tarea/' + clave + '">Cancelar</a></div></div>';
    $("#e-texto").value = valor || "";
    $("#e-ok").onclick = async () => {
      try { await papi("accion", { accion: campo, clave, texto: $("#e-texto").value }); aviso("Guardado"); location.hash = "#/tarea/" + clave; } catch (err) { aviso("❌ " + err.message); }
    };
  }

  // ---------------------------------------------------------------- nueva
  function vistaNueva() {
    $("#vista").innerHTML = '<div class="panel"><h2>Nueva tarea</h2><form id="f-nueva" class="formulario">' +
      '<div class="fila"><label>Tipo<select name="tipo"><option>bug</option><option>task</option></select></label>' +
      '<label>Número (workitem)<input name="numero" required pattern="\\d+" inputmode="numeric"></label>' +
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
        const clave = d.tipo + "-" + d.numero;
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
    $("#vista").innerHTML = '<div class="dos"><div class="panel"><h2>🩺 Health check</h2><p class="vacio">Qué falta para que las pruebas E2E funcionen.</p>' +
      '<div class="fila"><select id="h-clave"><option value="">Todo el proyecto</option>' + claves.map((c) => "<option>" + c + "</option>").join("") + '</select><button class="primario" data-correr="health">Correr</button></div></div>' +
      '<div class="panel"><h2>🧪 Pruebas guardadas</h2><p class="vacio">Vuelve a correr los casos guardados (run-tests).</p>' +
      '<div class="fila"><select id="r-clave"><option value="--all">Todas (regresión)</option><option value="smoke">Pruebas de humo</option>' + claves.map((c) => "<option>" + c + "</option>").join("") + "</select>" +
      '<select id="r-filtro"><option value="">QA + E2E</option><option>--qa</option><option>--e2e</option><option>--web</option><option>--android</option></select><button class="primario" data-correr="run-tests">Correr</button></div></div></div>' +
      '<div class="panel"><h2>📥 Azure DevOps</h2><div class="fila"><span class="vacio">Trae las tareas nuevas del sprint.</span><button data-correr="azure-sync">Sincronizar</button></div></div>' +
      '<div class="panel"><h2>Trabajos</h2><div id="trabajos"></div><pre class="salida" id="salida" hidden></pre></div>';
    document.querySelectorAll("[data-correr]").forEach((b) => (b.onclick = async () => {
      const que = b.dataset.correr;
      const d = { que, clave: que === "health" ? $("#h-clave").value : que === "run-tests" ? $("#r-clave").value : "", filtro: que === "run-tests" ? $("#r-filtro").value : "" };
      try { const r = await papi("correr", d); seguir(r.id); listar(); } catch (err) { aviso("❌ " + err.message); }
    }));
    const listar = async () => {
      const ts = await papi("trabajos");
      $("#trabajos").innerHTML = ts.length ? '<table class="tabla">' + ts.reverse().map((t) => "<tr><td>" + esc(t.inicio) + "</td><td>" + esc(t.que) + "</td><td>" +
        (t.rc === null ? "⏳ corriendo" : t.rc === 0 ? "✅ ok" : "❌ salió " + t.rc) + '</td><td><button data-ver="' + t.id + '">Ver</button></td></tr>').join("") + "</table>" : '<p class="vacio">Nada corrió todavía.</p>';
      document.querySelectorAll("[data-ver]").forEach((b) => (b.onclick = () => seguir(b.dataset.ver)));
    };
    listar();
  }
  function seguir(id) {
    clearTimeout(seguir.t);
    const paso = async () => {
      if (!$("#salida")) return;
      const t = await papi("trabajo/" + id);
      const s = $("#salida"); s.hidden = false; s.textContent = t.salida || "(sin salida todavía)"; s.scrollTop = s.scrollHeight;
      if (t.rc === null) seguir.t = setTimeout(paso, 1500); else { aviso(t.que + (t.rc === 0 ? " terminó ✅" : " terminó con error ❌")); vistaHerramientasLista(); }
    };
    paso();
  }
  function vistaHerramientasLista() { const b = document.querySelector("[data-correr]"); if (b) papi("trabajos").then(() => {}); }

  // ---------------------------------------------------------------- pruebas y log
  async function vistaPruebas() {
    const lista = await papi("pruebas");
    $("#vista").innerHTML = '<div class="panel"><h2>Reportes de pruebas</h2>' + (lista.length ? "<ul>" + lista.map((f) => '<li><a href="#/prueba/' + encodeURIComponent(f) + '">' + esc(f) + "</a></li>").join("") + "</ul>" : '<p class="vacio">Todavía no hay reportes (se generan con run-tests).</p>') + "</div>";
  }
  async function vistaPrueba(nombre) {
    const r = await papi("prueba/" + encodeURIComponent(nombre));
    const resolver = (u) => (/^https?:/.test(u) ? u : archivoUrl(u, "pruebas"));
    $("#vista").innerHTML = '<div class="panel"><p><a href="#/pruebas">← Reportes</a></p>' + md(r.texto, resolver) + "</div>";
  }
  async function vistaLog() {
    const filas = await papi("log?n=500");
    $("#vista").innerHTML = '<div class="panel"><h2>Log de actividad</h2><div class="filtros"><input id="l-texto" placeholder="Filtrar…"></div><div class="tabla-scroll"><table class="tabla" id="l-tabla"></table></div></div>';
    const pintar = () => {
      const f = $("#l-texto").value.toLowerCase();
      $("#l-tabla").innerHTML = "<tr><th>Hora</th><th>Quién</th><th>Tarea</th><th>Evento</th><th>Detalle</th></tr>" +
        filas.filter((l) => !f || JSON.stringify(l).toLowerCase().includes(f)).map((l) => "<tr><td>" + esc((l.hora || "").replace("T", " ").slice(0, 16)) + "</td><td>" + esc(l.origen) +
          "</td><td>" + (/^(task|bug)-\d+$/.test(l.tarea) ? '<a href="#/tarea/' + l.tarea + '">' + l.tarea + "</a>" : esc(l.tarea || "")) + "</td><td>" + esc(l.evento) + "</td><td>" + esc(l.detalle || "") + "</td></tr>").join("");
    };
    $("#l-texto").oninput = pintar;
    pintar();
  }

  iniciar().catch((e) => { if (e.message !== "sin sesion") $("#vista").innerHTML = '<div class="panel">❌ ' + esc(e.message) + "</div>"; });
})();
