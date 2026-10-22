#!/usr/bin/env python3
"""
entorno.py — Nunca contra produccion: valida el .env.autopilot de un repo.

El coder SOLO se conecta a bases de datos o APIs con el `.env.autopilot` que el
HUMANO crea a mano en el repo, apuntando a local o a QA. Este validador mínimo
revisa que así sea y nunca imprime valores, solo nombres de claves.

Variables "destino" (las que dicen A DONDE se conecta el codigo): modo del
entorno (NODE_ENV, APP_ENV...), bases de datos (URL/URI/HOST/NOMBRE), URLs de
API. Cada una se clasifica:
  local          localhost, 127.0.0.1, host.docker.internal, sqlite, :memory:
  qa             el valor dice "qa" (en una BD: el NOMBRE de la base dice "qa")
  no-permitido   todo lo demas (incluye NODE_ENV=production). Ante la duda no se usa.
El humano puede permitir a proposito claves sin version de QA con
`AUTOPILOT_PERMITIR=CLAVE1,CLAVE2` dentro de su .env.autopilot.

Estados de un repo:
  ok          .env.autopilot existe, todo destino es local/qa (o permitido) y
              define TODAS las claves destino que tienen los .env del repo.
  falta       no hay .env.autopilot.
  inseguro    alguna clave destino de .env.autopilot no es local ni qa.
  incompleto  alguna clave destino de .env / .env.local / ... no esta en .env.autopilot.

uso: entorno.py <repo o worktree>          JSON
     entorno.py <repo> --exportar          pares CLAVE\\0VALOR\\0 para aenv.sh (solo si ok)
"""
import json
import os
import re
import subprocess
import sys

ARCHIVO = ".env.autopilot"
RE_MODO = re.compile(r"^((NODE|APP|RAILS|FLASK|DJANGO)_)?ENV(IRONMENT)?$", re.I)
RE_BD = re.compile(r"(DATABASE|(^|_)DB(_|$)|MONGO|POSTGRES|MYSQL|SQL|REDIS|RABBIT|KAFKA|ELASTIC)", re.I)
RE_BD_DESTINO = re.compile(r"(URL|URI|HOST|NAME|SERVER|CONN|DATABASE$|(^|_)DB$)", re.I)
RE_URL = re.compile(r"(_URL$|_URI$|(^|_)HOST$|HOSTNAME|ENDPOINT|BASE_URL|_SERVER$)", re.I)
RE_CREDENCIAL = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|(^|_)PASS(_|$)|USER|PORT|EXPIRATION|LIMIT|VERSION)", re.I)
LOCAL = re.compile(r"(localhost|127\.0\.0\.1|host\.docker\.internal|^sqlite|:memory:|file:)", re.I)


def leer(path):
    vals = {}
    if not os.path.isfile(path):
        return vals
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:]
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        vals[k.strip()] = v
    return vals


def es_destino(k):
    """Claves que dicen A DONDE se conecta el codigo: modo del entorno, BD (url/host/nombre) y URLs."""
    if RE_MODO.match(k):
        return True
    if RE_CREDENCIAL.search(k) and not RE_URL.search(k):
        return False                      # claves, usuarios, puertos: no son un destino
    if RE_BD.search(k):
        return bool(RE_BD_DESTINO.search(k))
    return bool(RE_URL.search(k))


def nombre_bd(v):
    """Nombre de la base de datos en una URL de conexion (postgres://h/NOMBRE?x, ...;Database=NOMBRE)."""
    m = re.search(r"(?:database|dbname|initial catalog)\s*=\s*([^;&]+)", v, re.I)
    if m:
        return m.group(1)
    m = re.match(r"^[a-z][a-z0-9+.-]*://[^/]+/([^?#]+)", v, re.I)
    return m.group(1) if m else None


def clasificar(k, v):
    if RE_MODO.match(k):
        return "no-permitido" if re.search(r"prod|live|main|master", v, re.I) else "local"
    if LOCAL.search(v):
        return "local"
    if RE_BD.search(k):
        nombre = nombre_bd(v)
        return "qa" if re.search(r"qa", nombre if nombre is not None else v, re.I) else "no-permitido"
    return "qa" if re.search(r"qa", v, re.I) else "no-permitido"


def repo_principal(path):
    """En un worktree del coder, el .env.autopilot (sin versionar) esta en el repo principal."""
    r = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return os.path.dirname(r.stdout.strip().rstrip("/"))
    return os.path.abspath(path)


def validar(path):
    repo = repo_principal(path)
    auto = leer(os.path.join(repo, ARCHIVO))
    reales = {}
    for n in sorted(os.listdir(repo)) if os.path.isdir(repo) else []:
        if n.startswith(".env") and n != ARCHIVO and not n.endswith((".example", ".sample", ".template")):
            reales.update({k: v for k, v in leer(os.path.join(repo, n)).items() if v})
    destinos_reales = sorted(k for k in reales if es_destino(k))
    out = {"repo": repo, "archivo": os.path.join(repo, ARCHIVO), "estado": "ok",
           "inseguras": [], "faltan": [], "destinos_en_env_real": destinos_reales}
    if not os.path.isfile(out["archivo"]):
        out["estado"] = "falta"
        out["recomendacion"] = ("Crea %s en %s (copia de .env) apuntando a local o QA: base de datos cuyo "
                                "NOMBRE diga qa, URLs de QA, NODE_ENV distinto de production." % (ARCHIVO, repo))
        return out
    permitidas = set()
    for raw in open(out["archivo"], encoding="utf-8", errors="replace"):
        m = re.match(r"^\s*(?:export\s+)?AUTOPILOT_PERMITIR\s*=\s*['\"]?([^'\"#]*)", raw)
        if m:
            permitidas |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    for k, v in sorted(auto.items()):
        if k == "AUTOPILOT_PERMITIR" or not v or not es_destino(k):
            continue
        if clasificar(k, v) == "no-permitido":
            (out["permitidas_por_humano"] if k in permitidas else out["inseguras"]).append(k)
    out["faltan"] = [k for k in destinos_reales if k not in auto]
    if out["inseguras"]:
        out["estado"] = "inseguro"
        out["recomendacion"] = ("En %s estas claves no apuntan a local ni a QA: %s. Cambialas a QA/local "
                                "(la BD debe decir qa en su nombre) o, si es a proposito y seguro, "
                                "agregalas a AUTOPILOT_PERMITIR." % (ARCHIVO, ", ".join(out["inseguras"])))
    elif out["faltan"]:
        out["estado"] = "incompleto"
        out["recomendacion"] = ("%s no define %s, que el .env del repo si tiene: al ejecutar se usaria el "
                                "valor real. Agregalas a %s con valores de QA/local."
                                % (ARCHIVO, ", ".join(out["faltan"]), ARCHIVO))
    return out


def main(a):
    if not a:
        print(__doc__, file=sys.stderr)
        return 1
    v = validar(a[0])
    if "--exportar" in a:
        if v["estado"] != "ok":
            print(json.dumps(v, ensure_ascii=False), file=sys.stderr)
            return 3
        for k, val in leer(v["archivo"]).items():
            if k != "AUTOPILOT_PERMITIR":
                sys.stdout.write("%s\0%s\0" % (k, val))
        return 0
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["estado"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))