---
name: autopilot
description: Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown (.workitems/), ejecutado por Orca: el orquestador crea un worktree por tarea con `orca worktree create`, lanza al coder con `orca orchestration` (worker-start / check) y el humano revisa (done -> reviewed, o pide cambios -> bug-fix). Sin QA ni E2E. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.
---

# Sistema Autónomo de Desarrollo (Autopilot)

El autopilot trabaja las tareas de un **board de workitems** (carpetas + `.md`) y
tú, el agente principal (**orquestador**), diriges la ejecución con **Orca**: un
**coder** por tarea, cada uno en su propio `git worktree` (rama `task-<id>` /
`bug-<id>`), sin push ni merge. El humano es el revisor final: las tareas
terminadas pasan a `done` y él las mueve a `reviewed` o pide cambios (bug-fix).

```
 tarea (new) ──> CODER ──────────────> done ──(humano)──> reviewed
                 la programa en        tú revisas        (o pedís cambios ──> bug-fix)
                 su rama y commitea     y mergeas
```

- **Un coder por tarea** (`new` o `bug-fix`). No hay QA ni E2E: la certificación la
  hace el humano cuando revisa la tarea de `done`.
- Cada tarea tiene **su propia rama** desde la rama base del proyecto
  (`BASE_BRANCH` o `REPO.<carpeta>=<rama>`). **Nunca hace push**: el merge lo haces
  tú a mano, o el kit con `AUTO_MERGE=true` (solo local, sin push).
- **Nunca toca producción**: el coder solo se conecta a BD/API con `aenv.sh`, que
  valida el `.env.autopilot` que tú creaste.
- Orca gestiona los **worktrees**, los **terminales** y la **orquestación**
  (lanzar, vigilar y recibir a los coders). El board (estados y notas) son solo
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

## El board

```
.workitems/                         # WORKITEMS_DIR; NO esta en git
├── new/          bug-140123-login-falla-con-google.md   # tarea = archivo .md en la carpeta de su estado
├── in-progress/  task-pagos_modelo.md
├── bug-fix/
├── stopped/
├── done/
├── reviewed/                       # las mueves tú cuando revisas una de done
├── adjuntos/<clave>/               # capturas, imagenes y videos (archivos)
├── planes/<slug>.md                # planes de /autopilot-plan
└── .autopilot/resultados/<clave>.md # (scratch) notas que escribe el coder al terminar
```

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

1. **El orquestador está SIEMPRE a la espera**: o esperando a un coder
   (`orca orchestration check --wait …`) o pidiendo la revisión al humano.
2. **No cierres el turno** sin dejar al menos un `check --wait` corriendo o sin
   decirle al usuario que el autopilot quedó a la espera de él.
3. **No inventes que hay un coder trabajando si no lo hay.** Orca dice la verdad
   (`worker-list`, `worker-show`); si un worktree quedó sin efecto, velo.
4. Los **aviso de un worker que terminó** (worker_done de orca o el aviso nativo
   del cliente) son el evento B: procésalo **una sola vez**.

## NUNCA CONTRA PRODUCCIÓN (por encima de todo)

- Nadie (tú ni el coder) ejecuta nada contra producción.
- Lo que se conecta a una base de datos o API (tests de integración, levantar un
  backend, migraciones, seeds, scripts, HTTP) corre **solo** con
  `$K/aenv.sh <repo o worktree> -- <comando>` (`$K` = `~/.local/share/autopilot-kit`,
  donde instaló el kit `aenv.sh` y `entorno.py`). Valida el **`.env.autopilot`** que
  el humano creó y, si no es `ok`, **NO ejecuta** (salida 3) y dice qué hacer.
- Sin `aenv.sh` solo se corren cosas que **no se conectan a nada**: compilar,
  analizar, lint, instalar dependencias, tests de unit/widget sin red.
- Nadie crea, edita ni copia `.env*`. Nadie cambia a mano la URL de API de una app
  para probar.
- El orquestador tampoco ejecuta contra ambientes: si tiene que probar algo, se lo
  delega al coder (que lo corre con `aenv.sh`).
- Un coder que se detiene por **posible producción** termina con
  `RESULTADO: STOPPED` + `MOTIVO: POSIBLE PRODUCCIÓN: …` + `RECOMENDACIÓN: …`:
  muévelo a `stopped/` tal cual. No lo reintentes: lo resuelve el humano (creando o
  corrigiendo `.env.autopilot`).
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

Para cada tarea en `new/` o `bug-fix/` que no tenga ya un coder trabajando:

1. Decide la rama base (<BASE>) de su repo (`REPO.<carpeta>` o `BASE_BRANCH`).
2. Crea el worktree si no existe: `orca worktree create --name <clave> --repo
   <selector> --base-branch <BASE> [--activate]` (en un workspace, uno por repo de la
   tarea). Si falla (rama base inexistente, repo no registrado), mueve la tarea a
   `stopped/` con el motivo.
3. Mueve el `.md` de la tarea de `new/` o `bug-fix/` a `in-progress/`.
4. Despacha al coder: `orca orchestration worker-start --spec "<especificación>"
   --worktree <clave> --agent <agente-disponible> --json` (o, si no hay agente de
   orca, lanza el subagente `coder` del cliente en ese worktree). La especificación
   cumple el contrato de orca (Target / Change / Constraints / Ownership /
   Observable acceptance) y contiene el **encargo del coder** (más abajo).
5. Si hay `MAX_CODERS` coders en vuelo (`PARALLEL=false` → 1), no lances más.

### B. Terminó el coder (worker_done de orca, o aviso de subagente)

1. El coder dejó su resultado en `<board>/.autopilot/resultados/<clave>.md`
   (bloque `NOTAS DEL DESARROLLADOR` + `RESULTADO`). Léelo y **copia las notas**
   como sección `## Notas del desarrollador` en el `.md` de la tarea (las capturas
   que mencione con ruta completa quedan citadas; no las muevas).
2. Según el `RESULTADO`:
   - `done` (commiteó en la rama) → mueve el `.md` a `done/`. Añade la línea
     `## Repos modificados` (qué repo, rama, commits) si vino en las notas.
   - `EN ESPERA` + `CHOCA CON: <otra>` → si `<otra>` sigue activa, **no** lo muevas
     a `in-progress` de nuevo: deja la tarea en `in-progress/` con nota y no la
     re-lances hasta que `<otra>` termine (o mévela de vuelta a `new/` si así
     prefieres reordenarla). No es un fallo.
   - `STOPPED` → mueve el `.md` a `stopped/` con el motivo tal cual.
   - Sin `RESULTADO` claro o worker con `outcome: failed` → `stopped/` con ese
     motivo.
3. **Reporta al humano**: la tarea que está en `done` listo para revisar (y en
   `stopped` con su motivo). Conviene que el humano verifique la sesión.

### C. Revisión del humano (mensaje en el chat)

- **`reviewed <clave>`** (o "aprobá la N", "dale merge"): mueve el `.md` de `done/`
  a `reviewed/`. Con **`AUTO_MERGE=true`**, antes de moverla, mergea la rama a la
  base **solo local** (en la copia principal del repo: `git merge --no-ff <rama>` en
  cada repo de la tarea; nunca push, nunca borra la rama). Si el merge no entra
  limpio, deja la base intacta y la tarea en `stopped/` con el motivo del conflicto.
- **Pedir cambios: `<clave>` con cambios** (o "volvé a mandarla al coder"): añade la
  sección `## Feedback del humano` al `.md` con **exactamente** qué está mal,
  qué esperas y dónde, y mueve la tarea de `done/` (o `reviewed/`/`stopped/`) a
  `bug-fix/`. El coder la toma primero que las `new/`, en la misma rama, y arregla
  solo eso.
- Si el humano pide algo que el coder no puede o un cambio de alcance, negócialo
  con él antes de lanzar.

### D. Atascos y escalaciones de Orca

- Orca reporta en `check` `escalation`/`question` (un coder preguntando o
  atascado): respóndele con `orca orchestration reply --id <message_id> --body "…"`
  (al coder solo por chat de orca) o toma una decisión. Si no responde, termina la
  tarea: `worker-stop`/`worker-abandon` según corresponda y `stopped/` con el motivo.
- Un worktree quedó **sin tarea** (huérfano) → `orca worktree rm --worktree <clave>`
  (no lo dejes acumular).
- Revisa actividad real con `orca orchestration worker-list --run <run_id> --json`
  si `check` se queda sin novedades rato largo: cada worker debe estar vivo o con
  `worker_done` pendiente de procesar. No lances duplicados.

Después de cada evento, si no hay un `check --wait` corriendo, relánzalo.

## Una sola vía de escritura del board

El orquestador trata el board como **archivos `.md`**:

| Acción | Comando |
|---|---|
| Mover estado | `mv .workitems/<old>/<clave>-*.md .workitems/<new>/` |
| Añadir notas del coder | sección `## Notas del desarrollador` al `.md` |
| Feedback del humano | sección `## Feedback del humano` al `.md` (y mover a `bug-fix/`) |
| Resultado de la tarea | sección `## Repos modificados` / `## Resultado` |
| Detener | sección `## Motivo de stopped` (Markdown con saltos) y mover a `stopped/` |

No edites ni reescribas los `.md` de otra forma (el humano sí puede moverlos o
editarlos). El nombre del archivo no cambia al moverlo: solo cambia de carpeta.

## Encargo del coder (la especificación que le pasas)

Clave y título; la **ruta del board** y la **clave** para leer la tarea
(`cat .workitems/<estado>/<clave>-<slug>.md`: descripción, criterio y feedback
completos — **no resumidos**); la **ruta de su worktree** (la de `orca worktree
create`: ahí trabaja, nunca en la copia principal), el repo, la rama y `<BASE>`;
si es un **workspace** y la tarea puede tocar otro repo, la lista de repos
disponibles (y que abra la misma rama ahí con `orca worktree create --name <clave>
--repo <carpeta> --base-branch <base>`); dónde está `$K` (`~/.local/share/autopilot-kit`)
con `aenv.sh` y `entorno.py`; y la **ruta de salida**
(`<board>/.autopilot/resultados/<clave>.md`). Pídele que trabaje **solo** la tarea,
commitee en la rama y termine escribiendo `NOTAS DEL DESARROLLADOR` + `RESULTADO`
(`done` / `EN ESPERA` / `STOPPED`) en ese archivo de salida.

## La máquina de estados

```
new ──> in-progress ──> done ──(humano: reviewed / pide cambios)──> reviewed
            ↑              │  │
            │              │  └── (AUTO_MERGE=true: mergea la rama solo local y deja reviewed)
            └── bug-fix <──┘  (el humano pidió cambios → el coder corrige en la misma rama)
stopped  <- humano | coder (posible producción, bloqueo, atascado)
```

| Carpeta | Significado | Quién actúa |
|---|---|---|
| `new` | Pendiente | — |
| `in-progress` | El coder está trabajando (1 por tarea; hasta `MAX_CODERS` a la vez). | coder |
| `bug-fix` | El humano pidió cambios. **Se toma antes que `new`.** | coder |
| `stopped` | No se pudo. Requiere humano, con motivo escrito. | — |
| `done` | El coder terminó y commiteó. **Pendiente de tu revisión.** | — |
| `reviewed` | Ya la revisaste (y mergeaste). Solo la mueve el humano (o el kit, con `AUTO_MERGE=true`, al mergear). | humano |

Cuando la resuelvas, vuelve a `new/` (o directamente al flujo): es una tarea más.

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

- **Cerrar el turno sin dejar al autopilot a la escucha** (un `check --wait` o a la
  espera del humano) sin decírselo.
- **Afirmar que un coder está trabajando si no lo está** (consulta `worker-list`).
- `git push` o `git merge` (salvo `AUTO_MERGE=true`, solo local) — **el merge lo hace
  el humano, siempre**, o el kit con la variable activa.
- Crear una rama desde otra que no sea `<BASE>`, o con otro nombre que `task-<n>`/`bug-<n>`.
- Trabajar en `<BASE>` directamente (ni tú ni el coder: el coder, solo en su worktree).
- Lanzar dos coders para la misma tarea a la vez.
- Mover una tarea a `reviewed` por tu cuenta: eso lo hace el humano (salvo
  `AUTO_MERGE=true`).
- Ejecutar nada contra ambientes tú mismo.
- Editar los `.md` del board fuera de las secciones y movimientos definidos.
- Inventar que hiciste algo que no hiciste.