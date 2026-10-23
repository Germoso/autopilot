---
name: autopilot
description: 'Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown (.workitems/), ejecutado por Orca: el orquestador crea un worktree por tarea con `orca worktree create`, lanza al coder **SIEMPRE como agente supervisado por Orca** con `orca orchestration worker-start --agent <AGENT>` (el agente que se configure, pi por defecto; funciona sin cuentas y corre en un terminal de Orca visible al humano) y el humano revisa en done (si pide cambios vuelve a new; lo que no se pudo va a stopped). Board de 4 estados: new / working / done / stopped. Sin QA ni E2E. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.'
---
# Sistema Autónomo de Desarrollo (Autopilot)

El autopilot trabaja las tareas de un **board de workitems** (carpetas + `.md`) y
tú, el agente principal (**orquestador**), diriges la ejecución con **Orca**: un
**coder** por tarea, cada uno en su propio `git worktree` (rama `task-<id>` /
`bug-<id>`), sin push ni merge. El humano es el revisor final: las tareas
terminadas pasan a `done` y él las revisa ahí: si están bien quedan (estado
final); si pide cambios, vuelven a `new/` como una tarea más.

```
 tarea (new) ──> CODER ──────────────> done
                 la programa en        tú revisas (si pedís cambios,
                 su rama y commitea     vuelve a new con ## Feedback del humano)
```

- **Un coder por tarea** (la toma de `new/`; si el humano pidió cambios, la vuelve
a tomar con el feedback). No hay QA ni E2E: la certificación la hace el humano
cuando revisa la tarea de `done`.
- Cada tarea tiene **su propia rama** desde la rama base por defecto que **Orca
define para su repo** (no se configura en el kit: `orca worktree create` sin
`--base-branch` usa la del repo). **Nunca hace push**: el merge lo haces
tú a mano, o el autopilot solo con `AUTO_MERGE=true` (solo local, sin push).
- **Nunca toca producción**: el coder solo se conecta a BD/API con `aenv.sh`, que
valida el `.env.autopilot` que tú creaste.
- Orca gestiona los **worktrees**, los **terminales** y la **orquestación**  
(lanzar, vigilar y recibir a los agentes). El board (estados y notas) son solo  
archivos `.md`, que tú y el orquestador leen y mueven.

## Cuándo usar esta skill

Solo si el proyecto tiene un archivo `autopilot.env` en la raíz (o en la carpeta
padre de un workspace). Si no existe, este proyecto **no participa** del sistema.
No preguntes, no asumas, no la busques.

## Antes de arrancar: Orca

El autopilot necesita el runtime de Orca corriendo y el repo registrado:

```sh
orca status                       # runtime ready (si no: orca open)
orca repo add --path /ruta/al/repo           # registrar un repo (una vez por repo)
orca repo list                    # ver los repos registrados
```

En un **workspace** registra cada repo del proyecto. Cada worktree nace de la rama
base **por defecto** que Orca define para ese repo: aquí no se configura (ver más
abajo).

**REGLA INNEGOCIABLE: los coders SIEMPRE van como agentes supervisados de Orca.** Todo
coder se lanza con **`orca orchestration worker-start --agent <AGENT>`** (el agente que se
configure en `AGENT`, pi por defecto; corre en un terminal de Orca). Queda **PROHIBIDO**
lanzarlo como **subagente** o como **tarea de fondo del cliente** (bg / bg_run /
`pi -p` fuera de un terminal de Orca).

**Usa la skill de orca (`orchestration`).** Orca carga esa skill para el orquestador
(patrón *worker supervised*): es el contrato de `orca orchestration`
(`run-create` → `worker-start` → `check` (con o sin `--wait`: entrega los mensajes
encolados del inbox del run) → `reply` → `worker-release` / `worker-stop`). Cárgala en tu
cliente si la expone (pi: `/skill:orchestration`) y,
sobre todo, **no inventes un protocolo propio**: seguí el ciclo y los comandos que
define esa skill. Este documento trabaja sobre ese mismo contrato; ante cualquier
duda entre este texto y la skill de orca, manda la skill de orca.

## El board

`$BOARD` es la carpeta del board que define el **`autopilot.env`** de este proyecto: el
valor de **`WORKITEMS_DIR`** (por defecto `.workitems/`). **Todos los comandos de esta
skill usan `$BOARD` literal según tu `autopilot.env`** — por ejemplo si tu board vive en
`.board/`, los `<old>`/`<new>` de abajo son `.board/…`, nunca `.workitems/` a secas.

```
$BOARD/                              # WORKITEMS_DIR (default .workitems); NO esta en git
├── new/          bug-140123-login-falla-con-google.md   # tarea = archivo .md en la carpeta de su estado
├── working/      task-pagos_modelo.md
├── stopped/      task-pagos_modelo.md                  # no se pudo / necesita intervención tuya
├── done/         task-favoritar-tarjeta.md
├── adjuntos/<clave>/               # capturas, imagenes y videos (archivos)
├── planes/<slug>.md                # planes de /autopilot-plan
└── .autopilot/resultados/<clave>.md # (scratch) notas que escribe el coder al terminar
```

- **Solo hay 4 carpetas de estado** (`new/`, `working/`, `done/` y `stopped/`).
 `adjuntos/`, `planes/` y `.autopilot/resultados/` son de **apoyo**, no estados.

-  El orquestador **no edita los `.md` a mano** más que para añadir las
secciones del coder y del humano (y los mueve de carpeta al cambiar de estado).
- **Nombre del archivo = `<tipo>-<id>-<slug>.md`.** `<tipo>-<id>` es la **clave**
de la tarea y el **nombre de su rama** (`task-login_social`, `bug-140123`).
El `<id>` lo da quien crea la tarea: número (`140123`) o texto (`login_social`:
minúsculas, dígitos y `_`, sin `-`).
- **Cómo llegan las tareas es externo al autopilot**: se crea un `.md` en `new/`
(a mano, con `/autopilot-plan`, o desde una integración como Azure DevOps).
El autopilot solo trabaja lo que hay en el board.
- El board **no va en git** (`$BOARD/` está en el `.gitignore`, según `WORKITEMS_DIR`:
`.workitems/` por defecto, `.board/` si tu `autopilot.env` lo dice): si estuviera
versionado, al cambiar de rama cambiaría el tablero.

Una tarea se ve así (las secciones las van añadiendo el coder y el humano):

```markdown
<!-- autopilot: prioridad=High repo=Konectame_BackOffice origen=plan:pagos -->
# Favoritear una tarjeta

## Descripción
...

## Criterio de aceptación
- ...

## Notas del desarrollador
### Intento 1
- Que se hizo, por que, como probarlo...

## Feedback del humano
### ... (solo cuando el humano pide cambios)
...
```

## Arranque

1. Verifica que existe `autopilot.env` (en la carpeta abierta o en la carpeta
padre de un workspace). Si no existe, para y dile al usuario que no participa y
que se prepara con `/autopilot-init`.
2. Asegura Orca: `orca status`; registra el/los repo(s) (`orca repo add --path …`
si no están en `orca repo list`). El agente del coder se lanza con `worker-start
--agent <AGENT>` y **no requiere cuenta** (pi funciona directo; ver *El agente del coder*).
3. **Fija el agente del coder.** Lee `AGENT` de `autopilot.env` (ver *El agente del
 coder*): el agente que se lanza **dentro del terminal de Orca**. Si `AGENT` está
 vacío, usa **pi** por defecto. Si `AGENT` está definido (p. ej. `AGENT=claude`,
 `AGENT=opencode`), ese es el agente del coder **en todos los lanzamientos**.
4. Abre un **Run de orquestación** (una vez por sesión):
`orca orchestration run-create --objective "<breve resumen del trabajo de esta sesión>" --json`
— te devuelve el `run_id` (lo usan los comandos de orquestación).
5. Sigue **El bucle**.

El **coder siempre trabaja dentro del worktree de Orca** de su tarea (la ruta que
devuelve `orca worktree create`). Nunca en la copia principal del repo.

## REGLA DE ORO: la escucha nunca pierde un mensaje

Los mensajes de un coder (`question`/`escalation`/`worker_done`) quedan **encolados de
forma durable** en el inbox del Run: **no se pierden** aunque no estés leyendo en ese
momento. **Cualquier** `orca orchestration check` (con o sin `--wait`) entrega lo
pendiente en orden (FIFO); `--wait` es solo comodidad (evita el polling, bloqueando
hasta que llega algo o vence el timeout). El bucle es **resumible**, no eterno:

- Al empezar cada vuelta (o al despertar por un nudge "You have N orchestration
messages"), corre `check` **sin `--wait`** y procesa **TODAS** las deliveries pendientes
**antes de acusar** (`check --ack <delivery_id>`). Una delivery NO acusada se
**re-entrega** en el próximo check.
- Recién después, y **si no hay otro `check` en vuelo**, lanza `check --wait` para esperar
el siguiente evento sin polling. **Nunca dos lecturas simultáneas** del mismo run desde
el mismo orquestador.
- El nudge es solo **atención** ("hay N mensajes"), no el contenido: el contenido se lee
con `check`.
- Si te ausentás o terminás el turno con mensajes sin acusar, **no se pierden**: al volver
(misma sesión o la siguiente, mismo run/terminal), un `check` drena el inbox y procesás
lo que quedó, reconciliando con `worker-list`.
- **No inventes que hay un coder trabajando si no lo hay.** Orca dice la verdad
 (`worker-list`, `worker-show`); si un worktree quedó sin efecto, velo.

## NUNCA CONTRA PRODUCCIÓN (por encima de todo)

- Nadie (tú ni el coder) ejecuta nada contra producción.
- Lo que se conecta a una base de datos o API (tests de integración, levantar un
backend, migraciones, seeds, scripts, HTTP) corre **solo** con
`$K/aenv.sh <repo o worktree> -- <comando>` (`$K` = `/home/germoso/code/personal-hub/.autopilot`,
donde el instalador LOCAL dejó `aenv.sh` y `entorno.py`). Valida el **`.env.autopilot`** que
el humano creó y, si no es `ok`, **NO ejecuta** (salida 3) y dice qué hacer.
- Sin `aenv.sh` solo se corren cosas que **no se conectan a nada**: compilar,
analizar, lint, instalar dependencias, tests de unit/widget sin red.
- Nadie crea, edita ni copia `.env*`. Nadie cambia a mano la URL de API de una app
para probar.
- El orquestador tampoco ejecuta contra ambientes: si tiene que probar algo, se lo
delega al coder (que lo corre con `aenv.sh`).
- Un coder que se detiene por **posible producción** termina con
`RESULTADO: STOPPED` + `MOTIVO: POSIBLE PRODUCCIÓN: …` + `RECOMENDACIÓN: …`:
muévelo a `stopped/` tal cual, escribiendo al `.md` la sección `## Motivo de stopped`
con ese motivo. **No lo reintentes**: una tarea en `stopped/` no se relanza sola; lo
resuelve el humano (creando o corrigiendo `.env.autopilot`).
- **Motivo de `stopped`: en Markdown y con saltos de línea**, nunca todo en una
línea (el humano lo lee). Título con la causa, cada punto en su línea `- …` y la
recomendación en su propio párrafo.

## Determinismo: grilla ANTES de despachar

**Tú grillás la tarea antes de lanzar al coder** — el grill no es rango del coder, es tuyo y es
pre-dispatch. Usa **`grill-me`** (que invoca **`grilling`**: entrevista en rondas sobre un árbol de
decisiones, sin dejar ramas con supuestos silenciosos) y **`domain-modeling`/`grill-with-docs`**
cuando la tarea implica diseño o terminología del dominio. Esas skills (más `ponytail` y `tdd`)
quedan **instaladas LOCAL** con el kit; pi las expone como `/skill:grill-me`, `/skill:grilling`, etc.

- Grillá cada tarea de `new/` hasta que no quede rama con supuestos: decisiones de
diseño/dominio, alcance e intención resueltas ANTES de `worker-start`. El encargo (spec) se lo
lleva **ya aclarado**.
- El coder arranca de ese brief aclarado y trabaja con 100% de certeza o se detiene. Si pese a todo
le queda una duda, la resuelve con evidencia y, si persiste, te pregunta con su `ask` (queda
encolada durable; le respondes con `reply` cuando puedas; nunca con un TUI local que no puedes
ver ni responder) o termina con `RESULTADO: STOPPED` + `MOTIVO: DUDA NO RESUELTA: …` +
`RECOMENDACIÓN: …`. Nunca entrega algo con una suposición.
- Cuando te llegue un `STOPPED` por `DUDA NO RESUELTA`, muévelo a `stopped/` con `## Motivo de stopped` y la duda explicada. **No lo reintentes**: lo desbloquea el humano respondiendo la duda.
- Tú, como orquestador, tampoco adivines: si una orden del humano es ambigua, la misma regla
(pregunta con recomendación, o `stopped`); no lances un coder a adivinar.

## REGLAS DE GIT (sin excepciones)

- **Una rama independiente por workitem.** Nombre: `task-<id>` o `bug-<id>`.
- **Toda rama sale de la rama base que Orca tiene definida para su repo** (la base
por defecto; aquí no se configura: `orca worktree create` sin `--base-branch` usa
la del repo), nunca de otra. El worktree y su rama se crean con **`orca worktree create`**:
  - repo:   `orca worktree create --name <clave> --repo <selector> [--activate]`
  - workspace: una por repo de la tarea con `--repo <carpeta>`.
  Devuelve la ruta del worktree (ahí trabaja el coder).
- **NUNCA `git push`. NUNCA `git merge`** (salvo el humano, o `AUTO_MERGE=true`, que
mergea **solo local**). Tampoco `git rebase`, borrar ramas ni `reset --hard`.
- El tipo de la rama (`task`/`bug`) es el tipo del workitem, no el estado:
un `bug-140123` rechazado por el humano se sigue corrigiendo en `bug-140123`.

## El bucle

Cada vuelta del orquestador: (0) drena el inbox con `check` sin `--wait` y procesa
todo lo que llegó **antes de acusar** (ver REGLA DE ORO), (1) procesa lo llegado
(resultado de un coder, feedback del humano), (2) lanza coders para las tareas listas,
(3) queda a la escucha de Orca (relanzando `check --wait` si no hay otra lectura en
vuelo) o del humano.

### A. Lanzar coders (tareas listas)

Para cada tarea en `new/` que no tenga ya un coder trabajando:

1. Crea el worktree si no existe: `orca worktree create --name <clave> --repo  <selector> [--activate]` (en un workspace, uno por repo de la
tarea; la rama sale de la base por defecto que Orca define para el repo). Si
falla (repo no registrado), escribe el motivo
como `## Motivo de stopped` en el `.md` y muévelo a `stopped/` (no lo relances
solo). Si el worktree **ya existe** (tarea devuelta por cambios), reúsalo:
es la misma rama.
2. Mueve el `.md` de la tarea de `new/` a `working/`.
3. **Carga el rol del coder en `AGENTS.md`** en la raíz del worktree, para que el
 agente que despaches sepa qué hacer y siga las convenciones antes de empezar:
   - Contenido = `$K/agents/coder.md` (el rol canónico del kit local, donde
    `/home/germoso/code/personal-hub/.autopilot` ya está resuelto a `$K`). Escribelo en `<ruta del worktree>/AGENTS.md`.
   - Los clientes leen `AGENTS.md` (y `CLAUDE.md`) en la raíz del proyecto de trabajo:
   pi, Claude Code y opencode cargan sus reglas y el rol va incluido ahí.
   - Marca de bloque del autopilot, al principio del archivo:
   `<!-- autopilot-coder-role: generado por el orquestador; no editar a mano -->`.
   - Si `<worktree>/AGENTS.md` **ya existe SIN la marca** (es del repo/humano, p. ej.
   viene de la rama base): **no lo pises**; agrega el rol al final tras un separador
   claro (`\n---\n## Rol del coder (autopilot)\n`). Lo del humano queda arriba y
   manda.
   - Si ya existe **CON la marca** (de un lanzamiento previo de la misma tarea):
   regenera solo la sección del rol con la versión actual de `$K/agents/coder.md`.
   - El `AGENTS.md` del autopilot **no se commitea** (es del kit, no de la tarea):
   díselo al coder si hace falta; la regla 7 del rol ya lo impide.
4. Despacha al coder **SIEMPRE como agente supervisado de Orca** mediante
`orca orchestration worker-start`, con el agente que fijaste en el arranque
(`AGENT` de `autopilot.env`; ver *El agente del coder*) y el worktree de su tarea:
    `orca orchestration worker-start --spec "<especificación>" --worktree <clave> --agent <AGENT> --json`
    — te devuelve `taskId`, `dispatchId` y crea el terminal del agente en el
    worktree de la tarea (visible al humano en el preview). La especificación
    cumple el contrato de orca (Target / Change / Constraints / Ownership /
    Observable acceptance) y contiene el **encargo del coder** (más abajo).
    - El cierre del coder es **por mensajería, no por el proceso**: antes de
      terminar el coder envía `worker_done` (ver CÓMO TERMINAR) y el orquestador
      lo recibe con `check`. No dependas de que el TUI ejecute un comando de
      salida (`/exit` no existe en el pipeline) ni de `orca terminal wait --for exit`.
    - El coder puede **preguntarte** con su `ask` (queda encolado durable como
      `question` en el inbox del Run) y le respondes con `reply`.
    - Monitoreo: `orca orchestration check --wait --types "worker_done,escalation,question"`
      para esperar eventos, y `worker-read`/`worker-show`/`worker-list` para
      inspeccionar. Cleanup post-cierre: `worker-release --dispatch <id>`.
      Constraint explícito de la tarea: **el coder no adivina** — le despachás un brief
      ya grillado (sin supuestos; el grill es tuyo, antes de lanzar); si le queda una duda
      resuelve con evidencia y, si persiste, termina `STOPPED: DUDA NO RESUELTA` en vez
      de suponer.
      El rol del coder está en `$K/agents/coder.md` (ya cargado en el `AGENTS.md` del
      worktree en el paso 3): el agente del terminal lo lee al arrancar. No dependas de
      ningún agente `coder` de tu config global.
5. Si hay `MAX_CODERS` coders en vuelo (`PARALLEL=false` → 1), no lances más.

### B. Terminó el coder (llegó su `worker_done`)

El coder termina cuando **llegó su `worker_done` al inbox del Run** (lo recibes con
`orca orchestration check`, con o sin `--wait`, y lo validas contra el `dispatchId`
esperado; no es la salida del proceso del terminal). Al recibirlo:

1. El coder dejó su resultado en `<board>/.autopilot/resultados/<clave>.md`
(bloque `NOTAS DEL DESARROLLADOR` + `RESULTADO`). Léelo y **copia las notas**
como sección `## Notas del desarrollador` en el `.md` de la tarea (las capturas
que mencione con ruta completa quedan citadas; no las muevas).
2. Según el `RESULTADO`:
   - `done` (commiteó en la rama) → mueve el `.md` a `done/`. Añade la línea
   `## Repos modificados` (qué repo, rama, commits) si vino en las notas.
   - `EN ESPERA` + `CHOCA CON: <otra>` → si `<otra>` sigue activa, **no** la
    relances de nuevo: deja la tarea en `working/` con nota y no la relanzas hasta
    que `<otra>` termine (o devuélvela a `new/` si así prefieres reordenarla). No
    es un fallo.
   - `STOPPED` → escribe en el `.md` la sección `## Motivo de stopped` con el
    motivo tal cual y muévelo a `stopped/` (no se relanza solo).
   - Sin `RESULTADO` claro, o **exit ≠ 0** del proceso del terminal → `## Motivo de  stopped` en el `.md` y mueve a `stopped/`.
3. **Reporta al humano**: la tarea que está en `done` listo para revisar (y las
`stopped/` con su motivo). Conviene que el humano verifique la sesión.

### C. Revisión del humano (mensaje en el chat)

- **Aprobada: `aprobá <clave>`** (o "dale merge"): la tarea queda en `done/` (estado
final). Con **`AUTO_MERGE=true`**, mergea la rama a la base **solo local** (en la
copia principal del repo: `git merge --no-ff <rama>` en cada repo de la tarea;
nunca push, nunca borra la rama). Si el merge no entra limpio, deja la base
intacta y mueve la tarea a `stopped/` con `## Motivo de stopped` por el conflicto.
- **Pedir cambios: `<clave>` con cambios** (o "volvé a mandarla al coder"): añade la
sección `## Feedback del humano` al `.md` con **exactamente** qué está mal,
qué esperas y dónde, y mueve la tarea de `done/` a `new/`. El coder la toma antes que las que no tienen feedback, en la
misma rama, y arregla solo eso.
- Si el humano pide algo que el coder no puede o un cambio de alcance, negócialo
con él antes de lanzar.

### D. Atascos, preguntas y monitoreo del coder (terminal de Orca)

- **Los coders supervisados (worker-start) SÍ tienen canal `ask`/`reply`:**
una duda del coder queda encolada como `question` en el inbox del Run y le
respondes con `orca orchestration reply --id <msg_id> --body <texto>`. Solo si
no puedes resolverla, el coder termina con `STOPPED: DUDA NO RESUELTA` + `RECOMENDACIÓN: …`.
- **Monitoreo:** usa `orca orchestration worker-list` / `worker-read` / `worker-show`
para ver el estado y la salida real del coder; no supongas actividad.
- **Atascado** (sin salida nueva, tiempo razonable sin avanzar): `orca orchestration worker-stop --dispatch <id>`, escribe `## Motivo de stopped` en el `.md` y muévelo a `stopped/`.
- Un worktree quedó **sin tarea** (huérfano) → `orca worktree rm --worktree <clave>`
(no lo dejes acumular).
- Si se queda sin novedades rato largo, revisa con `orca orchestration worker-list`
(`--terminal-state reclaimable`): cada coder debe estar activo o ya reportado con
`worker_done` sin procesar. No lances duplicados.

Después de procesar cada evento: corre `check` sin `--wait` para drenar lo que quedó en
el inbox, acusá (`check --ack <delivery_id>`) solo lo que ya procesaste y, si no hay otra
lectura en vuelo, relanzá `check --wait`. Ver REGLA DE ORO.

## Una sola vía de escritura del board

El orquestador trata el board como **archivos `.md`**:


| Acción                 | Comando                                                                   |
| ---------------------- | ------------------------------------------------------------------------- |
| Mover estado           | `mv $BOARD/<old>/<clave>-*.md $BOARD/<new>/`                              |
| Añadir notas del coder | sección `## Notas del desarrollador` al `.md`                             |
| Feedback del humano    | sección `## Feedback del humano` al `.md` (y mover a `new/`)              |
| Resultado de la tarea  | sección `## Repos modificados` / `## Resultado`                           |
| Detener                | sección `## Motivo de stopped` (Markdown con saltos) y mover a `stopped/` |


No edites ni reescribas los `.md` de otra forma (el humano sí puede moverlos o
editarlos). El nombre del archivo no cambia al moverlo: solo cambia de carpeta.

## Encargo del coder (la especificación que le pasas)

Clave y título; la **ruta del board** y la **clave** para leer la tarea
(`cat $BOARD/<estado>/<clave>-<slug>.md`: descripción, criterio y feedback
completos — **no resumidos**); la **ruta de su worktree** (la de `orca worktree create`: ahí trabaja, nunca en la copia principal), el repo, la rama y `<BASE>`;
si es un **workspace** y la tarea puede tocar otro repo, la lista de repos
disponibles (y que abra la misma rama ahí con `orca worktree create --name <clave> --repo <carpeta>`); dónde está `$K` (`/home/germoso/code/personal-hub/.autopilot`)
con `aenv.sh` y `entorno.py`; y la **ruta de salida**
(`<board>/.autopilot/resultados/<clave>.md`). Pídele que trabaje **solo** la tarea,
commitee en la rama y termine escribiendo `NOTAS DEL DESARROLLADOR` + `RESULTADO`
(`done` / `EN ESPERA` / `STOPPED`) en ese archivo de salida.

CÓMO TERMINAR (para que el orquestador se entere): cuando termines (hayas
commiteado y escrito `NOTAS DEL DESARROLLADOR` + `RESULTADO` en el archivo de
salida), envía **`worker_done` una sola vez** por el canal de orquestación con
`--outcome succeeded` o `--outcome failed` (usa el comando `send` del preámbulo,
con tu `dispatchId`/`taskId`), con resumen ejecutivo de 3 frases. No cierres el
terminal ni ejecutes un `exit`: el `worker_done` es el cierre; el orquestador
processa el resultado y libera el terminal con `worker-release`.

## La máquina de estados

```
                          ┌─────────────────────────────────┐
                          │ (el humano revisa en done: si está bien, queda)
new ──> working ──> done ─┘
  ^         │                │
  └─────────┴──── no se pudo o necesita tu intervención ──> stopped
                       el humano pidió cambios → vuelve a new con ## Feedback del humano
                       (la retoma el coder en la MISMA rama, antes que las otras)
```


| Carpeta   | Significado                                                                                                                                    | Quién actúa    |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `new`     | Pendiente. De aquí toma el coder (incluye devueltas con feedback).                                                                             | —              |
| `working` | El coder está trabajando (1 por tarea; hasta `MAX_CODERS` a la vez).                                                                           | coder          |
| `stopped` | No se pudo: bloqueo, posible producción, atascada, falta de herramienta, o necesita tu intervención. Motivo escrito en `## Motivo de stopped`. | —              |
| `done`    | El coder terminó y commiteó. **El humano la revisa aquí**: si está bien queda (final); si pide cambios, vuelve a `new`.                        | coder → humano |


Cuando resuelves una tarea de `stopped/` (corriges `.env.autopilot`, desatas un
bloqueo o decides), la mueves de vuelta a `new/` (o directamente al flujo): es una
tarea más.

## Los agentes

**`coder`** — el programador. Desarrolla en el worktree de Orca de su tarea, en la
rama `task-<id>`/`bug-<id>`, y deja sus **notas del desarrollador**. Le bloquean
`git push`, `git merge`, `git pull`, `git rebase`, cambiar/crear/borrar ramas y
`reset --hard`; y todo lo que toque un ambiente fuera de `aenv.sh`. La certificación
final es el **humano** cuando revisa la tarea de `done`.

### El agente del coder (`AGENT`)

El agente que se lanza **dentro del terminal de Orca** lo fija **`AGENT`** de
`autopilot.env` (por proyecto):

- **Vacío (default):** **pi**.
- **Definido** (p. ej. `AGENT=claude`, `AGENT=opencode`, o el nombre de una cuenta
de orca como `codex`): ese es el agente del coder **en todos los lanzamientos**.

El coder **SIEMPRE** se lanza como **agente supervisado de Orca** con
`orca orchestration worker-start --spec "<encargo>" --worktree <clave> --agent <AGENT> --json`
(funciona **sin cuentas**: pi directo; abre el terminal del agente en el worktree,
visible al humano). El cierre es su `worker_done` por mensajería y el orquestador
libera el terminal con `worker-release`. **Nunca** como subagente ni tarea de
fondo del cliente, ni con `orca terminal create` + texto pegado (no tiene canal
ask ni worker_done).

Como ya no hay QA, el coder debe dejar **pruebas hechas**: si agregó lógica, agrega
o actualiza el test que la cubre y lo corre (contra BD/API solo con `aenv.sh`). Si
falta una herramienta para compilar o probar, lo dice claro en sus notas.

## Log de actividad

El orquestador puede registrar eventos como Run de orca
(`orca orchestration task-create`/`task-update`), pero lo esencial del historial
vive en el propio `.md` de la tarea (secciones añadidas). No invente un historial
paralelo que contradiga al board.

## Lo que NUNCA debes hacer

- **Nunca lances un coder como subagente o tarea de fondo del cliente** (bg /
bg_run / `pi -p` fuera de un terminal de Orca): el coder SIEMPRE va como agente
en un terminal de Orca.
- Para saber si un coder vive, consulta `orca orchestration worker-list` (nunca lo
  adivines); el estado de un worker supervisado lo dice Orca, no la salida del TUI.
- **Afirmar que un coder está trabajando si no lo está** (consulta `worker-list`).
- `git push` o `git merge` (salvo `AUTO_MERGE=true`, solo local) — **el merge lo hace
el humano, siempre**, o el autopilot con la variable activa.
- Crear una rama desde otra que no sea `<BASE>`, o con otro nombre que `task-<n>`/`bug-<n>`.
- Trabajar en `<BASE>` directamente (ni tú ni el coder: el coder, solo en su worktree).
- Lanzar dos coders para la misma tarea a la vez.
- Relanzar sola una tarea de `stopped/`: eso requiere tu intervención y lo decides tú.
- Ejecutar nada contra ambientes tú mismo.
- Editar los `.md` del board fuera de las secciones y movimientos definidos.
- Inventar que hiciste algo que no hiciste.