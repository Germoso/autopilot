// markdown.js — Markdown -> HTML para los reportes del autopilot. Escapa TODO el HTML del texto primero
// (los reportes vienen de agentes: nunca se inserta HTML crudo). Soporta: titulos, parrafos, listas,
// tablas, codigo, citas, negrita/cursiva, enlaces e imagenes. `resolver(url)` reescribe las rutas de
// imagenes/enlaces (p. ej. ../adjuntos/... -> /api/.../archivo?ruta=...).
(function () {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const seguro = (u) => /^(https?:|\/|#|\.{0,2}\/|[\w.-]+\/)/i.test(u) && !/^\s*javascript:/i.test(u);

  function enLinea(t, resolver) {
    const codigos = [];
    t = t.replace(/`([^`]+)`/g, (_, c) => { codigos.push(c); return "\u0000" + (codigos.length - 1) + "\u0000"; });
    t = esc(t);
    t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_, alt, url) => {
      const u = resolver(url.replace(/&amp;/g, "&"));
      return seguro(u) ? '<img src="' + esc(u) + '" alt="' + alt + '" loading="lazy">' : alt;
    });
    t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, txt, url) => {
      const u = resolver(url.replace(/&amp;/g, "&"));
      return seguro(u) ? '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + txt + "</a>" : txt;
    });
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])_([^_]+)_(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
         .replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
    return t.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + esc(codigos[+i]) + "</code>");
  }

  function render(md, resolver) {
    resolver = resolver || ((u) => u);
    const lineas = (md || "").replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    const esLista = (l) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
    while (i < lineas.length) {
      const l = lineas[i];
      if (/^```/.test(l)) {
        const buf = [];
        i++;
        while (i < lineas.length && !/^```/.test(lineas[i])) buf.push(lineas[i++]);
        i++;
        out.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>");
        continue;
      }
      if (/^<!--/.test(l.trim())) { while (i < lineas.length && !/-->/.test(lineas[i])) i++; i++; continue; }
      let m = l.match(/^(#{1,6})\s+(.*)$/);
      if (m) { const n = Math.min(m[1].length + 2, 6); out.push("<h" + n + ">" + enLinea(m[2], resolver) + "</h" + n + ">"); i++; continue; }
      if (/^\s*(---|\*\*\*)\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lineas.length && /^\s*\|[\s:|-]+\|\s*$/.test(lineas[i + 1])) {
        const celdas = (x) => x.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => enLinea(c.trim().replace(/\\\|/g, "|"), resolver));
        const cab = celdas(l);
        i += 2;
        const filas = [];
        while (i < lineas.length && /^\s*\|.*\|\s*$/.test(lineas[i])) filas.push(celdas(lineas[i++]));
        out.push("<table><thead><tr>" + cab.map((c) => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>" +
          filas.map((f) => "<tr>" + f.map((c) => "<td>" + c + "</td>").join("") + "</tr>").join("") + "</tbody></table>");
        continue;
      }
      if (/^\s*>/.test(l)) {
        const buf = [];
        while (i < lineas.length && /^\s*>/.test(lineas[i])) buf.push(lineas[i++].replace(/^\s*>\s?/, ""));
        out.push("<blockquote>" + render(buf.join("\n"), resolver) + "</blockquote>");
        continue;
      }
      if (esLista(l)) {
        const ordenada = /^\s*\d+[.)]/.test(l);
        const items = [];
        while (i < lineas.length && (esLista(lineas[i]) || (/^\s{2,}\S/.test(lineas[i]) && items.length))) {
          if (esLista(lineas[i])) items.push(lineas[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
          else items[items.length - 1] += "\n" + lineas[i].trim();
          i++;
        }
        out.push((ordenada ? "<ol>" : "<ul>") + items.map((x) => "<li>" + x.split("\n").map((y) => enLinea(y, resolver)).join("<br>") + "</li>").join("") + (ordenada ? "</ol>" : "</ul>"));
        continue;
      }
      if (!l.trim()) { i++; continue; }
      const buf = [];
      while (i < lineas.length && lineas[i].trim() && !/^(#{1,6}\s|```|\s*\|.*\|\s*$|\s*>)/.test(lineas[i]) && !esLista(lineas[i])) buf.push(lineas[i++]);
      out.push("<p>" + buf.map((x) => enLinea(x, resolver)).join("<br>") + "</p>");
    }
    return out.join("\n");
  }
  window.Markdown = { render, esc };
})();
