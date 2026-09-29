# dotenvs

Kit portable de un **sistema de desarrollo autónomo** para **OpenCode y Claude Code**, sobre un
board de workitems hecho de **carpetas y archivos Markdown**. Sin Notion, sin tokens, sin red.
Opcionalmente, conectado a Azure DevOps con el MCP oficial de Microsoft (sin permisos de admin).

Dos subsistemas independientes, ambos opt-in por proyecto:

| Comando | Qué hace | Consume tokens |
|---|---|---|
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
│   ├── azure-sync.py           # importador aditivo de Azure DevOps
│   ├── git-guard.sh            # bloquea push/merge (hooks de Claude Code)
│   └── ado-mcp.sh              # lanza el MCP de Azure DevOps con tu PAT
├── skills/                     # -> carpeta de skills de cada cliente
│   ├── autopilot/SKILL.md      # reglas, maquina de estados, arranque por cliente
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
| `/autopilot`, `/azure-sync` | comandos en `~/.config/opencode/commands/` | las propias skills |
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
- **Siempre desde `base-branch`** (`BASE_BRANCH` en `autopilot.env`). Si no existe, la tarea
  pasa a `stopped`: no se inventa otra base.
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

Cada proyecto decide si participa. **Sin `autopilot.env`, el proyecto no entra.**

```sh
./install.sh --init /mi/proyecto
```

- crea `autopilot.env`, `azure-sync.env` y el board `.workitems/`
- agrega `.workitems/`, `*.secrets.env` y `.claude/settings.local.json` al `.gitignore`
- prohíbe push/merge también al agente principal del proyecto (en cada cliente instalado)
- avisa si `base-branch` no existe

**Después, commiteá esos cambios en `base-branch`** (`.gitignore`, `opencode.json`, los `.env`).
Mientras haya cambios sin commitear en archivos rastreados, `wi.sh rama` no cambia de rama y
la tarea pasa a `stopped`.

`autopilot.env`:

| Variable | Default | Qué es |
|---|---|---|
| `REPO_PATH` | carpeta del `.env` | Ruta del repo |
| `BASE_BRANCH` | `base-branch` | Rama desde la que nacen las ramas de los workitems |
| `WORKITEMS_DIR` | `$REPO_PATH/.workitems` | Carpeta del board |
| `POLL_INTERVAL` | `5` | Segundos entre lecturas del board |

No tiene secretos: se puede versionar. El PAT para `azure-sync.py` va en
`azure-sync.secrets.env` (gitignored).

---

## Uso

```sh
/autopilot     # arranca el bucle: espera tareas y las trabaja
/azure-sync    # importa Work Items de Azure al board
```

Crear una tarea a mano:

```sh
~/.local/share/autopilot-kit/wi.sh ./autopilot.env \
  add-task bug 140123 High "Login falla con Google" "descripcion" "criterio"
```

(o escribir el `.md` directamente en `.workitems/new/` respetando el nombre `<tipo>-<numero>-*.md`).

En un proyecto sin el `.env`, ambos comandos dicen que el proyecto no participa
y no hacen nada.

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

## Reglas de trabajo

Fijadas en `SKILL.md`, se aplican sin que nadie las recuerde:

- **Una sola tarea a la vez.** Máximo 1 en `in-progress`.
- **Una rama por workitem:** `task-<numero>` / `bug-<numero>` desde `base-branch`.
- **Nadie hace `push` ni `merge`** (ni `pull`, que mergea). Bloqueado por permiso/hook, no por instrucción.
- **QA solo lee.** No puede editar, commitear ni cambiar de rama.
- **Los subagentes no usan el MCP de Azure.**
- **`bug-fix` tiene prioridad** sobre trabajo nuevo: siempre se toma primero.
- **3 intentos** de certificación. Al cuarto, `stopped` con el historial.
- **`stopped` es para el humano**, con motivo escrito. Nunca inventar.

---

## Seguridad

- El kit **no contiene secretos**. Solo plantillas.
- `.gitignore` bloquea `*.env`, `*.secrets.env` y los `.log`.
- El PAT **nunca** se hardcodea: va en variable de entorno o en `*.secrets.env`.
