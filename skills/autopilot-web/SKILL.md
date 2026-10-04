---
name: autopilot-web
description: Arranca y gestiona la app web del autopilot (tablero de tareas en el navegador): la levanta desacoplada del cliente, detecta si ya esta corriendo, la detiene o la rearranca en otro modo (lan, puerto) y reporta URL, PID, modo y proyectos. Usar cuando el usuario diga /autopilot-web, "abre la web", "arranca la app web", "quiero ver el tablero en el navegador" o "quiero verlo desde el celular".
---

# Autopilot Web

Arranca y gestiona la app web del kit (`autopilot-web`, servidor en `lib/web/servidor.py`).
**No implementa nada nuevo**: todo lo hace el script que ya viene en el kit; esta skill solo
decide qué comando correr y qué reportar.

```sh
K=~/.local/share/autopilot-kit        # el kit instalado
W=$K/autopilot-web                    # el lanzador
LOG=~/.cache/autopilot-kit/web.log    # salida del servidor
PUERTO_DEF=8765
```

## Arranque

### 1. Verificar que el kit está instalado

Si no existe `$W`, diles que el kit no está instalado y que lo instalan con
`cd ~/code/dotenvs && ./install.sh`. **No** intentes instalarlo tú. Fin.

### 2. Detectar si ya está corriendo

```sh
pgrep -f "autopilot-kit/web/servidor[.]py"
```

> El `[.]` no es decorativo: sin él, el `pgrep` se encuentra a sí mismo en la línea de
> comandos del shell y siempre "encuentra" un proceso. Igual que abajo, busca la **ruta
> completa del kit**, no solo `servidor.py`.

Si hay PID(s), para el que sea del kit lee sus argumentos y su puerto:

```sh
tr '\0' ' ' < /proc/<pid>/cmdline      # muestra: .../autopilot-web --lan --port 9000
```

- **Modo**: tiene `--lan` → "lan (red local, con clave)"; si no → "local (solo esta PC)".
- **Puerto**: el de `--port`, si no, `8765`.
- **URL**: `http://localhost:<puerto>/` (con `--lan`, la IP de la red la da el propio
  servidor al arrancar; se puede ver en `$LOG`).

Comprueba que responde:

```sh
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<puerto>/api/sesion   # 200 = viva
```

**Ya corriendo → NO la mates: reporta y pregunta.** Di algo como:

> Ya está corriendo: `http://localhost:8765` (PID 1234, modo local).
> ¿La detengo, la rearranco en otro modo (lan / otro puerto) o la dejo así?

Y sigue lo que elija:

- **dejar** → terminas con la URL y el PID. Nada más.
- **detener** → sección *Detener*.
- **rearrancar en otro modo** → sección *Detener* y después el paso 3 con el modo nuevo.

Si hay PID pero **no responde** (moribunda o es un proceso ajeno que solo coincide en el
nombre), dilo: *no responde; puedo matarla y arrancarla de nuevo. ¿Procedo?* Espera sí/no.

### 3. Arrancar (desacoplado del cliente)

La web **vive independiente**: aunque cierres el cliente, el servidor sigue. Se lanza con
`setsid nohup` y se redirige la salida a `$LOG` (ahí quedan los errores, p. ej. puerto ocupado).

**Lanza SIEMPRE desde la carpeta del proyecto abierto** (cwd de la sesión): `servidor.py`
registra solo el `autopilot.env` que encuentre en el cwd o su padre, y así el proyecto actual
aparece en el selector.

```sh
mkdir -p ~/.cache/autopilot-kit
setsid nohup $W [--lan] [--port <n>] > "$LOG" 2>&1 < /dev/null &
```

Argumentos según lo pedido:

| El usuario pidió | Argumento |
|---|---|
| (nada) | sin argumentos — solo `127.0.0.1:8765` |
| "desde el celular" / `lan` | `--lan` |
| `puerto <n>` / `port <n>` | `--port <n>` |

Con `--lan`, en tu respuesta incluye SIEMPRE: va **sin HTTPS** (solo redes de confianza), la
clave está en `~/.config/autopilot-kit/web.env` (se crea sola la primera vez) y la URL con la
IP de la red (sale del `$LOG`).

**Verifica que arrancó** (espera ~2 s):

```sh
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<puerto>/api/sesion   # esperado: 200
```

- **200** → arrancó.
- **otro / nada** → lee `$LOG` y reporta el motivo real (p. ej. `Address already in use`:
  otro proceso usa el puerto → ofrece otro puerto con `--port`; o error de Python → copia el
  error). **No** lo reintentes en loop más de una vez.

## Detener (solo si lo pidió)

Nunca mates sin que lo haya pedido en esta conversación (puede ser una instancia que abrió él
a mano en su terminal).

```sh
# 1. confirma que el PID es del kit (no un proceso ajeno que coincide en el nombre)
tr '\0' ' ' < /proc/<pid>/cmdline | grep -q "autopilot-kit/web/servidor.py" || echo "no es del kit"
# 2. mata y verifica
kill <pid>            # si en 5 s no murió: kill -9 <pid>
pgrep -f "autopilot-kit/web/servidor[.]py" || echo "detenida"
```

Reporta "detenida (PID …)". Si el PID no es del kit, **no lo mates**: dilo y pregunta.

## Qué reportar siempre

Al final de cada invocación, una respuesta corta con:

1. **URL** (`http://localhost:8765`, o la IP + clave si es `--lan`).
2. **PID** y **modo** (local / lan) y puerto.
3. **Proyectos del selector**:
   ```sh
   curl -s http://127.0.0.1:<puerto>/api/proyectos
   ```
   Lista los `nombre`. Si devuelve `401` (es `--lan`, pide clave), dilo y no insistas: solo
   muestra la URL y la ruta de `web.env`.
   - **Lista vacía** → "Ningún proyecto registrado todavía: corre `/autopilot-init` en uno."
   - **Proyecto actual no registrado** (no aparece el de esta carpeta) → arrancó fuera del
     proyecto: informa que se registra cuando se corre desde la carpeta con `autopilot.env`.
4. **Rutas muertas** en `~/.config/autopilot-kit/proyectos.json` que ya no existen
   (`os.path.isfile` falla, la web las oculta del selector): solo avísalas
   ("hay N rutas en el registro que ya no existen; puedes borrarlas del JSON").
   **No** edites ese archivo sin que te lo pida.

## Reglas

- **Nunca** mates un servidor que no hayas arrancado tú sin preguntar.
- **No** uses `--lan` salvo que lo pida; es sin HTTPS.
- **No** edites `web.env`, `proyectos.json` ni nada de `~/.config/autopilot-kit/` salvo que
  te lo pidan.
- La web **no necesita** `autopilot.env` para arrancar (lista todos los proyectos del kit);
  solo para que el proyecto actual aparezca en el selector.
- Si el usuario pregunta por los proyectos o el tablero, la web es solo una vista: el estado
  real está en `.workitems/autopilot.db` (`wi.sh`), y los botones de la web llaman a `wi.sh`.
