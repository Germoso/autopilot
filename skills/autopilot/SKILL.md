---
name: autopilot
description: Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown. Arranca el watcher y trabaja las tareas con subagentes, una rama por workitem desde la rama base del proyecto (BASE_BRANCH), sin push ni merge. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.
---

# Sistema Autónomo de Desarrollo (Autopilot)

Sistema donde un **watcher** vigila un board de workitems (carpetas + `.md`) y delega
tareas a subagentes.

## Cuándo usar esta skill

Solo si el proyecto tiene un archivo `autopilot.env` en la raíz.
Si no existe, este proyecto **no participa** del sistema. No preguntes, no asumas, no la busques.

## El board

```
.workitems/                     # WORKITEMS_DIR; NO esta en git (va en .gitignore)
├── new/          bug-140123-login-falla.md
├── in-progress/
├── qa/
├── validando/
├── bug-fix/
├── stopped/
├── done/
└── log.md                      # log de actividad, solo se agregan filas
```

- **El estado de una tarea es la carpeta donde está.** No hay campo de estado.
- **Clave de la tarea = `<tipo>-<numero>`** (`task-123`, `bug-140123`). Es también el
  **nombre de su rama**. Es lo que se le pasa a `wi.sh`.
- Cada archivo tiene frontmatter (`id`, `tipo`, `prioridad`, `intento`, `rama`, `repo`,
  `origen`, `actualizado`) y las secciones `## Descripción`, `## Criterio de aceptación`,
  `## Feedback de QA` (historial por intento), `## Resultado`, `## Motivo de stopped`.
- El board **no va en git**: si estuviera versionado, al cambiar de rama cambiaría el tablero.

## Arranque

Los scripts del sistema estan en `~/.local/share/autopilot-kit/` (en adelante `$K`).

1. Verifica que existe `autopilot.env` en la carpeta abierta (un repo, o la carpeta padre de un
   workspace con varios repos). Si no existe, para y dile al usuario que no participa y que se
   prepara con `/autopilot-init`. No lo busques en otro sitio ni lo adivines.
2. Lanza el watcher. **Cómo** depende del cliente en el que estás corriendo:

   | Cliente | Cómo lanzarlo |
   |---|---|
   | **Claude Code** | Tool Bash con `run_in_background: true`: `$K/watcher.sh ./autopilot.env`. Claude Code corta los comandos en primer plano a los 10 minutos; en segundo plano no hay límite y **te re-invoca cuando el watcher termina**. Mientras tanto no hagas nada ni sondees su salida: termina el turno diciendo que el watcher está vigilando. |
   | **OpenCode** | En primer plano, con el timeout más largo que permita el tool de shell: `$K/watcher.sh ./autopilot.env`. |

3. Cuando el watcher retorna, lee el JSON de su salida y sigue **El bucle** (más abajo).
4. Al terminar cada tarea, vuelve al paso 2.

### Por qué el watcher y no polling del agente

- **No consume tokens mientras espera.** El proceso duerme entre lecturas del board; no hay
  turnos de modelo hasta que retorna.
- **No hay sesión duplicada.** No se usa `opencode run` ni `claude -p` desde un demonio, que
  abrirían sesiones con tokens aparte. El usuario rechazó explícitamente ese modelo.
- **El despertar es la propia salida del script.** Cuando detecta algo, imprime el JSON y termina.

**LIMITACIÓN CONOCIDA:** el watcher vive dentro de la sesión. Si el usuario cierra OpenCode o
Claude Code, deja de vigilar. No sobrevive a la ausencia del usuario.

## REGLA DE ORO: NUNCA DEJAR EL WATCHER PARADO

1. **El watcher se relanza SIEMPRE al terminar cada tarea.** No importa cómo terminó:
   `done`, `qa`, `bug-fix` o `stopped`. Siempre vuelve al paso 1.
2. **Si no hay tareas, el watcher sigue esperando.** No lo abandones por no haber nada que hacer.
3. **No cierres el turno sin un watcher corriendo.** O lo relanzas, o le dices al usuario que
   el sistema ya no está vigilando. (En Claude Code, "corriendo" = lanzado en segundo plano.)
4. **Nunca inventes que el sistema está vigilando si no lo está.**
5. **Si el usuario se ausenta y vuelve, el watcher ya no está.** Relánzalo antes de actuar.

## REGLAS DE GIT (sin excepciones)

- **Una rama independiente por workitem.** Nombre: `task-<numero>` o `bug-<numero>`.
  Ejemplo: `bug-140123`.
- **Toda rama nueva sale de la rama base de SU repo**, definida en `autopilot.env`:
  `BASE_BRANCH=<rama>` si es un repo, o `REPO.<carpeta>=<rama>` por repo si es un workspace.
  Nunca de otra.
- **Workspace (varios repos):** cada tarea dice su repo (`repo:` en el frontmatter) y su rama se
  crea **dentro de ese repo**. Todo lo de git de esa tarea se hace ahí (`git -C <REPO> ...`).
- El watcher devuelve, dentro de `tarea`, **`repo_path`** (en este documento `<REPO>`) y
  **`base`** (`<BASE>`). Si trae `repo_error`, la tarea no tiene un repo válido: `stopped` con ese
  motivo.
- **La rama se prepara SOLO con `wi.sh rama`**, que valida todo y, si algo falla, pasa la tarea
  a `stopped` con el motivo:
  - `wi.sh rama <clave> nueva` → crea `<clave>` desde `<BASE>`. Si la rama ya existe, si
    la rama base está vacía o no existe, **no inventa nada**: `stopped`.
  - `wi.sh rama <clave> existente` → vuelve a la rama de la tarea (ciclo de Bug Fix).
- **NUNCA `git push`. NUNCA `git merge`.** Bloqueados por permiso. El merge lo hace el humano.
- Tampoco `git rebase`, ni borrar ramas, ni `reset --hard`.
- El tipo de la rama (`task`/`bug`) es el tipo del workitem, **no** el estado `bug-fix`:
  un `task-123` rechazado por QA se sigue corrigiendo en `task-123`.

## Una sola vía de escritura: wi.sh

Todo cambio al board se hace con `wi.sh`. **No edites ni muevas los `.md` a mano desde el
agente**: el watcher y el agente usarían caminos distintos. (El humano sí puede moverlos
o editarlos: el watcher lo detecta en la siguiente lectura.)

```sh
W=~/.local/share/autopilot-kit/wi.sh
E=<proyecto>/autopilot.env

$W "$E" rama        <clave> nueva|existente
$W "$E" in-progress <clave>
$W "$E" qa          <clave>
$W "$E" certificar  <clave> <intento_nuevo>   # qa -> validando
$W "$E" aprobar     <clave>                   # validando -> done
$W "$E" rechazar    <clave> "<motivos>"       # validando -> bug-fix
$W "$E" new         <clave>
$W "$E" stopped     <clave> "<motivo>"
$W "$E" resultado   <clave> "<rama | commit | resumen>"
$W "$E" add-task    <task|bug> <numero> <prioridad> "<titulo>" "<descripcion>" "<criterio>" [repo]   # repo obligatorio en workspace
$W "$E" log <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
$W "$E" query [estado]
```

## El bucle

1. Lanza el watcher como dice **Arranque** (segundo plano en Claude Code, primer plano en OpenCode). No hagas polling paralelo.
2. Cuando retorna con `accion` != `idle`, toma **solo** `tarea` (su `id` es la clave).
3. Según la acción:
   - `desarrollar` → `wi.sh rama <clave> nueva` y luego `wi.sh in-progress <clave>`.
   - `desarrollar-bugfix` → `wi.sh rama <clave> existente` y luego `wi.sh in-progress <clave>`.
   - `certificar` → ver el ciclo de certificación (no cambia de rama).
   Si `wi.sh rama` falla, la tarea ya quedó en `stopped`: relanza el watcher.
4. Lanza un subagente `autopilot-worker` con la tarea, `<REPO>` (dónde trabajar), la rama y
   `<BASE>` (y el `Feedback de QA` si es bugfix).
5. Verifica el resultado:
   - Hay commits nuevos en la rama (`git -C <REPO> log <BASE>..<clave>`) y el subagente reporta
     éxito → `wi.sh qa <clave>` + `wi.sh resultado <clave> "<rama> @ <commit> — <resumen>"`
   - No hay commits, depende de algo que no está en `<BASE>`, o falta información
     → `wi.sh stopped <clave> "<motivo>"`
6. Registra el evento con `wi.sh log`.
7. Vuelve al paso 1. El watcher se relanza.

## La máquina de estados

```
new ──> in-progress ──> qa ──> validando ──┬──> done
                          ↑       │         │
                          │       ↓         │
                          └── bug-fix ──────┘
                                  │
                                  └── intento >= 3 ──> stopped
```

| Carpeta | Significado | Quién actúa |
|---|---|---|
| `new` | Pendiente | — |
| `in-progress` | El worker está trabajando. Máximo 1. | `autopilot-worker` |
| `qa` | El worker terminó y commiteó. Cola de certificación. | — |
| `validando` | El reviewer está examinando. Máximo 1. | `qa-reviewer` |
| `bug-fix` | QA falló. Hay que corregir. **Se toma antes que cualquier otra cosa.** | `autopilot-worker` |
| `stopped` | No se pudo. Requiere humano, con motivo escrito. | — |
| `done` | **Certificado por QA.** No significa mergeado: el merge lo hace el humano. | — |

## Las 3 acciones que puede devolver el watcher

| accion | Qué hacer |
|---|---|
| `desarrollar-bugfix` | `rama existente`, lanzar `autopilot-worker` con el `Feedback de QA`. Estado: `in-progress`. |
| `desarrollar` | `rama nueva`, lanzar `autopilot-worker` con la tarea. Estado: `in-progress`. |
| `certificar` | Lanzar `qa-reviewer` con los criterios. Estado: `validando`, e `intento` +1. |

Prioridad de selección en el watcher: `bug-fix` > `qa` > `new` (por prioridad, luego número).

## El ciclo de certificación

1. Hay una tarea en `qa` y el watcher devuelve `certificar`
2. `wi.sh certificar <clave> <intento+1>`
3. Lanza `qa-reviewer` con la tarea, sus criterios, `<REPO>`, la rama, `<BASE>` y el número de
   intento. El reviewer compara con `git -C <REPO> diff <BASE>...<clave>`.
4. Lee el veredicto:
   - `APROBADO` → `wi.sh aprobar <clave>` (va a `done`)
   - `RECHAZADO` → si `intento >= 3` → `wi.sh stopped <clave> "<historial de los intentos>"`
     → si no → `wi.sh rechazar <clave> "<motivos>"` (va a `bug-fix`)
5. En `bug-fix`, el watcher devuelve `desarrollar-bugfix`. El worker arregla SOLO el feedback,
   en la misma rama.
6. Vuelve al paso 1. Se repite hasta 3 intentos.

## Los dos agentes

**`autopilot-worker`** — desarrolla. Puede editar y commitear en la rama de la tarea.
Le bloquean `git push`, `git merge`, `git pull`, `git rebase`, cambiar/crear/borrar ramas y `reset --hard`.

**`qa-reviewer`** — certifica. **No puede editar, commitear ni cambiar de rama.**

Los bloqueos son reales, no instrucciones: en OpenCode son permisos `deny` del agente; en
Claude Code, un hook `PreToolUse` (`$K/git-guard.sh`) que cancela el comando. En el proyecto,
`install.sh --init` además prohíbe push/merge al agente principal (el orquestador).

Ninguno de los dos subagentes usa el MCP de Azure DevOps: si hay que escribir en Azure, lo hace
el orquestador.
Contrasta el diff contra cada punto del criterio de aceptación, uno por uno.
Debe marcar `NO VERIFICABLE` lo que no pueda comprobar, en vez de aprobarlo.

## Log de actividad

`log.md` es una tabla a la que solo se agregan filas: `Hora`, `Origen`
(`watcher`|`agente`|`sistema`), `Tipo` (`deteccion`|`delegacion`|`QA`|`Stopped`|`recuperacion`|`error`|`nota`),
`Tarea`, `Rama`, `Commit`, `Evento`, `Detalle`.

## Lo que NUNCA debes hacer

- **Dejar el watcher sin correr al terminar una tarea.** Relánzalo siempre.
- **Cerrar el turno sin un watcher activo** sin decírselo al usuario.
- **Afirmar que el sistema sigue vigilando si el watcher no corre.**
- `git push` o `git merge`. **El merge lo hace el humano, siempre.**
- Crear una rama desde otra que no sea `<BASE>`, o con otro nombre que `task-<n>`/`bug-<n>`.
- Trabajar en `<BASE>` directamente.
- Procesar más de una tarea a la vez.
- Marcar `qa` sin commits verificables en la rama.
- Marcar `stopped` sin escribir el motivo.
- Editar o mover los `.md` del board sin `wi.sh`.
- Inventar que hiciste algo que no hiciste.
