#!/usr/bin/env python3
"""
oc_sesion.py — Subagentes en segundo plano para OpenCode, via la API de su servicio local.

OpenCode puede correr varios subagentes en paralelo, pero el agente principal espera a que
terminen. Para que el coder y el QA trabajen de verdad en paralelo (y el principal siga
atendiendo el board), cada tarea corre en SU PROPIA SESION de OpenCode:

  lanzar    crea la sesion con el agente (coder / qa-reviewer) en la carpeta del
            proyecto, le manda el encargo (con imagenes adjuntas) y NO espera: /prompt agenda
            la ejecucion y devuelve enseguida.
  estado    activa / terminada (+ outcome: succeeded, failed, interrupted).
  resultado el texto final del agente, para leer su veredicto y sus notas.

Las sesiones se ven en la lista de sesiones de OpenCode: se pueden abrir y mirar en vivo.
Mismo costo en tokens que un subagente. Habla con el servicio con `opencode api` (que ya sabe
autenticarse); no guarda credenciales.

uso:
  oc_sesion.py lanzar <agente> <carpeta> <titulo> <archivo_encargo|-> [--adjunto <ruta>]...
  oc_sesion.py estado <ses_id>
  oc_sesion.py resultado <ses_id>
"""
import json
import os
import shutil
import subprocess
import sys


class Error(Exception):
    pass


def api(metodo, ruta, cuerpo=None, timeout=60):
    if not shutil.which("opencode"):
        raise Error("opencode no esta en el PATH")
    cmd = ["opencode", "api", metodo, ruta]
    if cuerpo is not None:
        cmd += ["-d", json.dumps(cuerpo, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=os.path.expanduser("~"))
    if r.returncode != 0:
        raise Error("opencode api %s %s: %s" % (metodo, ruta, (r.stderr or r.stdout).strip()[:300]))
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise Error("opencode api %s %s no devolvio JSON: %s" % (metodo, ruta, r.stdout[:200]))


def lanzar(agente, carpeta, titulo, encargo, adjuntos=()):
    carpeta = os.path.abspath(carpeta)
    ses = api("POST", "/api/session", {"agent": agente, "title": titulo,
                                        "location": {"directory": carpeta}})["data"]["id"]
    files = [{"uri": "file://" + os.path.abspath(p), "name": os.path.basename(p)}
             for p in adjuntos if os.path.isfile(p)]
    api("POST", "/api/session/%s/prompt" % ses, {"text": encargo, "files": files})
    return {"sesion": ses, "agente": agente, "adjuntos": len(files)}


def estado(ses):
    """{'activa': bool, 'outcome': ...} o None si no se puede consultar (sin OpenCode)."""
    try:
        activas = api("GET", "/api/session/active", timeout=20)["data"]
    except (Error, subprocess.TimeoutExpired, KeyError):
        return None  # OpenCode no disponible: no se sabe, el puesto sigue ocupado
    if ses in activas:
        return {"activa": True, "outcome": None}
    try:
        info = api("GET", "/api/session/%s" % ses, timeout=20)["data"]
    except (Error, subprocess.TimeoutExpired, KeyError):
        # El servicio responde pero la sesion no existe (borrada): el puesto no puede quedar tomado.
        return {"activa": False, "outcome": "no-encontrada"}
    return {"activa": False, "outcome": info.get("outcome")}


def resultado(ses):
    """Texto final del agente: el ultimo mensaje del asistente con texto."""
    msgs = api("GET", "/api/session/%s/message?order=desc&limit=30" % ses)["data"]
    for m in msgs:
        partes = m.get("content") if isinstance(m.get("content"), list) else []
        texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and p.get("type") == "text")
        if m.get("type") == "assistant" and texto.strip():
            return texto.strip()
    raise Error("la sesion %s no tiene respuesta del agente" % ses)


def main(a):
    try:
        if a[:1] == ["lanzar"] and len(a) >= 5:
            adj, resto, i = [], a[5:], 0
            while i < len(resto):
                if resto[i] == "--adjunto" and i + 1 < len(resto):
                    adj.append(resto[i + 1]); i += 2
                else:
                    raise Error("argumento desconocido: %s" % resto[i])
            encargo = sys.stdin.read() if a[4] == "-" else open(a[4], encoding="utf-8").read()
            print(json.dumps(lanzar(a[1], a[2], a[3], encargo, adj), ensure_ascii=False))
        elif a[:1] == ["estado"] and len(a) == 2:
            print(json.dumps(estado(a[1]), ensure_ascii=False))
        elif a[:1] == ["resultado"] and len(a) == 2:
            print(resultado(a[1]))
        else:
            print(__doc__, file=sys.stderr)
            return 1
        return 0
    except Error as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
