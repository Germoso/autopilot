# dotenvs

Kit portable de un **sistema de desarrollo autónomo** para **OpenCode y Claude Code**, sobre un
board de workitems hecho de **carpetas y archivos Markdown**. Sin Notion, sin tokens, sin red.
Opcionalmente, conectado a Azure DevOps con el MCP oficial de Microsoft (sin permisos de admin).

Dos subsistemas independientes, ambos opt-in por proyecto:

| Comando | Qué hace | Consume tokens |
|---|---|---|
| `/autopilot-init` | Prepara la carpeta abierta: un repo o un **workspace con varios repos**. Detecta ramas y proyectos de Azure, pregunta la rama base de cada repo y crea la config y el board. | sí (poco) |
| `/autopilot` | Detecta tareas en el board y las trabaja con subagentes, cada una en su rama. Ciclo completo: `new` → `in-progress` → `qa` → `validando` → `done`, con `bug-fix` hasta 3 intentos. Opcional (`E2E=true`): antes de `done`, pruebas E2E en web y Android (`e2e` → `probando-e2e`). | sí |
| `/azure-sync` | Importa Work Items de Azure DevOps al board como `new`. Aditivo, con dedup. | no |

---

## Qué incluye

```
dotenvs/
├── install.sh                  # instala para OpenCode y/o Claude Code; --init prepara proyectos
├── lib/                        # -> ~/.local/share/autopilot-kit/  (compartido por ambos clientes)
│   ├── workitems.py            # formato del board (unica implementacion)
│   ├── wi.sh                   # unica via de escritura del board + ramas
│   ├── watcher.sh              # sensor: lee el board y retorna
│   ├── azure-sync.py           # importador aditivo de Azure DevOps (uno o varios proyectos)
│   ├── init.py                 # prepara un repo o workspace (lo usa /autopilot-init)
│   ├── git-guard.sh            # bloquea push/merge (hooks de Claude Code)
│   ├── aenv.sh / entorno.py    # nunca contra produccion: corre con .env.autopilot(.e2e) validado
│   ├── vigia.py                # vigilante: procesos colgados/huerfanos, tareas atascadas
│   ├── e2e.sh / e2e.py         # agente E2E: apps al backend local, emulador sin DNS, navegador con red cortada
│   ├── e2e-setup.sh            # instala Java, Android SDK + emulador + AVD, Playwright (una vez, sin sudo)
│   ├── e2e-playwright.config.cjs, e2e-pasos.cjs, e2e_driver.dart   # capturas en cada paso (web/Android)
│   └── ado-mcp.sh              # lanza el MCP de Azure DevOps con tu PAT
├── skills/                     # -> carpeta de skills de cada cliente
│   ├── autopilot/SKILL.md      # reglas, maquina de estados, arranque por cliente
│   ├── autopilot-init/SKILL.md # /autopilot-init
│   └── azure-sync/SKILL.md
├── agents/                     # fuente unica de los subagentes
│   ├── coder.md
│   ├── qa-reviewer.md
│   └── e2e-tester.md           # pruebas E2E en web y Android (con E2E=true)
├── clients/render.py           # genera agentes/comandos/guardas para cada cliente
└── examples/proyecto/          # autopilot.env, azure-sync.env, .env.autopilot.e2e (ejemplos)
```

### Qué se instala en cada cliente

| | OpenCode | Claude Code |
|---|---|---|
| Skills | `~/.config/opencode/skills/` | `~/.claude/skills/` |
| Subagentes | `~/.config/opencode/agents/*.md` | `~/.claude/agents/*.md` |
| `/autopilot-init`, `/autopilot`, `/azure-sync` | comandos en `~/.config/opencode/commands/` | las propias skills |
| Bloqueo de push/merge en subagentes | `permission.bash` con `deny` | hook `PreToolUse` → `git-guard.sh` |
| Bloqueo en el agente principal (por proyecto) | `opencode.json` del proyecto | `.claude/settings.local.json` (deny + hook) |
| Cómo espera el watcher | primer plano | segundo plano (`run_in_background`): Claude Code te re-invoca al terminar |
| MCP de Azure DevOps | `opencode.json` → `ado-mcp.sh` | `claude mcp` (scope user) → `ado-mcp.sh` |
| Herramientas E2E (opcional, `e2e-setup.sh`) | `~/.local/share/autopilot-e2e/` | la misma carpeta |

Los agentes se escriben **una vez** en `agents/`; `clients/render.py` genera la versión de cada
cliente. Todo lo generado lleva una marca y `--uninstall` solo borra lo que tiene la marca.

---

## El board

```
mi-proyecto/
├── autopilot.env
├── .gitignore                    # incluye .workitems/
└── .workitems/
    ├── new/
    │   └── bug-140123-login-falla-con-google.md
    ├── in-progress/
    ├── qa/
    ├── validando/
    ├── e2e/                      # QA aprobó; cola de pruebas E2E (solo con E2E=true)
    ├── probando-e2e/
    ├── bug-fix/
    ├── stopped/
    ├── done/
    ├── reviewed/                 # done que ya revisaste (la mueves tú)
    └── log.md                    # log de actividad (solo se agregan filas)
```

- **El estado de una tarea es la carpeta donde está.** Cambiar de estado es mover el archivo.
  Podés mover tareas a mano (explorador, VS Code, Obsidian); el watcher lo ve en segundos.
- **`reviewed`**: cuando revisas una tarea de `done`, muévela a `reviewed/` (arrastrando el archivo
  o con `wi.sh <env> reviewed <clave>`). Así `done` queda solo con lo pendiente de revisar. El
  autopilot nunca mueve tareas a `reviewed` ni las vuelve a tocar.
- **El nombre del archivo es `<tipo>-<numero>-<slug>.md`.** `<tipo>-<numero>` es la clave de
  la tarea y **el nombre de su rama**.
- **El board no está en git.** Si lo estuviera, cada vez que una rama cambia el
  tablero cambiaría con ella. `install.sh --init` lo agrega al `.gitignore`. Con
  `WORKITEMS_DIR` se puede poner en otra carpeta (un vault de Obsidian, una carpeta compartida).

Una tarea:

```markdown
---
id: 140123
tipo: bug
prioridad: High
intento: 1
rama: bug-140123
repo: -
origen: azure:Konectame_App_Clientes
actualizado: 2026-09-29T14:02:00+00:00
---
# Login falla con Google

## Descripción

...

## Criterio de aceptación

- ...

## Feedback de QA

### Intento 1 — RECHAZADO (2026-09-29T15:10:00+00:00)

...

## Resultado

bug-140123 @ a1b2c3d — resumen

## Motivo de stopped

```

El feedback de QA **se acumula por intento**: al llegar a `stopped`, el historial está entero.

---

## Ramas

- **Una rama independiente por workitem**: `task-<numero>` o `bug-<numero>` (ej. `bug-140123`).
- **Siempre desde la rama base de su repo**, definida en `autopilot.env` (obligatoria):
  `BASE_BRANCH=<rama>` en un repo, o `REPO.<carpeta>=<rama>` por repo en un workspace.
  Si está vacía o la rama no existe (ni local ni en `origin`), la tarea pasa a `stopped`:
  no se inventa otra base.
- **Workspace:** la rama se crea **dentro del repo de la tarea** (`repo:` en su frontmatter).
  Una tarea sin repo, o con un repo que no está en `autopilot.env`, pasa a `stopped`.
- Cada tarea se trabaja en su **propia copia del repo** (`git worktree`): tu copia principal no se
  toca ni cambia de rama, aunque tenga cambios sin commitear.
- Si la rama de una tarea nueva ya existe, `stopped`: no se pisa trabajo previo.
- Un rechazo de QA se corrige **en la misma rama**.
- **Nunca `push`, nunca `merge`.** Bloqueados por permiso. El merge lo hace el humano.

---

## Instalación

```sh
git clone <tu-repo> dotenvs
cd dotenvs
./install.sh                              # detecta OpenCode y Claude Code
./install.sh --claude                     # o solo uno
./install.sh --with-ado-mcp codikasrl     # ademas registra el MCP de Azure DevOps
```

No pisa nada que no haya generado el kit: si ya existe una skill, agente o MCP con el mismo
nombre y no es del kit, lo deja y avisa. Reinstalar actualiza lo que sí es del kit.

Para las pruebas E2E (opcional), además, una vez: `~/.local/share/autopilot-kit/e2e-setup.sh`
(ver *Pruebas E2E: terminar de certificar*).

### Desinstalar

```sh
./install.sh --uninstall
```

Quita scripts, skills, agentes, comandos y el registro del MCP. Quedan intactos los proyectos
(`.env`, board, guardas) y tu PAT en `~/.config/autopilot-kit/`. Las herramientas E2E
(`~/.local/share/autopilot-e2e/`, ~6 GB) tampoco se tocan: bórralas con
`rm -rf ~/.local/share/autopilot-e2e` si ya no las usas.

---

## MCP de Azure DevOps (opcional)

Usa el [servidor local oficial de Microsoft](https://github.com/microsoft/azure-devops-mcp)
(`@azure-devops/mcp`) con **autenticación por PAT**:

- **No requiere admin** de la organización ni del tenant. El servidor *remoto*
  (`mcp.dev.azure.com`) sí lo requiere para clientes como OpenCode y Claude Code (app registration +
  admin consent en Entra ID), por eso no se usa.
- Requisitos: Node 20+, organización respaldada por Entra ID, y un PAT personal con
  **Work Items (Read & Write)**.
- El PAT **nunca** va en la config del cliente: `ado-mcp.sh` lo lee de
  `~/.config/autopilot-kit/ado-mcp.secrets.env` (o de `AZURE_DEVOPS_PAT`) y lo pasa al MCP.
- Dominios cargados: `core work work-items`.

Guardar el PAT (en tu terminal, no en el chat del agente):

```sh
(umask 077; read -rsp 'PAT: ' p; echo; printf 'AZURE_DEVOPS_PAT=%s\n' "$p" > ~/.config/autopilot-kit/ado-mcp.secrets.env)
```

La **importación** al board la sigue haciendo `azure-sync.py` (sin tokens, con dedup). El MCP
sirve para consultar Azure o escribir de vuelta desde el agente principal; los subagentes no lo usan.

---

## Configurar un proyecto

Abrí OpenCode o Claude Code **en la carpeta del proyecto** y ejecutá:

```
/autopilot-init
```

El agente detecta si la carpeta es **un repo** o un **workspace** (una carpeta con varios repos
adentro), te muestra las ramas de cada repo con una sugerida, te pregunta la rama base de cada
uno y crea todo. Sin `autopilot.env`, la carpeta no participa.

También sin agente: `./install.sh --init /ruta --base dev` (un repo) o
`--base <repo>=<rama>` por cada repo (workspace).

Qué hace:

- crea `autopilot.env`, `azure-sync.env` (org y proyecto deducidos del remoto de cada repo,
  sprint `@current`) y el board `.workitems/`
- **no toca archivos de los repos**: en un repo, lo del kit se ignora solo en tu copia local
  (`.git/info/exclude`); en un workspace todo vive en la carpeta padre. No hay nada que commitear.
- prohíbe push/merge también al agente principal (en cada cliente instalado)
- avisa si falta alguna rama base o si no existe, herramientas o un `.env.autopilot` válido
- deja en `autopilot.env` la **config E2E sugerida, apagada** (`E2E=false`): qué app consume cada
  backend, plataformas y cómo apuntar cada app Flutter al backend local. Si `autopilot.env` ya
  existía, le agrega ese bloque al final (ver *Pruebas E2E*)

### Workspace: varios repos, un board

```
konectame/                      <- abrís el cliente acá
├── autopilot.env               REPO.Konectame_App_Clientes=dev
│                               REPO.Konectame_BackOffice=master ...
├── azure-sync.env              SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current ...
├── .workitems/                 un solo board; cada tarea dice su repo (repo: <carpeta>)
├── Konectame_App_Clientes/     <- la rama bug-140123 se crea ACÁ, desde dev
└── Konectame_BackOffice/
```

- Cada repo tiene **su propia rama base**. La rama de cada tarea se crea dentro de su repo.
- azure-sync lee **un proyecto de Azure por repo** y le pone a cada tarea su `repo:`.
- Los puestos son globales: **un coder, un QA (y un E2E)** para todo el workspace (ver *Puestos en paralelo*).

### Una tarea en varios repos

Si la corrección de un work item está (también) en **otro repo del workspace** — p. ej. el bug es
de la app pero la causa está en el backend —, el coder **no se detiene ni pide otro work item**:

- abre la **misma rama** (`bug-37271`) en ese repo con
  `wi.sh <env> rama bug-37271 nueva --repo Konectame_BackOffice_BE`, desde la rama base **de ese
  repo**; queda registrado en la tarea (`repos_extra:`);
- corrige y commitea ahí; en sus **notas del desarrollador** detalla repo por repo (rama, commits,
  archivos), por qué tocó cada uno y en qué orden levantarlos o desplegarlos;
- el QA recibe **una copia de trabajo por repo** y los revisa y prueba todos; un rechazo vuelve a
  poner la rama en todos los repos de la tarea.

Solo repos declarados en `autopilot.env` (`REPO.<carpeta>`); si hace falta uno que no está, el
coder termina en `stopped` explicando cuál. El bloqueo de git no cambia: el coder no crea ramas con
git, lo hace `wi.sh` con las mismas validaciones (base del repo, árbol limpio).

`autopilot.env`:

| Variable | Default | Qué es |
|---|---|---|
| `REPO_PATH` | carpeta del `.env` | Ruta del repo |
| `BASE_BRANCH` | **obligatoria** (un repo) | Rama desde la que nacen las ramas de los workitems (`dev`, `main`...) |
| `REPO.<carpeta>` | **una por repo** (workspace) | Rama base de ese repo. Si hay alguna, es un workspace |
| `WORKITEMS_DIR` | `$REPO_PATH/.workitems` | Carpeta del board |
| `POLL_INTERVAL` | `5` | Segundos entre lecturas del board |
| `PARALLEL`, `MAX_CODERS`, `MAX_QA`, `MAX_E2E` | `false`, `2`, `2`, `1` | Agentes a la vez (ver *Cuántos agentes a la vez*) |
| `WATCHDOG`, `WATCHDOG_INTERVAL`, `HUNG_MINUTES`, `STALE_MINUTES`, `COMMAND_TIMEOUT` | `true`, `60`, `10`, `45`, `900` | Vigilante y tiempo máximo de `aenv.sh` (ver *Vigilante*) |
| `E2E`, `E2E_COMMAND_TIMEOUT` | `false`, `2400` | Etapa de pruebas E2E y su tiempo máximo por comando (ver *Pruebas E2E*) |
| `E2E_CLIENTS.<backend>`, `E2E_PLATFORMS.<front>`, `E2E_API.<app>` | — | Qué fronts consumen cada backend, en qué plataformas se prueban, cómo apuntar la app al backend local |

**La rama base se define por proyecto/repo** en su `autopilot.env`. Para cambiarla, editá la
línea o volvé a correr `/autopilot-init`; no hace falta reinstalar nada.

El PAT para `azure-sync.py` se busca en `AZURE_DEVOPS_PAT`, `azure-sync.secrets.env` y, si no,
en el del MCP (`~/.config/autopilot-kit/ado-mcp.secrets.env`): con el MCP configurado no hace falta nada más.

---

## Uso

```sh
/autopilot-init   # una vez por proyecto/workspace
/azure-sync       # importa Work Items de Azure al board
/autopilot        # arranca el bucle: espera tareas y las trabaja
```

Crear una tarea a mano:

```sh
~/.local/share/autopilot-kit/wi.sh ./autopilot.env \
  add-task bug 140123 High "Login falla con Google" "descripcion" "criterio" [repo]   # repo: obligatorio en workspace
```

(o escribir el `.md` directamente en `.workitems/new/` respetando el nombre `<tipo>-<numero>-*.md`).

En un proyecto sin el `.env`, ambos comandos dicen que el proyecto no participa
y no hacen nada.

### azure-sync

Importa a `.workitems/new/` los work items **Task/Bug en estado New** del sprint. Solo crea,
nunca modifica; no gasta tokens; deduplica por número (los IDs son únicos en la organización).

`azure-sync.env` (lo genera `/autopilot-init` desde los remotos de git):

```ini
AZURE_ORG=codikasrl

# Un repo
AZURE_PROJECT=Konectame_App_Clientes
AZURE_ITERATION=@current

# Workspace: una fuente por repo -> SYNC.<carpeta>=<proyecto de Azure>|<sprint>
SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current
SYNC.Konectame_BackOffice=Konectame_BackOffice|@current
```

- **Sprint:** `@current` = sprint actual del equipo `<Proyecto> Team` (se actualiza solo al
  cambiar de sprint); `@current:<Equipo>` para otro equipo; o una ruta fija `Proyecto\Sprint X`.
- En un workspace cada tarea se crea con su `repo:`. Cada `SYNC.<repo>` necesita su `REPO.<repo>`.
- Si **cualquier** fuente falla, no se escribe nada en el board.
- `--refrescar [clave…]` vuelve a traer de Azure la descripción, el criterio y los adjuntos de tareas
  **ya importadas** (sin claves: todas) con el formato actual. No cambia su estado ni toca notas,
  reportes ni feedback. Útil para tareas importadas antes de una mejora del importador.
- `--dry-run` muestra qué importaría (con cuántas imágenes/videos); `--status` cuenta por fuente;
  `--watch 60` en bucle; `--fotogramas` procesa videos ya descargados (tras instalar ffmpeg).

### Adjuntos: capturas y videos

Cada work item importado trae sus adjuntos a `.workitems/adjuntos/<clave>/`:

- **Imágenes incrustadas** en la descripción o los pasos: se descargan y quedan en su lugar en el
  texto como `![imagen N](../adjuntos/<clave>/...)`.
- **Adjuntos** del work item (imágenes, videos, otros), listados en la sección `## Adjuntos`.
- **Videos:** con `ffmpeg` instalado se extraen hasta 12 fotogramas (primer cuadro + cambios de
  escena, repartidos) en `<video>.frames/fNN.png`, porque ningún modelo ve video directamente.
  Sin ffmpeg se guarda el video y queda la nota; después: `azure-sync.py --config ... --fotogramas`.
- Límite de 50 MB por archivo. Un adjunto que falla no frena la importación: queda anotado.

El autopilot le pasa las imágenes y fotogramas al coder, al QA y al agente E2E (`tarea.adjuntos`).

**Requisito:** `sudo apt install ffmpeg` para los fotogramas.

### El watcher

`/autopilot` lanza `watcher.sh`, que espera sin gastar tokens y retorna cuando hay trabajo.

- **OpenCode:** en primer plano.
- **Claude Code:** en segundo plano; Claude Code re-invoca al agente cuando el watcher termina
  (en primer plano lo cortaría a los 10 minutos).

No hay demonios que abran sesiones aparte. **Limitación:** si cerrás el cliente, deja de vigilar.

`azure-sync` sí puede correr como demonio, porque no lanza agentes:

```sh
setsid nohup python3 ~/.local/share/autopilot-kit/azure-sync.py \
  --config ./azure-sync.env --watch 60 &>/dev/null &
```

---

## Puestos en paralelo

| Puesto | Agente | Toma de | Mientras trabaja | Máximo |
|---|---|---|---|---|
| coder | `coder` | `bug-fix` > `new` | `in-progress` | `MAX_CODERS` |
| QA | `qa-reviewer` | `qa` | `validando` | `MAX_QA` |
| E2E (con `E2E=true`) | `e2e-tester` | `e2e` | `probando-e2e` | `MAX_E2E` |

Mientras un coder desarrolla una tarea, el QA puede estar certificando otra y el agente E2E
probando una tercera.

- **Claude Code:** los subagentes corren en segundo plano; Claude Code avisa al agente principal
  cuando terminan.
- **OpenCode:** cada tarea corre como **su propia sesión** de OpenCode, lanzada por la API del
  servicio local (`oc_sesion.py`). Las ves en tu lista de sesiones y podés mirarlas en vivo. El
  watcher avisa cuando una termina. Si cerrás OpenCode, esas sesiones siguen; al volver,
  `/autopilot` las retoma.
- **El QA trabaja en su propia copia del repo** (`git worktree` en `~/.cache/autopilot-kit/qa/`,
  en la punta de la rama de la tarea): puede compilar y correr tests o la app sin pisar al coder.
  Se borra al dar el veredicto.
- **El agente E2E también** (`~/.cache/autopilot-kit/e2e/`): una copia por cada repo de la tarea y
  por cada repo que pide el flujo real (el backend de una app, las apps de un backend). Se borra al
  dar el veredicto, matando backend, servidor web y emulador que queden ahí.

### Cuántos agentes a la vez

En `autopilot.env`:

```ini
PARALLEL=false  # false = 1 coder + 1 QA + 1 E2E (defecto). true = hasta MAX_CODERS, MAX_QA y MAX_E2E
MAX_CODERS=2
MAX_QA=2
MAX_E2E=1       # solo cuenta con E2E=true
```

- **Cada agente trabaja un workitem distinto.** Nunca hay dos coders en la misma tarea.
- **Cada coder en su propia copia del repo** (`git worktree` en `~/.cache/autopilot-kit/coder/<repo>-<clave>`)
  con su propia rama. Tu copia principal del repo **nunca cambia de rama** (también con `PARALLEL=false`).
- **Dos workitems en paralelo no tocan el mismo archivo:** el primero que lo edita lo reserva (en
  Claude Code, automáticamente al editar; con `wi.sh reservar` desde la terminal o en OpenCode).
  El otro se pone **en espera** y se retoma, en su misma copia, cuando el primero termina.
- Al terminar un coder, `wi.sh solapes` compara sus archivos con los de las demás tareas activas y
  avisa si comparten alguno (posible conflicto al mergear).
- Límites: dos tareas pueden tocar archivos distintos y aun así depender una de otra; eso lo ve el
  QA o se ve al mergear. **Cada agente gasta tokens y memoria**: con 7 GB de RAM y Flutter, 2 + 2 es
  el máximo razonable; con E2E (emulador de 2 GB + build de Android) conviene bajar a 1 + 1 + 1.

### Vigilante: nada se queda colgado

El watcher corre cada `WATCHDOG_INTERVAL` segundos un vigilante (`vigia.py`, no gasta tokens) que
mira los procesos de cada tarea (los reconoce porque corren dentro de su copia del repo):

- **Colgados:** si los procesos de una tarea activa llevan `HUNG_MINUTES` **sin usar nada de CPU**
  (están vivos pero no hacen nada, p. ej. un test esperando una animación que no termina), los mata.
  El comando del agente termina con error y el agente sigue. Un proceso lento pero que trabaja
  (su CPU avanza) nunca se toca.
- **Huérfanos:** procesos que siguen vivos cuando su tarea ya no está en su puesto (p. ej. un
  MongoDB en memoria que el QA dejó levantado) → los mata en la siguiente revisión. Al borrar la
  copia de una tarea, también se matan sus procesos.
- **Tareas atascadas:** una tarea en su puesto sin ninguna actividad (archivos, commits, CPU)
  durante `STALE_MINUTES` → despierta al agente principal para que revise al agente.
- **Prevención:** lo que corre por `aenv.sh` tiene tiempo máximo (`COMMAND_TIMEOUT`), y los agentes
  corren los tests con límite (`flutter test --timeout 120s`, jest `--testTimeout`) y apagan lo que
  levantan.
- Solo toca procesos de trabajo (node, dart, flutter, mongod, tests…, y el emulador del E2E, que
  arranca dentro de su copia) dentro de las copias de este board (coder, QA y E2E); nunca
  terminales, editores ni los clientes. Todo queda en `log.md`.

```ini
WATCHDOG=true           # false = apagado
WATCHDOG_INTERVAL=60    # segundos entre revisiones
HUNG_MINUTES=10         # minutos sin usar CPU para considerar colgado
STALE_MINUTES=45        # minutos sin actividad para avisar de una tarea atascada
COMMAND_TIMEOUT=900     # segundos máximos de un comando por aenv.sh
E2E_COMMAND_TIMEOUT=2400  # lo mismo para aenv.sh --e2e y e2e.sh (builds de Android)
```

Revisarlo a mano: `python3 ~/.local/share/autopilot-kit/vigia.py <autopilot.env> --simular`.

### Nunca contra producción: `.env.autopilot`

Los agentes **nunca** ejecutan nada contra un ambiente con el `.env` del repo. Solo usan un archivo
que **creas tú a mano** en cada repo que lo necesite (backends con base de datos o APIs):

```sh
cd ~/code/codika/konectame/Konectame_BackOffice_BE
cp .env .env.autopilot     # y cambia la BD y las URLs a las de QA (o a local)
```

- Todo lo que se conecta a una BD o API (tests de integración/e2e, levantar el backend,
  migraciones, seeds, scripts, HTTP) corre solo con `aenv.sh <repo> -- <comando>`, que valida
  `.env.autopilot` y exporta sus valores. Los comandos directos (`npm test`, `npm run start`,
  `node`, `npx jest`, `prisma`, `flutter run`...) los bloquea el hook (Claude Code) o los permisos
  (OpenCode).
- `.env.autopilot` es válido si **todo destino** es local (`localhost`, `127.0.0.1`, sqlite...) o de
  QA — **la base de datos tiene que decir "qa" en su nombre** — y si define **todas** las variables
  de BD/URL que tiene el `.env` real (si no, se colaría el valor real). `NODE_ENV=production`
  o una URL sin "qa" lo invalidan.
- ¿Un servicio externo sin versión de QA (p. ej. una API de mapas de solo lectura)? Permítelo a
  propósito en tu archivo: `AUTOPILOT_PERMITIR=GEOCODING_API_URL`.
- Revisarlo sin ver valores: `wi.sh <env> entorno <repo>`. `/autopilot-init`, `wi.sh check` y el
  watcher avisan de los repos sin un `.env.autopilot` válido.
- Ningún agente crea, copia ni edita `.env*`. Ante la duda de si algo es producción, la tarea va a
  `stopped` con la recomendación de qué hacer.
- Apps Flutter: la URL de la API está fija en `config.dart`, así que el coder y el QA no las levantan
  contra una API real; los tests unitarios y de widget (sin red) sí corren. Solo el agente E2E corre
  las apps, apuntadas por el kit a un backend **local** (ver *Pruebas E2E*).

### El QA certifica al 100% o no certifica

`APROBADO` solo si **probó** todo: compila y analiza sin errores nuevos, los tests pasan y **cada
criterio** tiene una ejecución que lo demuestra (un test existente o uno temporal que escribe en su
copia de trabajo). "Cumple por lectura de código" no alcanza.

- **Lo visual** (espacios, colores, layout) se prueba con un **test de widget temporal** que mide la
  pantalla y guarda una **captura PNG**, que el QA abre y compara con las capturas del bug.
- **Tres veredictos:** `APROBADO` → `done` (o a la cola `e2e` con `E2E=true`); `RECHAZADO` → `bug-fix` (trabajo para el coder);
  **`NO CERTIFICABLE`** → `stopped` con lo que falta (herramienta, versión, entorno o dato). Cuando
  lo resuelvas: `wi.sh <env> reqa <clave>` la devuelve a la cola del QA.
- **Herramientas:** el QA usa la versión que pide cada repo (`fvm` con la de `.fvmrc`, Flutter, Node).
  Si falta alguna, lo avisan `/autopilot-init` y el watcher al arrancar, y esas tareas quedan en
  `stopped` en vez de certificarse a ciegas.
- El QA solo puede escribir dentro de sus copias de trabajo (hook en Claude Code, permiso por ruta
  en OpenCode): nunca en el repo del coder ni en el board.

### Las imágenes se ven en la tarea

Todas las imágenes quedan **enlazadas en el `.md`** de la tarea, para verlas junto al texto en VS
Code, Obsidian o GitHub:

- las del work item (capturas y fotogramas), en `## Adjuntos` y en su lugar dentro del texto;
- las que el **coder** genera o usa, en sus notas (`adjuntos/<clave>/coder-intentoN/`);
- las **capturas del QA** (sus tests de widget), en su reporte (`adjuntos/<clave>/qa-intentoN/`).
  Se copian del worktree del QA antes de borrarlo, así no se pierden.
- las **capturas de cada paso de las pruebas E2E** (web y Android) y sus videos, en el
  `## Reporte E2E` (`adjuntos/<clave>/e2e-intentoN/`), en el paso que muestran.

Cualquier ruta de imagen que un agente escriba en sus notas o su reporte se convierte en
`![nombre](../adjuntos/...)`; si está fuera del board, primero se copia.

### Qué queda escrito en cada tarea

- **`## Repos modificados`**: tabla calculada **desde git** al pasar a `qa` (repo, rama, base,
  commits, archivos), con aviso si no coincide con lo que declaró el coder. Te dice qué ramas
  mergear y dónde. En JSON: `wi.sh <env> repos-modificados <clave>`.
- **`## Notas del desarrollador`** (por intento): empieza con **REPOS MODIFICADOS** (la lista que
  declara el coder), y luego qué se hizo y por qué, archivos cambiados,
  decisiones, cómo probarlo, pruebas que corrió, riesgos y pendientes.
- **`## Reporte de QA`** (por intento): cada criterio (CUMPLE / NO CUMPLE / NO VERIFICABLE con
  evidencia de ejecución), las herramientas usadas, **qué probó** (comandos, tests temporales y capturas), **cómo verificarlo manualmente de punta a
  punta** (preparación, pasos, resultado esperado, casos borde) y **puntos a tomar en cuenta**
  (regresiones, migraciones, configuración, datos...).
- **`## Reporte E2E`** (por intento, con `E2E=true`): plataformas y ambiente, cada criterio con los
  pasos del flujo real y **la captura de cada paso**, videos, hosts que la red bloqueó, cómo
  repetirlo a mano. **`## Feedback de E2E`**: aprobado o rechazado, por intento.

### Pruebas E2E: terminar de certificar (`e2e-tester`)

Con `E2E=true`, lo que el QA aprueba no va a `done`: pasa a la cola `e2e`. El agente **`e2e-tester`**
recorre **como una persona** el flujo de cada criterio, de punta a punta — app o BackOffice →
backend de la rama → base de datos — en **web** (Playwright + Chromium) y en un **emulador Android**,
y saca **capturas en cada paso** (y video). Veredicto:

- `APROBADO` → `done`. `wi.sh aprobar-e2e` **se niega** si algún criterio no dice CUMPLE, no tiene
  capturas o falta una plataforma esperada.
- `RECHAZADO` → `bug-fix`, con el `Feedback de E2E` y las capturas del paso que falló; el coder corrige
  y la tarea vuelve a pasar por QA y E2E (máximo 3 intentos en total).
- `NO CERTIFICABLE` → `stopped` (falta herramienta, cuenta, `.env.autopilot.e2e`...). Cuando lo
  resuelvas: `wi.sh <env> re-e2e <clave>`.

**Nunca contra producción, también en E2E:**

- Los **backends corren locales**, desde las copias E2E, con `aenv.sh --e2e`, usando
  **`.env.autopilot.e2e`** (lo creas tú, como `.env.autopilot`): mismas reglas (BD con "qa" en el
  nombre, nada de producción) y además una **base de datos exclusiva para E2E**, distinta de la de
  `.env.autopilot` (las pruebas crean usuarios, reservas...). Si es la misma, se niega (`compartida`).
  Incluye `PORT` (el puerto del backend local).
- Las **apps Flutter** se apuntan a ese backend local con `e2e.sh api` (`E2E_API`: reemplaza la línea
  de la URL en la copia E2E, nunca se commitea; la URL la pone el kit: `http://localhost:<PORT>` en
  web y `http://10.0.2.2:<PORT>` en Android). Si alguien edita ese archivo después, `e2e.sh app` no
  corre.
- El **navegador** no resuelve ningún servidor salvo localhost (y las fuentes de Google): una llamada
  a otro servidor falla y queda en `red-bloqueada.txt`. El **emulador** arranca **sin DNS**: solo
  alcanza el backend local.
- Apps, emulador y navegador solo por `e2e.sh`; el hook/permisos bloquean `flutter build/run/drive`,
  `playwright` y `emulator` directos.

Ejemplo comentado de los tres `.env.autopilot.e2e` (backend, front web y cuentas):
`examples/proyecto/env.autopilot.e2e.example`.

**Cuentas de prueba:** en `.env.autopilot.e2e` junto a `autopilot.env`:
`E2E_CLIENTE_USER=…`, `E2E_CLIENTE_PASSWORD=…`, `E2E_ADMIN_USER=…` (un par por rol; solo cuentas
de QA que existan en la base E2E). El agente nunca las escribe en el reporte.

**Para activarlo:**

1. `~/.local/share/autopilot-kit/e2e-setup.sh` (una vez, sin sudo, ~6 GB en
   `~/.local/share/autopilot-e2e`: Java 17, Android SDK + emulador + AVD `autopilot_e2e`, Playwright +
   Chromium). No toca tu Flutter, tu Java ni `~/.android`. Si no tienes acceso a `/dev/kvm`:
   `sudo usermod -aG kvm $USER`. Para quitarlo: `rm -rf ~/.local/share/autopilot-e2e`.
2. Crea la base exclusiva (p. ej. `KonectameQADB_E2E`) con las cuentas de prueba, y los
   `.env.autopilot.e2e` de cada backend y front web (el del BackOffice apunta su URL de API al
   `http://localhost:<PORT>` del backend).
3. Revisa en `autopilot.env` el bloque E2E que propone `/autopilot-init`:
   ```sh
   E2E=true
   MAX_E2E=1                        # con emulador, 1 (RAM)
   E2E_COMMAND_TIMEOUT=2400         # el primer build de Android es largo
   E2E_CLIENTS.Konectame_App_Clientes_BE=Konectame_App_Clientes      # qué fronts consumen cada backend
   E2E_CLIENTS.Konectame_BackOffice_BE=Konectame_BackOffice
   E2E_PLATFORMS.Konectame_App_Clientes=web,android
   E2E_PLATFORMS.Konectame_BackOffice=web
   E2E_API.Konectame_App_Clientes=lib/config/config.dart|^final baseUrl = .*;$|final baseUrl = "{API}";
   ```
   Con `E2E_CLIENTS`, una tarea que solo toca un backend igual se prueba desde sus apps (en su rama
   base), y una que solo toca una app levanta su backend.
4. `wi.sh <env> check` no debe dar avisos de E2E. Reinicia `/autopilot`.

Memoria: emulador (2 GB) + build de Android + backend pesan; con 8 GB de RAM deja `MAX_E2E=1`.

Comandos útiles (todos los de `wi.sh`: `wi.sh <env> help`):

```sh
K=~/.local/share/autopilot-kit
$K/e2e.sh doctor                                  # qué herramientas E2E faltan
$K/wi.sh <env> check                              # avisos: herramientas, .env.autopilot.e2e, cuentas, E2E_API
$K/wi.sh <env> entorno <repo>                     # .env.autopilot (sin mostrar valores)
python3 $K/entorno.py <repo> --e2e                # .env.autopilot.e2e (ok / compartida / inseguro...)
$K/wi.sh <env> validar-e2e <clave>                # ¿el último Reporte E2E alcanza para aprobar?
$K/wi.sh <env> re-e2e <clave>                     # volver a probar en E2E (tras resolver un NO CERTIFICABLE)
$K/wi.sh <env> e2e-worktree <clave>               # copias E2E para probar tú mismo (y e2e-worktree-borrar)
```

## Reglas de trabajo

Fijadas en `SKILL.md`, se aplican sin que nadie las recuerde:

- **Puestos en paralelo, una tarea cada uno:** 1 coder (`in-progress`), 1 QA (`validando`) y, con `E2E=true`, 1 E2E (`probando-e2e`).
  `wi.sh` rechaza una segunda tarea en el mismo puesto.
- **Una rama por workitem:** `task-<numero>` / `bug-<numero>` desde `BASE_BRANCH`.
- **Nadie hace `push` ni `merge`** (ni `pull`, que mergea). Bloqueado por permiso/hook, no por instrucción.
- **QA y E2E no tocan el código:** prueban en sus propias copias (worktree); solo escriben pruebas temporales ahí; no commitean ni cambian de rama.
- **Nada se certifica sin probarlo:** sin compilación, tests y una prueba por criterio, el veredicto es `NO CERTIFICABLE` y la tarea queda en `stopped`. En E2E, un criterio sin capturas no está probado.
- **Nunca contra producción:** solo `.env.autopilot` / `.env.autopilot.e2e` que crea el humano (local o QA; E2E con base exclusiva), apps apuntadas al backend local, red cortada en navegador y emulador.
- **Todo queda escrito en la tarea:** repos modificados, notas del desarrollador, reporte de QA y reporte E2E (con capturas), por intento.
- **Los subagentes no usan el MCP de Azure.**
- **`bug-fix` tiene prioridad** sobre trabajo nuevo: siempre se toma primero.
- **3 intentos** de certificación (los rechazos de QA y de E2E suman juntos). Al cuarto, `stopped` con el historial.
- **`stopped` es para el humano**, con motivo escrito. Nunca inventar.

---

## Seguridad

- El kit **no contiene secretos**. Solo plantillas.
- `.gitignore` bloquea `*.env`, `*.secrets.env` y los `.log`.
- En los proyectos, `.env.autopilot` y `.env.autopilot.e2e` los crea solo el humano; ningún agente
  los crea, edita ni imprime sus valores. En modo un repo se ignoran en `.git/info/exclude`.
- Las cuentas de prueba del E2E son solo de QA y nunca se escriben en reportes ni capturas.
- El PAT **nunca** se hardcodea: va en variable de entorno o en `*.secrets.env`.
