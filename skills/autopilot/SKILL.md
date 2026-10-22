---
name: autopilot
description: Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown (.workitems/), ejecutado por Orca: el orquestador crea un worktree por tarea con `orca worktree create`, lanza al coder con `orca orchestration` (worker-start / check) y el humano revisa en done (si pide cambios vuelve a new; lo que no se pudo va a stopped). Board de 4 estados: new / working / done / stopped. Sin QA ni E2E. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.
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
- Cada tarea tiene **su propia rama** desde la rama base del proyecto
(`BASE_BRANCH` o `REPO.<carpeta>=<rama>`). **Nunca hace push**: el merge lo haces
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

En un **workspace** registra cada repo del proyecto. La rama base de cada repo
viene de `autopilot.env` (ver más abajo). Para lanzar al coder con la orquestación
de Orca hace falta un agente disponible:

```sh
orca account list                 # cuentas de agente (codex, claude...)
```

Si `orca account list` no muestra ninguna cuenta, corre `orca account add` una vez
(o dile al usuario que añada una). El orquestador despacha con el agente de
`orca account list`; si no hubiera ninguno, usa el **subagente `coder`** del propio
cliente (Claude Code / OpenCode / pi) dentro del worktree que creó Orca.

**Usa la skill de orca (`orchestration`).** Orca carga esa skill para el orquestador
(patrón *worker supervised*): es el contrato de `orca orchestration`
(`run-create` → `worker-start` → `check --wait` → `reply` → `worker-release` /
`worker-stop`). Cárgala en tu cliente si la expone (pi: `/skill:orchestration`) y,
sobre todo, **no inventes un protocolo propio**: seguí el ciclo y los comandos que
define esa skill. Este documento trabaja sobre ese mismo contrato; ante cualquier
duda entre este texto y la skill de orca, manda la skill de orca.

## El board

```
.workitems/                         # WORKITEMS_DIR; NO esta en git
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
- Donde antes había `bug-fix`/`reviewed`, ahora: las **devueltas por el humano** vuelven
a `new/` con `## Feedback del humano` (el coder las retoma); lo que **no se pudo** (bug,
 atascada, posible producción, falta de herramienta) va a `stopped/` con `## Motivo de
 stopped`, y **no se relanza solo**: requiere tu intervención.

- **El archivo `.md` ES la tarea** (no hay base de datos). El estado es la carpeta
donde está. El orquestador **no edita los `.md` a mano** más que para añadir las
secciones del coder y del humano (y los mueve de carpeta al cambiar de estado).
- **Nombre del archivo = `<tipo>-<id>-<slug>.md`.** `<tipo>-<id>` es la **clave**
de la tarea y el **nombre de su rama** (`task-login_social`, `bug-140123`).
El `<id>` lo da quien crea la tarea: número (`140123`) o texto (`login_social`:
minúsculas, dígitos y `_`, sin `-`).
- **Cómo llegan las tareas es externo al autopilot**: se crea un `.md` en `new/`
(a mano, con `/autopilot-plan`, o desde una integración como Azure DevOps).
El autopilot solo trabaja lo que hay en el board.
- El board **no va en git** (`.workitems/` está en `.gitignore`): si estuviera
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
 si no están en `orca repo list`); comprueba el agente disponible
 (`orca account list`).
3. Abre un **Run de orquestación** (una vez por sesión):
 `orca orchestration run-create --objective "<breve resumen del trabajo de esta sesión>" --json`
 — te devuelve el `run_id` (lo usan los comandos de orquestación).
4. Sigue **El bucle**.

El **coder siempre trabaja dentro del worktree de Orca** de su tarea (la ruta que
devuelve `orca worktree create`). Nunca en la copia principal del repo.

## REGLA DE ORO: el bucle nunca queda sin escuchar

1. **No inventes que hay un coder trabajando si no lo hay.** Orca dice la verdad
 (`worker-list`, `worker-show`); si un worktree quedó sin efecto, velo.

## NUNCA CONTRA PRODUCCIÓN (por encima de todo)

- Nadie (tú ni el coder) ejecuta nada contra producción.
- Lo que se conecta a una base de datos o API (tests de integración, levantar un
backend, migraciones, seeds, scripts, HTTP) corre **solo** con
`$K/aenv.sh <repo o worktree> -- <comando>` (`$K` = `«K_DIR»`,
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

## REGLAS DE GIT (sin excepciones)

- **Una rama independiente por workitem.** Nombre: `task-<id>` o `bug-<id>`.
- **Toda rama sale de la rama base de SU repo** (`BASE_BRANCH` o `REPO.<carpeta>=<rama>`),
nunca de otra. El worktree y su rama se crean con **`orca worktree create`**:
  - repo:   `orca worktree create --name <clave> --repo <selector> --base-branch <BASE> [--activate]`
  - workspace: una por repo de la tarea con `--repo <carpeta>`.
  Devuelve la ruta del worktree (ahí trabaja el coder).
- **NUNCA `git push`. NUNCA `git merge`** (salvo el humano, o `AUTO_MERGE=true`, que
mergea **solo local**). Tampoco `git rebase`, borrar ramas ni `reset --hard`.
- El tipo de la rama (`task`/`bug`) es el tipo del workitem, no el estado:
un `bug-140123` rechazado por el humano se sigue corrigiendo en `bug-140123`.

## El bucle

Cada vuelta del orquestador: (1) procesa lo que llegó (resultado de un coder,
feedback del humano), (2) lanza coders para las tareas listas, (3) queda a la
escucha de Orca o del humano. Relanza siempre.

### A. Lanzar coders (tareas listas)

Para cada tarea en `new/` que no tenga ya un coder trabajando:

1. Decide la rama base (<BASE>) de su repo (`REPO.<carpeta>` o `BASE_BRANCH`).
2. Crea el worktree si no existe: `orca worktree create --name <clave> --repo  <selector> --base-branch <BASE> [--activate]` (en un workspace, uno por repo de la
 tarea). Si falla (rama base inexistente, repo no registrado), escribe el motivo
 como `## Motivo de stopped` en el `.md` y muévelo a `stopped/` (no lo relances
 solo). Si el worktree **ya existe** (tarea devuelta por cambios), reúsalo:
 es la misma rama.
3. Mueve el `.md` de la tarea de `new/` a `working/`.
4. Despacha al coder: `orca orchestration worker-start --spec "<especificación>"  --worktree <clave> --agent <agente-disponible> --json` (o, si no hay agente de
 orca, lanza el subagente `coder` del cliente en ese worktree). La especificación
 cumple el contrato de orca (Target / Change / Constraints / Ownership /
 Observable acceptance) y contiene el **encargo del coder** (más abajo).
 El `coder` de ESTE proyecto es local: su definición está en `$K/agents/coder.md`
 (y, según cliente, en `.opencode/agent/coder.md` o `.claude/agents/coder.md` de
 esta misma carpeta). No dependas de ningún agente `coder` de tu config global:
 si tu cliente registra el agente local por nombre, úsalo; si no, pasa el
 contenido de `$K/agents/coder.md` como instrucciones del subagente (pi).
5. Si hay `MAX_CODERS` coders en vuelo (`PARALLEL=false` → 1), no lances más.

### B. Terminó el coder (worker_done de orca, o aviso de subagente)

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
   - Sin `RESULTADO` claro o worker con `outcome: failed` → `## Motivo de
   stopped` en el `.md` y mueve a `stopped/`.
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

### D. Atascos y escalaciones de Orca

- Orca reporta en `check` `escalation`/`question` (un coder preguntando o
atascado): respóndele con `orca orchestration reply --id <message_id> --body "…"`
(al coder solo por chat de orca) o toma una decisión. Si no responde, termina la
tarea: `worker-stop`/`worker-abandon` según corresponda, escribe `## Motivo de
stopped` en el `.md` y muévelo a `stopped/`.
- Un worktree quedó **sin tarea** (huérfano) → `orca worktree rm --worktree <clave>`
(no lo dejes acumular).
- Revisa actividad real con `orca orchestration worker-list --run <run_id> --json`
si `check` se queda sin novedades rato largo: cada worker debe estar vivo o con
`worker_done` pendiente de procesar. No lances duplicados.

Después de cada evento, si no hay un `check --wait` corriendo, relánzalo.

## Una sola vía de escritura del board

El orquestador trata el board como **archivos `.md`**:


| Acción                 | Comando                                                                   |
| ---------------------- | ------------------------------------------------------------------------- |
| Mover estado           | `mv .workitems/<old>/<clave>-*.md .workitems/<new>/`                      |
| Añadir notas del coder | sección `## Notas del desarrollador` al `.md`                             |
| Feedback del humano    | sección `## Feedback del humano` al `.md` (y mover a `new/`)               |
| Resultado de la tarea  | sección `## Repos modificados` / `## Resultado`                           |
| Detener                | sección `## Motivo de stopped` (Markdown con saltos) y mover a `stopped/` |


No edites ni reescribas los `.md` de otra forma (el humano sí puede moverlos o
editarlos). El nombre del archivo no cambia al moverlo: solo cambia de carpeta.

## Encargo del coder (la especificación que le pasas)

Clave y título; la **ruta del board** y la **clave** para leer la tarea
(`cat .workitems/<estado>/<clave>-<slug>.md`: descripción, criterio y feedback
completos — **no resumidos**); la **ruta de su worktree** (la de `orca worktree create`: ahí trabaja, nunca en la copia principal), el repo, la rama y `<BASE>`;
si es un **workspace** y la tarea puede tocar otro repo, la lista de repos
disponibles (y que abra la misma rama ahí con `orca worktree create --name <clave> --repo <carpeta> --base-branch <base>`); dónde está `$K` (`«K_DIR»`)
con `aenv.sh` y `entorno.py`; y la **ruta de salida**
(`<board>/.autopilot/resultados/<clave>.md`). Pídele que trabaje **solo** la tarea,
commitee en la rama y termine escribiendo `NOTAS DEL DESARROLLADOR` + `RESULTADO`
(`done` / `EN ESPERA` / `STOPPED`) en ese archivo de salida.

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


| Carpeta   | Significado                                                                 | Quién actúa |
| ---------| --------------------------------------------------------------------------- | ----------- |
| `new`    | Pendiente. De aquí toma el coder (incluye devueltas con feedback).          | —           |
| `working`| El coder está trabajando (1 por tarea; hasta `MAX_CODERS` a la vez).        | coder       |
| `stopped`| No se pudo: bloqueo, posible producción, atascada, falta de herramienta, o necesita tu intervención. Motivo escrito en `## Motivo de stopped`. | —           |
| `done`   | El coder terminó y commiteó. **El humano la revisa aquí**: si está bien queda (final); si pide cambios, vuelve a `new`. | coder → humano |


Cuando resuelves una tarea de `stopped/` (corriges `.env.autopilot`, desatas un
bloqueo o decides), la mueves de vuelta a `new/` (o directamente al flujo): es una
tarea más.

## Los agentes

**`coder`** — el programador. Desarrolla en el worktree de Orca de su tarea, en la
rama `task-<id>`/`bug-<id>`, y deja sus **notas del desarrollador**. Le bloquean
`git push`, `git merge`, `git pull`, `git rebase`, cambiar/crear/borrar ramas y
`reset --hard`; y todo lo que toque un ambiente fuera de `aenv.sh`. La certificación
final es el **humano** cuando revisa la tarea de `done`.

Como ya no hay QA, el coder debe dejar **pruebas hechas**: si agregó lógica, agrega
o actualiza el test que la cubre y lo corre (contra BD/API solo con `aenv.sh`). Si
falta una herramienta para compilar o probar, lo dice claro en sus notas.

## Log de actividad

El orquestador puede registrar eventos como Run de orca
(`orca orchestration task-create`/`task-update`), pero lo esencial del historial
vive en el propio `.md` de la tarea (secciones añadidas). No invente un historial
paralelo que contradiga al board.

## Lo que NUNCA debes hacer

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