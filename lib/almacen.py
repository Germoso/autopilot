#!/usr/bin/env python3
"""
almacen.py — el tablero en SQLite (.workitems/autopilot.db). Solo stdlib.

Guarda el TEXTO de las tareas; los adjuntos (imagenes, videos, capturas) siguen como archivos en
.workitems/adjuntos/<clave>/ y la base guarda su ruta. Lo usa workitems.Board (misma API de siempre).

Tablas:
  tareas    una fila por tarea: estado, metadatos, descripcion, criterio y las secciones de un solo valor
  entradas  el historial, una fila por bloque "### ..." (notas del coder, reportes y feedback de QA/E2E
            por intento): un agente pide solo el que necesita
  adjuntos  archivos de la tarea: ruta relativa a .workitems/, origen, intento, tipo, tamano, sha256
  log       el log de actividad
  meta      version del esquema y datos de la migracion

Modo WAL + busy_timeout: varios procesos (coder, QA, E2E, vigia, app web) leen y escriben a la vez.
"""
import hashlib
import json
import os
import re
import sqlite3

ESQUEMA = 1
ARCHIVO = "autopilot.db"

# Secciones de un solo valor (columna de `tareas`) y secciones de historial (filas de `entradas`).
SIMPLES = {"Descripción": "descripcion", "Criterio de aceptación": "criterio", "Adjuntos": "adjuntos_md",
           "Repos modificados": "repos_modificados", "Resultado": "resultado", "Motivo de stopped": "motivo_stopped"}
HISTORIAL = {"Notas del desarrollador": "notas_dev", "Reporte de QA": "reporte_qa", "Feedback de QA": "feedback_qa",
             "Reporte E2E": "reporte_e2e", "Feedback de E2E": "feedback_e2e"}
META = ["id", "tipo", "prioridad", "intento", "rama", "repo", "repos_extra", "origen", "sesion", "espera",
        "actualizado"]

SQL = """
CREATE TABLE IF NOT EXISTS tareas (
  clave TEXT PRIMARY KEY, estado TEXT NOT NULL, titulo TEXT NOT NULL DEFAULT '',
  id TEXT, tipo TEXT, prioridad TEXT, intento TEXT, rama TEXT, repo TEXT, repos_extra TEXT, origen TEXT,
  sesion TEXT, espera TEXT, actualizado TEXT, creado TEXT,
  descripcion TEXT, criterio TEXT, adjuntos_md TEXT, repos_modificados TEXT, resultado TEXT, motivo_stopped TEXT,
  otras_secciones TEXT, otros_meta TEXT, vista TEXT, vista_sha TEXT
);
CREATE INDEX IF NOT EXISTS tareas_estado ON tareas(estado);
CREATE TABLE IF NOT EXISTS entradas (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT NOT NULL, tipo TEXT NOT NULL, orden INTEGER NOT NULL,
  intento INTEGER, fecha TEXT, titulo TEXT, texto TEXT
);
CREATE INDEX IF NOT EXISTS entradas_clave ON entradas(clave, tipo, orden);
CREATE TABLE IF NOT EXISTS adjuntos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT NOT NULL, ruta TEXT NOT NULL UNIQUE, origen TEXT,
  intento INTEGER, tipo TEXT, tamano INTEGER, sha256 TEXT, creado TEXT
);
CREATE INDEX IF NOT EXISTS adjuntos_clave ON adjuntos(clave);
CREATE TABLE IF NOT EXISTS log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, hora TEXT, origen TEXT, tipo TEXT, tarea TEXT, rama TEXT,
  "commit" TEXT, evento TEXT, detalle TEXT
);
CREATE INDEX IF NOT EXISTS log_tarea ON log(tarea);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIDEO = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".3gp"}


def bloques(texto):
    """Parte una seccion de historial en bloques "### titulo\\n\\ntexto" -> [(titulo, texto)].
    Lo que haya antes del primer ### queda como un bloque sin titulo."""
    texto = (texto or "").strip()
    if not texto:
        return []
    partes = re.split(r"(?m)^### ", texto)
    out = []
    if partes[0].strip():
        out.append(("", partes[0].strip()))
    for p in partes[1:]:
        titulo, _, cuerpo = p.partition("\n")
        out.append((titulo.strip(), cuerpo.strip()))
    return out


def unir(bloques_):
    return "\n\n".join(("### %s\n\n%s" % (t, x)).strip() if t else x for t, x in bloques_).strip()


def intento_de(titulo):
    m = re.search(r"Intento (\d+)", titulo or "")
    return int(m.group(1)) if m else None


def fecha_de(titulo):
    m = re.search(r"\((\d{4}-\d\d-\d\dT[\d:+.-]+)\)", titulo or "")
    return m.group(1) if m else None


class Almacen:
    def __init__(self, directorio):
        self.dir = directorio
        self.path = os.path.join(directorio, ARCHIVO)
        self.nueva = not os.path.exists(self.path)
        os.makedirs(directorio, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA busy_timeout=30000")
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SQL)
        self.con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('esquema', ?)", (str(ESQUEMA),))

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    # -- tareas
    def claves(self):
        return [(r["estado"], r["clave"]) for r in self.q("SELECT estado, clave FROM tareas ORDER BY clave")]

    def fila(self, clave):
        r = self.q("SELECT * FROM tareas WHERE clave=?", (clave,))
        return r[0] if r else None

    def obtener(self, clave):
        """(estado, meta, titulo, secs) como si fuera el .md de siempre, o None."""
        r = self.fila(clave)
        if r is None:
            return None
        meta = {k: r[k] for k in META if r[k] not in (None, "")}
        meta.update(json.loads(r["otros_meta"] or "{}"))
        secs = {}
        for h, col in SIMPLES.items():
            if r[col] is not None:
                secs[h] = r[col]
        por_tipo = {}
        for e in self.q("SELECT tipo, titulo, texto FROM entradas WHERE clave=? ORDER BY tipo, orden", (clave,)):
            por_tipo.setdefault(e["tipo"], []).append((e["titulo"], e["texto"]))
        for h, tipo in HISTORIAL.items():
            if tipo in por_tipo:
                secs[h] = unir(por_tipo[tipo])
        secs.update(json.loads(r["otras_secciones"] or "{}"))
        return r["estado"], meta, r["titulo"], secs

    def guardar(self, clave, estado, meta, titulo, secs, creado=None):
        """Escribe la tarea completa (upsert). El historial se reescribe desde las secciones."""
        cols = {k: meta.get(k) for k in META}
        otros_meta = {k: v for k, v in meta.items() if k not in META}
        simples = {col: secs.get(h) for h, col in SIMPLES.items()}
        otras = {h: v for h, v in secs.items() if h not in SIMPLES and h not in HISTORIAL}
        existe = self.fila(clave) is not None
        self.con.execute("BEGIN IMMEDIATE")
        try:
            valores = dict(cols, **simples, clave=clave, estado=estado, titulo=titulo,
                           otras_secciones=json.dumps(otras, ensure_ascii=False),
                           otros_meta=json.dumps(otros_meta, ensure_ascii=False))
            if existe:
                sets = ", ".join('"%s"=:%s' % (k, k) for k in valores if k != "clave")
                self.con.execute("UPDATE tareas SET %s WHERE clave=:clave" % sets, valores)
            else:
                valores["creado"] = creado or meta.get("actualizado")
                ks = list(valores)
                self.con.execute("INSERT INTO tareas(%s) VALUES(%s)" % (", ".join('"%s"' % k for k in ks),
                                                                     ", ".join(":" + k for k in ks)), valores)
            self.con.execute("DELETE FROM entradas WHERE clave=?", (clave,))
            for h, tipo in HISTORIAL.items():
                for i, (t, x) in enumerate(bloques(secs.get(h, ""))):
                    self.con.execute("INSERT INTO entradas(clave, tipo, orden, intento, fecha, titulo, texto) "
                                     "VALUES(?,?,?,?,?,?,?)", (clave, tipo, i, intento_de(t), fecha_de(t), t, x))
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise

    def set_vista(self, clave, ruta, sha):
        self.con.execute("UPDATE tareas SET vista=?, vista_sha=? WHERE clave=?", (ruta, sha, clave))

    def entradas(self, clave, tipo=None, intento=None, ultimo=False):
        sql, args = "SELECT tipo, intento, fecha, titulo, texto FROM entradas WHERE clave=?", [clave]
        if tipo:
            sql += " AND tipo=?"
            args.append(tipo)
        if intento is not None:
            sql += " AND intento=?"
            args.append(intento)
        filas = [dict(r) for r in self.q(sql + " ORDER BY tipo, orden", args)]
        if ultimo:
            ult = {}
            for f in filas:
                ult[f["tipo"]] = f
            filas = list(ult.values())
        return filas

    # -- adjuntos
    def registrar_adjunto(self, clave, ruta_abs, origen=None, intento=None, fecha=None):
        rel = os.path.relpath(ruta_abs, self.dir).replace(os.sep, "/")
        ext = os.path.splitext(ruta_abs)[1].lower()
        tipo = "imagen" if ext in IMAGEN else "video" if ext in VIDEO else "otro"
        try:
            tam = os.path.getsize(ruta_abs)
            sha = hashlib.sha256(open(ruta_abs, "rb").read()).hexdigest() if tam < 64 * 1024 * 1024 else None
        except OSError:
            return None
        if origen is None:  # por la carpeta: coder-intento2, qa-intento1, e2e-intento3, humano, el resto de Azure
            m = re.search(r"/(coder|qa|e2e)-intento(\d+)/", "/" + rel)
            origen, intento = (m.group(1), int(m.group(2))) if m else ("humano" if "/humano/" in rel else "azure", intento)
        self.con.execute("INSERT INTO adjuntos(clave, ruta, origen, intento, tipo, tamano, sha256, creado) "
                         "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ruta) DO UPDATE SET tamano=excluded.tamano, "
                         "sha256=excluded.sha256", (clave, rel, origen, intento, tipo, tam, sha, fecha))
        return rel

    def adjuntos(self, clave):
        return [dict(r) for r in self.q("SELECT * FROM adjuntos WHERE clave=? ORDER BY ruta", (clave,))]

    def adjunto(self, id_):
        r = self.q("SELECT * FROM adjuntos WHERE id=?", (id_,))
        return dict(r[0]) if r else None

    def adjuntos_faltantes(self):
        return [dict(r) for r in self.q("SELECT id, clave, ruta FROM adjuntos")
                if not os.path.exists(os.path.join(self.dir, r["ruta"]))]

    # -- log
    def log(self, hora, origen, tipo, tarea, rama, commit, evento, detalle):
        self.con.execute('INSERT INTO log(hora, origen, tipo, tarea, rama, "commit", evento, detalle) '
                         "VALUES(?,?,?,?,?,?,?,?)", (hora, origen, tipo, tarea, rama, commit, evento, detalle))

    def log_listar(self, tarea=None, limite=200):
        if tarea:
            return [dict(r) for r in self.q("SELECT * FROM log WHERE tarea=? ORDER BY id DESC LIMIT ?", (tarea, limite))]
        return [dict(r) for r in self.q("SELECT * FROM log ORDER BY id DESC LIMIT ?", (limite,))]

    # -- meta
    def meta_get(self, k):
        r = self.q("SELECT v FROM meta WHERE k=?", (k,))
        return r[0]["v"] if r else None

    def meta_set(self, k, v):
        self.con.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
