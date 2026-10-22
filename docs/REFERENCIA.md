# Referencia del Autopilot

Sistema autónomo de desarrollo para agentes de IA **con un humano al volante**. Orca
crea un `git worktree` por tarea y lanza un **coder** por tarea; cuando el coder
termina, la tarea queda **`done` a la espera de tu revisión** (no hay QA ni E2E: el
humano es el revisor final). Documento de referencia: estados, ramas, variables,
el bucle del orquestador y la estructura del kit.

Índice:

- [Cómo funciona](#cómo-funciona)
- [El board](#el-board)
- [Ramas](#ramas)
- [Reglas de trabajo](#reglas-de-trabajo)
- [Instalación](#instalación)
- [Configurar un proyecto](#configurar-un-proyecto)
- [autopilot.env](#autopilotenv)
- [El bucle del orquestador](#el-bucle-del-orquestador)
- [Nunca contra producción](#nunca-contra-producción)
- [Trabajo en paralelo y colisiones](#trabajo-en-paralelo-y-colisiones)
- [Qué queda escrito en cada tarea](#qué-queda-escrito-en-cada-tarea)
- [La revisión del humano](#la-revisión-del-humano)
- [Orca](#orca)
- [Qué incluye el kit](#qué-incluye-el-kit)
- [Seguridad](#seguridad)

## Cómo funciona

```
 new ──> working ──(el coder termina)──> done
   ^         │                            │
   └─────────┴── el humano pidió cambios: vuelve a new con ## Feedback del humano
       (lo que no se pudo o necesita tu intervención) ──> stopped (con ## Motivo de stopped)
```

El **orquestador** (el agente principal que corre `/autopilot`) hace tres cosas en un
bucle:

1. procesa lo que llegó (resultado de un coder, revisión del humano);
2. lanza coders para las tareas listas (`new/`);
3. queda a la espera de Orca (`truth orchestration check --wait`) o del humano.

Toda la ejecución (worktrees, procesos, agentes) la maneja **Orca**; todo el estado
(qué tarea está en qué estado, qué hizo el coder, qué pidió el humano) vive en el
**board** de `.workitems/`. Orca no sabe de estados: el orquestador es el pegamento.

### Los agentes

- **coder**: un programador por tarea. Trabaja en el worktree de Orca de su rama
  (`task-<id>` / `bug-<id>`), commitea, corre sus pruebas y deja sus notas en el archivo de
  resultado `<board>/.autopilot/resultados/<clave>.md`, que el orquestador copia a la tarea.
- **el humano**: revisa `done`, mergea su rama, o escribe su feedback y la tarea vuelve a
  `new/`.

## El board

```
$BOARD/                             # BOARD = WORKITEMS_DIR (default .workitems/); NO está en git
├── new/          bug-140123-login-falla-con-google.md
├── working/      task-pagos_modelo.md
├── done/         task-favoritar-tarjeta.md
├── stopped/      task-pagos_modelo.md                  # no se pudo / necesita tu intervención
├── adjuntos/<clave>/               # capturas, imagenes y videos (archivos)
├── planes/<slug>.md                # planes de /autopilot-plan
└── .autopilot/resultados/<clave>.md # (scratch) notas que escribe el coder al terminar
```

Solo hay 4 carpetas de estado (`new/`, `working/`, `done/`, `stopped/`); `adjuntos/`,
`planes/` y `.autopilot/resultados/` son de apoyo. Las devueltas por el humano vuelven a
`new/` con `## Feedback del humano`; lo que no se pudo va a `stopped/` con `## Motivo de
stopped` (sin relanzar solo), a la espera de tu intervención.

- **El archivo `.md` ES la tarea** (no hay base de datos). El estado es la carpeta
  donde está. El orquestador **no reescribe los `.md`** más que para añadir secciones
  (notas del coder, feedback del humano) y moverlos de carpeta.
- **Nombre = `<tipo>-<id>-<slug>.md`.** `<tipo>-<id>` es la **clave** y el **nombre de
  la rama** (`task-login_social`, `bug-140123`). `<tipo>` es `task` o `bug`; el `id`
  lo pone quien crea la tarea (número o texto `[a-z0-9_]` sin `-`). El slug ayuda a
  identificar sin leer; **no** se usa como identificador.
- **Regla de oro:** cada clave existe una sola vez en el board. Si una clave ya está en
  `new`, `working`, `done`, etc., no se crea otra con ese `id` (se corrige la existente).
- El board **no va en git** (`.workitems/` está en `.gitignore`): si estuviera
  versionado, al cambiar de rama cambiaría el tablero. Los estados, notas y adjuntos
  son locales a tu copia.

### El `.md` de una tarea

Las secciones van apareciendo a medida que la tarea avanza (el orquestador las añade):

```markdown
<!-- autopilot: tipo=bug id=140123 prioridad=High repo=Konectame_BackOffice
origen=plan:pagos depende= -->
# Login falla con Google

## Descripción
El contexto, qué hay que hacer y cómo probarlo (para el coder).

## Criterio de aceptación
1. ... (observable y verificable: el humano lo comprueba uno por uno)

## Notas del desarrollador
### Intento 1
- Repos modificados: ...
- Que se hizo: ...
- Como probarlo: ...
- Pruebas que corriste: ...

## Feedback del humano          <- solo si el humano pidió cambios
### Revisión 1
- El botón X hace Y cuando tendría que hacer Z.

## Repos modificados            <- cuando el coder termina (done)
## Motivo de stopped            <- cuando no se pudo
```

El orquestador NO toca: el nombre del archivo, la descripción, el criterio de
aceptación (salvo sumar el feedback del humano al criterio si el humano lo pide) ni
los adjuntos. Las capturas que el coder menciona se citan con ruta completa y quedan
visibles en la tarea sin copiarse.

## Ramas

- **Una rama independiente por workitem.** Nombre: `task-<id>` o `bug-<id>` (el tipo
  del workitem, no su estado: un `bug-140123` rechazado se sigue corrigiendo en
  `bug-140123`).
- **Toda rama sale de la rama base por defecto que Orca tiene definida para su repo**
  (aquí no se configura: `orca worktree create` sin `--base-branch` usa la del repo).
  La crea **Orca** (`orca worktree create`), no el orquestador a mano.
- **NUNCA `git push`.** El merge a la base lo hace **el humano**, o el autopilot con
  `AUTO_MERGE=true` (solo local, sin push; no borra la rama).
- **NUNCA `git merge`** por parte de los agentes, ni `rebase`, ni borrar ramas, ni
  `reset --hard`.
- Cuando la rama se mergea (o se descarta la tarea), el worktree se limpia con
  `orca worktree rm --worktree <clave>` (los huérfanos se acumulan si no).

## Reglas de trabajo

1. El coder trabaja **solo** en el worktree de Orca de su tarea, nunca en la copia
   principal del repo (es la del humano).
2. Una tarea puede tocar **varios repos** de un workspace: el coder abre la misma rama
   en cada uno con `orca worktree create --name <clave> --repo <carpeta> ...`, o el
   orquestador se la crea si el coder no puede.
3. En paralelo, dos workitems no tocan el mismo archivo: el que choca devuelve
   `EN ESPERA` + `CHOCA CON <clave>` y se retoma cuando el otro termina.
4. Todo lo que se conecta a una BD/API se ejecuta con el validador (`aenv.sh`); si no
   es `ok`, no se ejecuta y la tarea va a `stopped` con la recomendación.
5. Commits en español, claros, con la clave (`bug-37282: ...`), sin `Co-Authored-By`
   ni cabeceras de herramienta, y **solo** con lo de la tarea.

## Instalación

La instalación es **LOCAL, por proyecto** (no contamina tu setup global). Baja el
repo del kit una vez y úsalo para instalar en cada proyecto que quieras:

```sh
git clone https://github.com/Germoso/azure_devops_coding_autopilot.git ~/code/autopilot
cd ~/code/autopilot
./install.sh --local ~/code/konectame    # o: cd ~/code/konectame && bash ~/code/autopilot/install.sh
```

Instala **dentro de la carpeta del proyecto** (no escribe nada en `~/.config/opencode`,
`~/.claude`, `~/.pi/agent` ni `~/.local/share/`):

- `.autopilot/`: validadores `aenv.sh` y `entorno.py` (nunca contra producción),
  skills y el agente fuente `agents/coder.md` (con `K` = `<proyecto>/.autopilot`);
- enrutado por cliente en la misma carpeta: `.pi/skills/`, `.opencode/{skill,agent,
  command}/`, `.claude/{skills,agents}/`;
- en OpenCode, además, los **comandos** `/autopilot-init`, `/autopilot-plan`,
  `/autopilot` (en Claude Code y pi las skills ya son esos comandos).
- un bloque en `.gitignore` (nada del kit se commitea).

No pisa archivos que no generó el kit (marca `.autopilot-kit`). `entorno.py` se valida
al final con `python3 -m py_compile`. Otras carpetas quedan sin autopilot: solo
funciona donde se instaló.

### Desinstalar

- De un proyecto (solo esa carpeta): `./install.sh --uninstall --local <proyecto>`.
- Copia GLOBAL vieja (la de versiones anteriores del kit que sí iba a tu config de
  usuario): `./install.sh --uninstall`. Nunca toca los proyectos (`autopilot.env`,
  board, `.env*`, config de azure).

## Configurar un proyecto

Salvo *workspace*, en la **carpeta del proyecto** (la que abre el cliente):

1. **`/autopilot-init`** detecta repo o workspace y crea `autopilot.env` y el board
   `$BOARD/` (`WORKITEMS_DIR`, por defecto `.workitems/`; si tu `autopilot.env` dice
   `WORKITEMS_DIR=.board`, el board es `.board/`). La rama base NO se pide: la define Orca
   (cada worktree nace de la base por defecto del repo).
2. **`.env.autopilot`** en cada repo que use BD/API: copia de `.env` con todo apuntando
   a **local o QA** (base con "qa" en el nombre). Sin él, ese repo no ejecuta nada.
3. **Orca**: `orca repo add --path <ruta>` por repo (o de la carpeta de un workspace) y
   un agente disponible (`orca account list`).

### Workspace: varios repos, un board

- La carpeta abierta es la del proyecto; bajo ella hay repos (subcarpetas con `.git/`).
- `autopilot.env` se crea en la carpeta del proyecto; los repos se registran en Orca
  (`orca repo add`) y cada worktree nace de la rama base por defecto de su repo.
- El board `$BOARD/` (la carpeta `WORKITEMS_DIR`) vive en la carpeta del proyecto (una
  sola lista de tareas para todo el workspace).

### Una tarea en varios repos

El board es uno por proyecto, no por repo. Las tareas que tocan dos repos (p. ej.
backend + app) abren la **misma rama** (`<clave>`) en cada uno; deben nacer de la base
de **su** repo. La tarea anota repos modificados por repo.

## autopilot.env

Variables del kit. Sin contraseñas (las cuentas van en los `.env.autopilot`).

| Variable | Default | Qué hace |
|---|---|---|
| `WORKITEMS_DIR` | (vacío) | Carpeta del board: `.workitems/` junto a `autopilot.env`. |
| `PARALLEL` | `false` | `true` = hasta `MAX_CODERS` coders a la vez. |
| `MAX_CODERS` | `1` | Tope de coders en vuelo con `PARALLEL=true`. |
| `AUTO_MERGE` | `false` | Al aprobar el humano una tarea de `done` (`aprobá <clave>`), el autopilot mergea la(s) rama(s) a la base **solo local** y la tarea queda en `done`. |
| `COMMAND_TIMEOUT` | `900` | Tope (segundos) de lo que corre `aenv.sh`. |

Sin variables de ranuras, E2E ni Telegram: ya no existen.

## El bucle del orquestador

Siempre una de dos: está esperando a un coder (`orca orchestration check --wait --types
worker_done,escalation,question`) o esperándote a ti. Nunca deja de escuchar.

**A. Lanzar coders** — por cada tarea en `new/` sin coder activo:

1. `orca worktree create --name <clave> --repo <selector> [--activate]`
   (workspace: una por repo de la tarea; la rama sale de la base por defecto que Orca
   define para el repo); si falla (repo no registrado) → `## Motivo de stopped` en el
   `.md` y a `stopped/`; si el worktree ya existe (tarea devuelta), lo reusa;
2. mover el `.md` a `working/`;
4. `orca orchestration worker-start --spec "<encargo>" --worktree <clave> --agent <n> --json`
   (o un subagente `coder` del cliente en el worktree si no hay agente de orca);
5. respetando `MAX_CODERS`/`PARALLEL`.

**B. Terminó el coder** (`worker_done`/aviso de subagente):

1. leer `<board>/.autopilot/resultados/<clave>.md`; copiar las notas como
   `## Notas del desarrollador` en el `.md`;
2. según `RESULTADO`:
   - `done` (commiteó) → mover a `done/` (añadir `## Repos modificados`);
   - `EN ESPERA` + `CHOCA CON <otra>` → dejar en `working/` con nota y retomar
     cuando la otra termine (o volver a `new/`);
   - `STOPPED` → `## Motivo de stopped` al `.md` y mover a `stopped/` (no relanzar);
   - sin `RESULTADO` claro o worker `failed` → igual: `## Motivo de stopped` y `stopped/`;
3. reportar al humano la/s tarea/s en `done` (y las `stopped/` con su motivo).

**C. Revisión del humano** (mensaje en el chat):

- aprobar (`aprobá <clave>`) → la tarea queda en `done/`; con `AUTO_MERGE=true`, mergear
  antes (solo local, en cada repo de la tarea); conflicto → base intacta y `stopped/`
  con `## Motivo de stopped`;
- pedir cambios → `## Feedback del humano` al `.md` + mover de `done/` a `new/` (el coder
  la retoma antes, en la misma rama);
- resolver una `stopped` → la mueves de `stopped/` a `new/` (o directamente al flujo)
  cuando puedas.

**D. Escalaciones de orca** — `escalation`/`question` en el `check`: responder por
`orca orchestration reply --id <id> --body "…"` o decidir; si un worker no responde,
`worker-stop`/`worker-abandon`, `## Motivo de stopped` en el `.md` y `stopped/`.
Worktrees huérfanos:
`orca worktree rm --worktree <clave>`.

## Nunca contra producción

- **`aenv.sh` es la única vía** para ejecutar lo que se conecta a un ambiente:
  `aenv.sh <repo o worktree> -- <comando>`. Valida el `.env.autopilot` de ese repo con
  `entorno.py` (estados `ok` / `falta` / `inseguro` / `incompleto`); si no es `ok`,
  **no ejecuta** (salida 3) e imprime la recomendación.
- `entorno.py` clasifica las variables del `.env.autopilot`: modo (`NODE_ENV`/`FLUTTER_*`),
  bases de datos y URLs. Para ser `ok`: todo local o QA; los **URLs de API reales de
  producción se clasifican como no-permitidos**; una **URL de API corresponde a una base de
  datos** del mismo ambiente (local→local, QA→QA) — si una URL de QA no corresponde a la
  base de QA, es `inseguro`. La base debe decir "qa" en su nombre.
- `AUTOPILOT_PERMITIR=CLAVE1,CLAVE2` en `.env.autopilot` permite de a propósito
  servicios externos que no tienen versión de QA (p. ej. una pasarela de pagos de
  pruebas).
- Lo que **no** se conecta a nada (compilar, analizar, lint, instalar, tests unit/
  widget sin red) se puede correr directo, sin `aenv.sh`.
- El orquestador **tampoco** ejecuta contra ambientes: si algo hay que probar, se lo
  delega al coder (que lo corre con `aenv.sh`).
- Si algo parece producción, la tarea va a `stopped` con *MOTIVO: POSIBLE PRODUCCIÓN* y
  la recomendación; **no** se reintenta solo: lo resuelve el humano (creando/corrigiendo
  `.env.autopilot`) y devolviendo la tarea.
- El motivo de `stopped` se escribe **en Markdown con saltos de línea** (título + líneas
  `- ...` + párrafo de recomendación), porque lo lee el humano.

## Trabajo en paralelo y colisiones

- `PARALLEL=false` (default): 1 coder a la vez, sin colisiones.
- `PARALLEL=true`: hasta `MAX_CODERS` coders en paralelo, cada uno en su worktree/rama.
- **Dos workitems no tocan el mismo archivo a la vez.** El coder que necesita un archivo
  ya tomado por otra tarea activa hace `git checkout -- <archivo>` (deshace lo suyo sin
  committear) y termina `RESULTADO: EN ESPERA` + `CHOCA CON <otra clave>`. El
  orquestador lo retoma en su mismo worktree cuando la otra termina. No es fallo ni
  gasta intentos.
- El coder avisa en sus notas si trabajó esperando: el humano lo ve (no hay razón para
  esconderlo).

## Qué queda escrito en cada tarea

Secciones que el orquestador añade al `.md` (no reemplaza las del humano/coder):

- `## Notas del desarrollador` — de la corrida de cada intento usada (en el scratch
  `<board>/.autopilot/resultados/<clave>.md`): qué se hizo, por qué, cómo probarlo,
  pruebas corridas, decisiones, riesgos y pendientes.
- `## Feedback del humano` — cada pedido de cambios (revisión), con lo que no cumple y
  lo que se espera; acompaña a la vuelta de la tarea a `new/`.
- `## Repos modificados` — al pasar a `done`: por repo, rama, base, commits y resumen.
- `## Motivo de stopped` — al detener: `POSIBLE PRODUCCIÓN`, bloqueo, atascado o falta
  de herramienta, y la recomendación.

## La revisión del humano

1. En `done`: abre el `.md` → *Repos modificados*, *Notas del desarrollador*
   (qué hizo + cómo probarlo + pruebas que corrió). Puedes releer el diff del worktree
   de Orca de la tarea si quieres ver el código.
2. **Aprobar** → mergea la rama a la base (a mano, o `AUTO_MERGE=true`). La tarea queda
   en `done/`. La rama no se borra (a mano o `orca worktree rm` si ya no la necesitas).
3. **Pedir cambios** → `## Feedback del humano` (qué está mal, qué esperas, dónde) y
   mover a `new/`. El coder corrige solo eso, en la misma rama, y la deja otra vez
   en `done`.

Con `AUTO_MERGE=true` el autopilot hace el paso 2 al aprobar (merge local sin
push). Si choca, la base queda intacta y la tarea va a `stopped/` con el motivo.

## Orca

El kit delega en la CLI de Orca toda la ejecución. Comandos que usa el orquestador
(todos en el PATH de tu máquina):

| Necesidad | Comando |
|---|---|
| Runtime listo | `orca status` |
| Registrar repo | `orca repo add --path <ruta>` → luego `orca repo list` |
| Cuentas de agente | `orca account list` (si falta: `orca account add`) |
| Worktree de una tarea | `orca worktree create --name <clave> --repo <selector> [--activate]` (nace de la base por defecto del repo) |
| Limpiar worktree | `orca worktree rm --worktree <clave>` |
| Run de la sesión (una vez) | `orca orchestration run-create --objective "<resumen>"` → devuelve `run_id` |
| Despachar al coder | `orca orchestration worker-start --spec "<encargo>" --worktree <clave> --agent <n> --json` |
| Esperar eventos | `orca orchestration check --wait --types worker_done,escalation,question --timeout-ms <ms>` |
| Responder a un coder | `orca orchestration reply --id <message_id> --body "…"` |
| Ver vivos | `orca orchestration worker-list --run <run_id> --json` / `worker-show` |
| Detener worker | `orca orchestration worker-stop` / `worker-abandon` |

El encargo (spec) cumple el contrato de orca **Target / Change / Constraints /
Ownership / Observable acceptance** y además: ruta del board y clave (para `cat` del
`.md`), ruta del worktree, repo, rama y base, `$K` del kit (validadores), la ruta de
salida y la instrucción de terminar con `NOTAS DEL DESARROLLADOR` + `RESULTADO`.

## Qué incluye el kit

```
autopilot/
├── README.md                esta guía
├── docs/REFERENCIA.md       este documento
├── install.sh               instala el kit LOCAL (validadores + skills + agente coder)
├── agents/coder.md          el programador (fuente única, por-cliente se genera)
├── clients/render.py        genera el agente y los comandos según el cliente
├── skills/
│   ├── autopilot/SKILL.md         corriente: el bucle, estados, reglas
│   ├── autopilot/aenv.sh          entorno.py + aenv.sh (validadores de producción)
│   ├── autopilot-plan/SKILL.md    de idea/documento a tareas (brainstorming)
│   └── autopilot-init/SKILL.md    prepara un proyecto (autopilot.env + board)
├── examples/proyecto/          autopilot.env.example
└── integraciones/azure/        sync de tareas desde Azure DevOps
```

Ya **no** hay scripts de maquinaria (wi.sh, watcher.sh, workitems.py, emit, guardas,
health-check, run-tests, e2e.py…) — eso lo hace Orca. El kit conserva solo los dos
**validadores** (`aenv.sh`/`entorno.py`) que refuerzan la regla *nunca contra
producción* en tiempo de corrida.

## Seguridad

- Los agentes **no pueden** hacer `git push`, `git merge`, `git pull`, borrar ramas ni
  `reset --hard`, y **no pueden** escribir archivos `.env*` (reglas de permiso de cada
  cliente, reforzadas por el coder y por `aenv.sh`).
- `aenv.sh` es la única vía a BD/API; sin él, los comandos que conectan están
  bloqueados en los permisos del cliente (OpenCode los niega por patrón).
- Los `.env.autopilot` solo los escribe el humano; no se muestran valores (solo
  estados) ni se copian.
- El orquestador no ejecuta contra ambientes y no hace push ni merge.