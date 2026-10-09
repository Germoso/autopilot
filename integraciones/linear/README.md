# Integración: Linear → board del autopilot

El autopilot **no depende de Linear**: trabaja lo que hay en su board. Esta carpeta es una
integración **opcional y externa** que trae issues de Linear al board, usando la misma API
que usarías a mano (`workitems.py` del kit: crear tareas en `new/` y guardar sus adjuntos).
Es el espejo de [integraciones/azure](../azure/README.md) para otro tracker.

| Archivo | Qué es |
|---|---|
| `linear-sync.py` | importador aditivo de issues (GraphQL, un team) |
| `skill/` | skill `/linear-sync` para OpenCode y Claude Code |
| `linear-sync.env.example` | config por proyecto |
| `instalar.sh` | instala todo lo anterior (requiere el kit ya instalado) |

## Instalar

```sh
./install.sh                                    # primero el kit del autopilot (raíz del repo)
integraciones/linear/instalar.sh                # skill /linear-sync + script
integraciones/linear/instalar.sh --uninstall
```

Los scripts quedan en `~/.local/share/autopilot-kit/integraciones/linear/`. `./install.sh --uninstall`
del kit también desinstala la integración.

## Configurar un proyecto

Con el proyecto ya preparado (`/autopilot-init`), copia `linear-sync.env.example` a la raíz del
proyecto (junto a `autopilot.env`) como `linear-sync.env`:

```ini
LINEAR_TEAM=ENG

# Solo si el board es un workspace de varios repos:
# LINEAR_REPO=Konectame_App_Clientes
```

- **`LINEAR_TEAM`** es la *key* corta del team (la que aparece en sus issues, ej. `ENG` en
  `ENG-123`), no su nombre completo.
- Por ahora la integración sincroniza **un solo team** por `linear-sync.env`. Si más adelante
  hace falta un workspace con varios teams (uno por repo), se agrega igual que `SYNC.<repo>`
  en la integración de Azure.
- En modo un repo no hace falta `LINEAR_REPO`. En un workspace sí, y ese repo necesita su
  `REPO.<repo>` en `autopilot.env`.
- Agrega `linear-sync.env` a `.git/info/exclude` para no commitearlo.
- **API key:** Personal API Key de Linear (Settings → Security & access → Personal API keys),
  con acceso de lectura al team. Se busca en `LINEAR_API_KEY` o en `linear-sync.secrets.env`
  (junto al config). Nunca en un archivo versionado ni en el chat.

## Uso

```sh
/linear-sync      # desde el agente: dry-run, confirma e importa
```

```sh
K=~/.local/share/autopilot-kit/integraciones/linear
python3 $K/linear-sync.py --config ./linear-sync.env --dry-run
python3 $K/linear-sync.py --config ./linear-sync.env
```

Importa a `new/` los issues del team cuyo **workflow state es de tipo `backlog` o
`unstarted`** (sin filtrar por ciclo/sprint), con clave `<tipo>-<team>_<numero>` (p. ej.
`bug-eng_123`) y `origen: linear:<team key>`. Solo crea, nunca modifica; no gasta tokens;
deduplica por `<team>_<numero>` (único dentro del team).

- Si la fuente falla, no se escribe nada en el board.
- `--refrescar [clave…]` vuelve a traer de Linear la descripción y los adjuntos de tareas
  **ya importadas** (sin claves: todas), encontrando el issue por su número aunque ya haya
  avanzado de columna en Linear. No cambia su estado ni toca notas, reportes ni feedback.
- `--dry-run` muestra qué importaría (con cuántas imágenes/adjuntos); `--status` cuenta
  pendientes; `--watch 300` en bucle (Linear desaconseja el polling seguido: usa un intervalo
  generoso); `--fotogramas` procesa videos ya descargados (tras instalar ffmpeg).

Puede correr como demonio, porque no lanza agentes:

```sh
setsid nohup python3 ~/.local/share/autopilot-kit/integraciones/linear/linear-sync.py \
  --config ./linear-sync.env --watch 300 &>/dev/null &
```

### Límite de requests

La API de Linear permite 2500 requests/hora por API key. El script hace pocas llamadas por
pasada (una para listar pendientes + una por issue nuevo), así que es difícil chocar el
límite salvo con `--watch` muy seguido; si pasa, el script lo reporta y sale sin tocar el
board (nunca reintenta a lo bruto).

### Adjuntos: capturas y videos

Cada issue importado trae sus adjuntos a `.workitems/adjuntos/<clave>/` (en el board aparecen
como *Tarea original*):

- **Imágenes** pegadas en la descripción (markdown `![alt](url)` hacia `uploads.linear.app`):
  se descargan y quedan referenciadas en su lugar en el texto como `📷 <archivo> — imagen N`.
- **Adjuntos** del issue (links a Figma, GitHub, archivos subidos, etc.), listados en la
  sección `## Adjuntos`. La API key de Linear **solo** se manda al bajar archivos de
  `*.linear.app`; a cualquier otro host (Figma, GitHub, Sentry...) se descarga sin ella.
- **Videos:** con `ffmpeg` instalado se extraen hasta 12 fotogramas (primer cuadro + cambios
  de escena, repartidos) en `<video>.frames/fNN.png`, porque ningún modelo ve video
  directamente. Sin ffmpeg se guarda el video y queda la nota; después:
  `linear-sync.py --config ... --fotogramas`.
- Límite de 50 MB por archivo. Un adjunto que falla no frena la importación: queda anotado.

## Criterio de filtro

Solo entra lo que está en un estado de **tipo `backlog` o `unstarted`** en Linear, del team
configurado. Linear agrupa los workflow states (que cada equipo puede nombrar distinto) en
tipos fijos (`backlog`, `unstarted`, `started`, `completed`, `canceled`); por eso se filtra
por tipo y no por el nombre del estado.

No filtra por ciclo (el "sprint" de Linear): si tu equipo usa ciclos y querés acotarlo a uno,
avisá — se puede agregar un filtro de ciclo actual, análogo a `@current` en Azure.

Cuando movés un issue a otro estado en Linear, el script deja de verlo en el listado de
pendientes, **pero la tarea sigue en el board** en la carpeta donde la dejó el autopilot. No
hay reconciliación en sentido inverso: el board no refleja Linear en tiempo real, solo se
alimenta de él. `--refrescar` sí sigue encontrando la tarea por su número para traer su
descripción/adjuntos actualizados, sin importar en qué estado esté ahora en Linear.

## Mapeo de prioridad

| Linear `priority` | `prioridad` |
|---|---|
| 1 (Urgent) | `Critical` |
| 2 (High) | `High` |
| 3 (Medium) | `Medium` |
| 4 (Low) | `Low` |
| 0 (sin prioridad) / ausente | `Medium` |

## Qué escribe en cada tarea

Un archivo `new/<tipo>-<team>_<numero>-<slug>.md`:

| Campo | Valor |
|---|---|
| nombre de archivo | `bug-eng_123-login-falla.md` — `tipo` sale de la label `Bug` (si la tiene) o `task` |
| `# título` | `title` del issue |
| `id` | `<team>_<numero>` (ej. `eng_123`) |
| `tipo` | `task` o `bug` |
| `prioridad` | mapeada desde Linear |
| `rama` | `<tipo>-<team>_<numero>`: la rama que el autopilot creará desde `BASE_BRANCH` |
| `origen` | `linear:<team key>` |
| `## Descripción` | `description` del issue (ya es Markdown en Linear: no hace falta convertir) |
| `## Criterio de aceptación` | `_Sin criterio en Linear._` — Linear no tiene un campo equivalente a `AcceptanceCriteria` de Azure |
| `## Adjuntos` | capturas, videos y fotogramas (ver arriba) |

`<tipo>-<team>_<numero>` es a la vez la clave de la tarea, la base del dedup y el nombre de la rama.
Se usa ese id corto y no el identifier de Linear (`ENG-123`) porque la clave del board no admite guiones.

## Configurar un proyecto nuevo

1. El proyecto tiene que tener el autopilot preparado (`/autopilot-init`).
2. Copia `~/.local/share/autopilot-kit/integraciones/linear/linear-sync.env.example` (o el del
   repo del kit, `integraciones/linear/`) a la raíz del proyecto como `linear-sync.env` y
   completa `LINEAR_TEAM` (y `LINEAR_REPO` si el board es un workspace).
3. Generá una Personal API Key en Linear (Settings → Security & access) y guardala:

```sh
(umask 077; printf 'LINEAR_API_KEY=%s\n' "$(read -rsp 'API key: ' k; echo "$k")" > linear-sync.secrets.env)
```

`linear-sync.secrets.env` queda bloqueado por el `.gitignore` del repo (`*.secrets.env`).

## Diferencia con el autopilot

| | linear-sync | autopilot |
|---|---|---|
| Qué hace | crea archivos en `new/` | trabaja las tareas |
| Consume tokens | **no** | sí |
| Puede ser demonio | **sí**, con `setsid` | no, corre en el hilo |
| Cuándo corre | cuando quieras (sin pasarte del límite de requests) | mientras haya un turno |

linear-sync no lanza agentes, así que es seguro correrlo en background. Si importó algo
y hay tareas en `new/`, puedes encadenar `/autopilot` en el mismo turno.

## Sobre algunos detalles de la API de Linear

Al escribir esta integración, dos comportamientos de la API de Linear no tenían un ejemplo
documentado verbatim y se infirieron por analogía (el script los prueba en tiempo de
ejecución, no se adivinan a ciegas):

- El filtro de issues por team (`team: { id: { eq: "<uuid>" } }`): se resuelve primero el
  `id` del team listando `teams { nodes { id key name } }` (sin filtro), así no depende de
  si Linear acepta filtrar `teams` por `key`.
- Si hace falta el prefijo `"Bearer "` para descargar archivos de `uploads.linear.app` con
  una Personal API Key: `descargar()` intenta primero sin el prefijo y, si Linear responde
  401, reintenta con `"Bearer <key>"`.

Si `--dry-run` falla con un error de GraphQL, el mensaje de Linear suele decir exactamente
qué campo o filtro no es el esperado — es el punto donde ajustar la query.

## Lo que NUNCA debes hacer

- Modificar, mover o borrar tareas que ya existen en el board
- Hardcodear la API key en cualquier archivo
- Mandar la API key de Linear a un host que no sea `*.linear.app` al bajar un adjunto
- Correr sin `linear-sync.env` en el proyecto
