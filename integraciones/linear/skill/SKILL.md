---
name: linear-sync
description: Importa issues de Linear al board de workitems (carpetas + .md) como new. Usar cuando el usuario mencione linear-sync, sincronizar Linear, importar issues de Linear, o /linear-sync. NO usar en proyectos sin linear-sync.env.
---

# Linear Sync — importador de Linear al board de workitems

Trae los issues de un team de Linear al board, como archivos en `new/`, para que el
autopilot pueda trabajar sobre ellos. Es el espejo de la skill `azure-sync` para otro tracker.

## Cuándo usar

Solo si el proyecto tiene `linear-sync.env` en la raíz. Si no existe, el proyecto
**no importa de Linear**. No lo busques en otro sitio ni lo adivines.

## Qué es y qué no es

Es **aditivo**:

| Garantía | Cómo se cumple |
|---|---|
| Solo crea, nunca modifica | Solo escribe archivos nuevos en `new/`. Nunca mueve, edita ni borra uno existente |
| Dedup por `<team>_<numero>` | Si ya hay un `*-<team>_<numero>-*.md` en **cualquier** carpeta del board, lo salta |
| Idempotente | Correrlo N veces crea la tarea una sola vez. Las otras N-1 son `no-op` |
| Falla ruidosa | Si Linear falla o el board no existe, sale con código ≠ 0 y no toca el board |
| La API key nunca se hardcodea | Se lee del entorno o de `linear-sync.secrets.env` |

**Nunca** mueve, borra ni sobrescribe una tarea existente. **Nunca** borra ni archiva.

Es una integración **externa** al autopilot: solo usa la API pública del board
(`workitems.py` del kit instalado), igual que `wi.sh add-task`. El autopilot no sabe que
existe Linear.

## Arranque

1. Verifica que existe `linear-sync.env` en la raíz del proyecto actual. Si no existe, para
   y dile al usuario que este proyecto no importa de Linear (se prepara copiando
   `linear-sync.env.example` de la integración; ver "Configurar un proyecto nuevo"). No lo
   busques en otro sitio ni lo adivines.
2. Verifica que hay una API key: variable `LINEAR_API_KEY` o `linear-sync.secrets.env` junto
   al config. Si no hay, explica cómo generarla (Linear → Settings → Security & access →
   Personal API keys) y para. **No la pidas en el chat** ni la escribas en un archivo
   versionado.
3. Corre primero en `--dry-run` y muestra el resumen: cuántos issues hay en backlog/unstarted
   en Linear, cuántos ya están en el board y cuáles se importarían.
4. Si el usuario pidió sincronizar de verdad, corre sin `--dry-run` y reporta el JSON: cuántos
   se agregaron, cuántos se saltaron por duplicado y si hubo errores.
5. Si se importó algo, dile que puede encadenar `/autopilot`. No lo arranques salvo que lo pida.
6. Si el script devuelve error, no reintentes a lo bruto: reporta el error. Un error de
   GraphQL de Linear suele decir exactamente qué campo o filtro falló.

```sh
K=~/.local/share/autopilot-kit/integraciones/linear
P=<PROYECTO>

python3 "$K/linear-sync.py" --config "$P/linear-sync.env" --dry-run   # que haria, sin escribir
python3 "$K/linear-sync.py" --config "$P/linear-sync.env"             # una pasada
python3 "$K/linear-sync.py" --config "$P/linear-sync.env" --status    # solo diagnostico
python3 "$K/linear-sync.py" --config "$P/linear-sync.env" --watch 300 # bucle continuo (intervalo generoso: Linear desaconseja polling seguido)
python3 "$K/linear-sync.py" --config "$P/linear-sync.env" --refrescar [clave...]  # re-trae descripcion/adjuntos de tareas ya importadas (no cambia estado ni notas)
```

## Fuente: un team (por ahora)

`linear-sync.env` (se copia a mano, no hay detección automática de remoto como en Azure):

```ini
LINEAR_TEAM=ENG

# Solo si el board es un workspace de varios repos:
# LINEAR_REPO=Konectame_App_Clientes
```

- `LINEAR_TEAM` es la *key* corta del team (la de sus issues, ej. `ENG` en `ENG-123`).
- Por ahora sincroniza un solo team por config. Si el board es un workspace (varios repos),
  `LINEAR_REPO` dice a qué repo van sus tareas; ese repo necesita su `REPO.<repo>` en
  `autopilot.env`.

## Adjuntos: capturas y videos

Cada issue importado trae sus adjuntos a `.workitems/adjuntos/<clave>/`:

- **Imágenes** pegadas en la descripción (markdown hacia `uploads.linear.app`): se descargan
  y quedan referenciadas en su lugar como `📷 <archivo> — imagen N` (no incrustadas; la app
  web las muestra en *Tarea original*).
- **Adjuntos** del issue (links a Figma, GitHub, archivos, etc.), listados en `## Adjuntos`.
  La API key solo se manda a hosts `*.linear.app`.
- **Videos:** con `ffmpeg` instalado se extraen hasta 12 fotogramas en `<video>.frames/fNN.png`.
  Sin ffmpeg se guarda el video y queda la nota; después: `linear-sync.py --config ... --fotogramas`.
- Límite de 50 MB por archivo. Un adjunto que falla no frena la importación: queda anotado.

El autopilot le pasa las imágenes y fotogramas al coder, al QA y al agente E2E (`tarea.adjuntos`).

## Criterio de filtro

Solo entra lo que está en un estado de **tipo `backlog` o `unstarted`** del team configurado
(Linear agrupa los workflow states, que cada equipo nombra distinto, en esos tipos fijos). No
filtra por ciclo/sprint.

Cuando mueves un issue a otro estado en Linear, el script deja de verlo, **pero la tarea sigue
en el board** en la carpeta donde la dejó el autopilot. `--refrescar` sí lo sigue encontrando
por su número para traer la descripción/adjuntos actualizados.

## Mapeo de prioridad

| Linear `priority` | `prioridad` |
|---|---|
| 1 (Urgent) | `Critical` |
| 2 (High) | `High` |
| 3 (Medium) | `Medium` |
| 4 (Low) | `Low` |
| 0 / ausente | `Medium` |

## Qué escribe en cada tarea

Un archivo `new/<tipo>-<team>_<numero>-<slug>.md`:

| Campo | Valor |
|---|---|
| nombre de archivo | `bug-eng_123-login-falla.md` — `tipo` sale de la label `Bug` (si la tiene), si no `task` |
| `# título` | `title` del issue |
| `id` | `<team>_<numero>` |
| `tipo` | `task` o `bug` |
| `prioridad` | mapeada desde Linear |
| `rama` | `<tipo>-<team>_<numero>`: la rama que el autopilot creará desde `BASE_BRANCH` |
| `origen` | `linear:<team key>` |
| `## Descripción` | `description` del issue (ya en Markdown) |
| `## Criterio de aceptación` | `_Sin criterio en Linear._` (Linear no tiene un campo equivalente) |
| `## Adjuntos` | capturas, videos y fotogramas (ver arriba) |

## Configurar un proyecto nuevo

1. El proyecto tiene que tener el autopilot preparado (`/autopilot-init`).
2. Copia `~/.local/share/autopilot-kit/integraciones/linear/linear-sync.env.example` a la raíz
   del proyecto como `linear-sync.env` y completa `LINEAR_TEAM` (y `LINEAR_REPO` si hace falta).
3. Generá una Personal API Key en Linear y guardala en `linear-sync.secrets.env` junto al
   config (nunca en el chat ni en un archivo versionado).

`linear-sync.secrets.env` debe estar en `.gitignore` (ya lo cubre el patrón `*.secrets.env`).

## Diferencia con el autopilot

| | linear-sync | autopilot |
|---|---|---|
| Qué hace | crea archivos en `new/` | trabaja las tareas |
| Consume tokens | **no** | sí |
| Puede ser demonio | **sí**, con `setsid` | no, corre en el hilo |
| Cuándo corre | cuando quieras (sin pasarte del límite de requests de Linear) | mientras haya un turno |

linear-sync no lanza agentes, así que es seguro correrlo en background. Si importó algo
y hay tareas en `new/`, puedes encadenar `/autopilot` en el mismo turno.

## Lo que NUNCA debes hacer

- Modificar, mover o borrar tareas que ya existen en el board
- Hardcodear la API key en cualquier archivo
- Mandar la API key de Linear a un host que no sea `*.linear.app` al bajar un adjunto
- Correr sin `linear-sync.env` en el proyecto
