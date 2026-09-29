# dotenvs

Kit portable de un **sistema de desarrollo autónomo** para **OpenCode y Claude Code**, sobre un
board de workitems hecho de **carpetas y archivos Markdown**. Sin Notion, sin tokens, sin red.
Opcionalmente, conectado a Azure DevOps con el MCP oficial de Microsoft (sin permisos de admin).

Dos subsistemas independientes, ambos opt-in por proyecto:

| Comando | Qué hace | Consume tokens |
|---|---|---|
| `/autopilot-init` | Prepara la carpeta abierta: un repo o un **workspace con varios repos**. Detecta ramas y proyectos de Azure, pregunta la rama base de cada repo y crea la config y el board. | sí (poco) |
| `/autopilot` | Detecta tareas en el board y las trabaja con subagentes, cada una en su rama. Ciclo completo: `new` → `in-progress` → `qa` → `validando` → `done`, con `bug-fix` hasta 3 intentos. | sí |
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
│   └── ado-mcp.sh              # lanza el MCP de Azure DevOps con tu PAT
├── skills/                     # -> carpeta de skills de cada cliente
│   ├── autopilot/SKILL.md      # reglas, maquina de estados, arranque por cliente
│   ├── autopilot-init/SKILL.md # /autopilot-init
│   └── azure-sync/SKILL.md
├── agents/                     # fuente unica de los subagentes
│   ├── autopilot-worker.md
│   └── qa-reviewer.md
├── clients/render.py           # genera agentes/comandos/guardas para cada cliente
└── examples/proyecto/          # autopilot.env, azure-sync.env
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
    ├── bug-fix/
    ├── stopped/
    ├── done/
    └── log.md                    # log de actividad (solo se agregan filas)
```

- **El estado de una tarea es la carpeta donde está.** Cambiar de estado es mover el archivo.
  Podés mover tareas a mano (explorador, VS Code, Obsidian); el watcher lo ve en segundos.
- **El nombre del archivo es `<tipo>-<numero>-<slug>.md`.** `<tipo>-<numero>` es la clave de
  la tarea y **el nombre de su rama**.
- **El board no está en git.** Si lo estuviera, cada vez que el worker cambia de rama el
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
- Si el repo tiene cambios sin commitear en archivos rastreados, no se cambia de rama: `stopped`.
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

### Desinstalar

```sh
./install.sh --uninstall
```

Quita scripts, skills, agentes, comandos y el registro del MCP. Quedan intactos los proyectos
(`.env`, board, guardas) y tu PAT en `~/.config/autopilot-kit/`.

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
- avisa si falta alguna rama base, si no existe, o si un repo tiene cambios sin commitear

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
- Los puestos son globales: **un coder y un QA** para todo el workspace (ver *Dos puestos en paralelo*).

`autopilot.env`:

| Variable | Default | Qué es |
|---|---|---|
| `REPO_PATH` | carpeta del `.env` | Ruta del repo |
| `BASE_BRANCH` | **obligatoria** (un repo) | Rama desde la que nacen las ramas de los workitems (`dev`, `main`...) |
| `REPO.<carpeta>` | **una por repo** (workspace) | Rama base de ese repo. Si hay alguna, es un workspace |
| `WORKITEMS_DIR` | `$REPO_PATH/.workitems` | Carpeta del board |
| `POLL_INTERVAL` | `5` | Segundos entre lecturas del board |

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

El autopilot le pasa las imágenes y fotogramas al worker y al QA (`tarea.adjuntos`).

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

## Dos puestos en paralelo

| Puesto | Agente | Toma de | Mientras trabaja | Máximo |
|---|---|---|---|---|
| coder | `autopilot-worker` | `bug-fix` > `new` | `in-progress` | 1 |
| QA | `qa-reviewer` | `qa` | `validando` | 1 |

Mientras el coder desarrolla una tarea, el QA puede estar certificando otra.

- **Claude Code:** los dos subagentes corren en segundo plano; Claude Code avisa al agente
  principal cuando terminan.
- **OpenCode:** cada puesto corre como **su propia sesión** de OpenCode, lanzada por la API del
  servicio local (`oc_sesion.py`). Las ves en tu lista de sesiones y podés mirarlas en vivo. El
  watcher avisa cuando una termina. Si cerrás OpenCode, esas sesiones siguen; al volver,
  `/autopilot` las retoma.
- **El QA trabaja en su propia copia del repo** (`git worktree` en `~/.cache/autopilot-kit/qa/`,
  en la punta de la rama de la tarea): puede compilar y correr tests o la app sin pisar al coder.
  Se borra al dar el veredicto.

### Qué queda escrito en cada tarea

- **`## Notas del desarrollador`** (por intento): qué se hizo y por qué, archivos cambiados,
  decisiones, cómo probarlo, pruebas que corrió, riesgos y pendientes.
- **`## Reporte de QA`** (por intento): cada criterio (CUMPLE / NO CUMPLE / NO VERIFICABLE con
  evidencia), **qué probó** (comandos y resultados), **cómo verificarlo manualmente de punta a
  punta** (preparación, pasos, resultado esperado, casos borde) y **puntos a tomar en cuenta**
  (regresiones, migraciones, configuración, datos...).

## Reglas de trabajo

Fijadas en `SKILL.md`, se aplican sin que nadie las recuerde:

- **Dos puestos en paralelo, una tarea cada uno:** 1 coder (`in-progress`) y 1 QA (`validando`).
  `wi.sh` rechaza una segunda tarea en el mismo puesto.
- **Una rama por workitem:** `task-<numero>` / `bug-<numero>` desde `BASE_BRANCH`.
- **Nadie hace `push` ni `merge`** (ni `pull`, que mergea). Bloqueado por permiso/hook, no por instrucción.
- **QA no toca el código:** prueba en su propia copia (worktree); no edita, no commitea, no cambia de rama.
- **Todo queda escrito en la tarea:** notas del desarrollador y reporte de QA, por intento.
- **Los subagentes no usan el MCP de Azure.**
- **`bug-fix` tiene prioridad** sobre trabajo nuevo: siempre se toma primero.
- **3 intentos** de certificación. Al cuarto, `stopped` con el historial.
- **`stopped` es para el humano**, con motivo escrito. Nunca inventar.

---

## Seguridad

- El kit **no contiene secretos**. Solo plantillas.
- `.gitignore` bloquea `*.env`, `*.secrets.env` y los `.log`.
- El PAT **nunca** se hardcodea: va en variable de entorno o en `*.secrets.env`.
