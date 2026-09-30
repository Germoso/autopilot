#!/usr/bin/env python3
"""
cadena.py — aviso de CADENA DETENIDA: el autopilot quedo esperando al humano.

El sistema puede quedarse parado aunque no haya ninguna tarea "atascada" en un puesto: cuando todo
lo pendiente solo lo puede destrabar el humano (tareas en done sin revisar, en stopped, o bloqueadas
por dependencias de una done). Este vigia avisa una vez por episodio por Telegram, y re-avisa cada
CADENA_REAVISO_MIN mientras siga parado. Lo llama el watcher en cada vuelta (cuesta poco; en pausa
explicita no avisa).

Estado por proyecto en ~/.cache/autopilot-kit/cadena-<hash>.json:
  {"desde": epoch | null, "avisada": bool, "ultimo_aviso": epoch | null}

uso: cadena.py <autopilot.env> [--simular]   JSON con el estado de la cadena y si avisa
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workitems as wi  # noqa: E402


def estado_path(env):
    """Archivo de estado por proyecto (no comparte contadores entre boards)."""
    return wi.cache_kit("cadena-%s.json" % hashlib.sha1(os.path.abspath(env).encode()).hexdigest()[:10])


def leer_estado(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def guardar_estado(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wi.escribir_atomico(path, json.dumps(d))


def decidir(prev, parada, ahora, min_cadena, reaviso):
    """(desde, avisar, avisada, ultimo_aviso) para la proxima corrida.

    - parada recien detectada: desde = ahora (empieza a contar), no avisa todavia.
    - desde hace min_cadena minutos: avisa una vez (avisada = True).
    - mientras siga parada: re-avisa solo pasadas `reaviso` horas del ultimo aviso.
    - sin parada: se resetea todo (el proximo episodio vuelve a avisar).
    """
    if not parada:
        return None, False, False, None
    desde = prev.get("desde") or ahora
    minutos = (ahora - desde) / 60
    avisada = bool(prev.get("avisada"))
    ultimo = prev.get("ultimo_aviso")
    primero = not avisada and minutos >= min_cadena
    de_nuevo = avisada and reaviso > 0 and (ultimo is None or ahora - ultimo >= reaviso * 60)
    if primero or de_nuevo:
        return desde, True, True, ahora
    return desde, False, avisada, ultimo


def texto(cond, minutos):
    """El mensaje de Telegram (el prefijo [proyecto] y 🚨 los pone telegram.enviar)."""
    p = cond["pendiente"]
    partes = []
    if p.get("done"):
        partes.append("%d en done sin revisar" % p["done"])
    if p.get("en_espera"):
        partes.append("%d bloqueadas por dependencias" % p["en_espera"])
    if p.get("stopped"):
        partes.append("%d en stopped" % p["stopped"])
    return ("🧊 El autopilot esta detenido hace %d min esperandote: %s. "
            "Revisa y mergea en la web o con /reviewed <clave> para destrabar."
            % (int(minutos), " · ".join(partes) or "sin detalles"))


def info(env):
    """Estado de la cadena para la web: condicion de Board.cadena() + minutos detenida."""
    cfg = wi.cargar_config(env)
    cond = wi.Board(cfg).cadena()
    st = leer_estado(estado_path(env))
    cond["minutos"] = max(1, round((time.time() - st["desde"]) / 60)) \
        if cond["parada"] and st.get("desde") else None
    return cond


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    env, simular = a[0], "--simular" in a[1:]
    cfg = wi.cargar_config(env)
    b = wi.Board(cfg)
    cond = b.cadena()
    ahora = time.time()
    path = estado_path(env)
    desde, avisar, avisada, ultimo = decidir(leer_estado(path), cond["parada"], ahora,
                                             cfg["cadena"]["min"], cfg["cadena"]["reaviso"])
    if not simular:
        guardar_estado(path, {"desde": desde, "avisada": avisada, "ultimo_aviso": ultimo})
        if avisar and cond["parada"]:
            msg = texto(cond, (ahora - desde) / 60 if desde else 0)
            b.avisar(msg, alerta=True, dedup=True)
            b.log("Cadena detenida: el autopilot espera al humano", "vigia", "nota", "-", "-", "-", msg[:800])
    print(json.dumps({"parada": cond["parada"], "pendiente": cond["pendiente"],
                      "asignables": cond["asignables"], "pausa": cond["pausa"],
                      "desde": desde, "avisar": avisar}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except wi.Error as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(3)