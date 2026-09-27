---
name: Notion Autopilot
description: Sistema autonomo de desarrollo con tablero Notion. Usar cuando el usuario mencione el tablero de tareas, autonomous dev board, notion-autopilot, /autopilot, o pida trabajo autonomo sobre tareas en Notion. NO usar en proyectos que no tengan un archivo notion-autopilot.env.
slash: true
---

# Sistema Autónomo de Desarrollo (Notion Autopilot)

Sistema donde un **watcher** vigila un tablero de Notion y delega tareas a subagentes.

## Cuándo usar esta skill

Solo si el proyecto tiene un archivo `notion-autopilot.env` en la raíz o en `notion-autopilot/`.
Si no existe, este proyecto **no participa** del sistema. No preguntes, no asumas, no la busques.

## activating

Source: `notion-autopilot.env` (OBLIGATORIO antes de hacer nada)
Script: `~/.config/opencode/skills/notion-autopilot/watcher.sh`

```sh
cd <PROYECTO> && ~/.config/opencode/skills/notion-autopilot/watcher.sh
```

El watcher es **bloqueante y de un solo disparo**: se lanza, espera, y cuando detecta
algo accionable imprime el JSON y **sale con código 0**. Al salir, el control vuelve al agente.

### Por qué bloqueante y no demonio

El watcher corre en primer plano, en este mismo hilo, a proposito.

- **No consume tokens mientras espera.** No hay turnos de modelo mientras la llamada de shell
  no retorna. El proceso bash duerme entre polling y no genera nada.
- **No hay sesion duplicada.** Si corriera como demonio (`setsid`), cada deteccion abriria su
  propia sesion de OpenCode con tokens aparte. El usuario rechazo explicitamente ese modelo.
- **El despertar es la propia salida del script.** Cuando el watcher detecta algo, imprime el
  JSON y termina; esa llamada de shell retorna y el turno se reanuda. No hay polling paralelo
  ni temporizadores externos.

**LIMITACION CONOCIDA:** al correr en primer plano, el watcher muere si el turno se cierra o
el usuario cierra OpenCode. No sobrevive a la ausencia del usuario. Es el trade-off
aceptado a cambio de no gastar tokens en una sesion paralela.

## REGLA DE ORO: NUNCA DEJAR EL WATCHER PARADO

Esta es la regla que mas importa, y es la que mas veces se olvida.

1. **El watcher se relanza SIEMPRE al terminar cada tarea.** No importa como termino:
   `Done`, `QA`, `Bug Fix` o `Stopped`. Siempre vuelve al paso 1.
2. **Si no hay tareas, el watcher sigue esperando.** No lo abandones por no haber nada que hacer.
   El proposito es exactamente ese: esperar sin gastar tokens hasta que haya trabajo.
3. **No cierres el turno sin un watcher corriendo.** Si vas a responder al usuario o terminar
   el turno, deja un watcher activo en primer plano o en su equivalente bloqueante.
4. **Nunca inventes que el sistema esta vigilando si no lo esta.** Si el watcher no esta corriendo,
   dilo. La autonomia se sostiene sobre este proceso; si no corre, no hay autonomia.
5. **Si el usuario se ausenta y vuelve, el watcher ya no esta.** Relanzalo antes de actuar.

## Una sola via de escritura: REST API

Todo se escribe con `notion-set.sh` (REST API, token `ntn_`). **El MCP de Notion queda
solo para lectura y consulta humana: nunca escribas estados con el.**

El watcher es un script bash y solo puede usar REST. Si el agente escribiera con el MCP,
los dos estarian mutando los mismos campos por caminos distintos, sin que nadie lo notara.

```sh
N=~/.config/opencode/skills/notion-autopilot/notion-set.sh
E=<proyecto>/notion-autopilot.env

$N "$E" in-progress <page_id>
$N "$E" qa          <page_id>
$N "$E" done        <page_id>
$N "$E" new         <page_id>
$N "$E" stopped     <page_id> "<motivo>"
$N "$E" resultado   <page_id> "<rama | commit | resumen>"
$N "$E" log <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
$N "$E" query [database_id]
```

## El bucle

1. Lanza el watcher en primer plano. Espera. No hagas polling paralelo.
2. Cuando retorna con `elegida` != null, toma **solo esa** tarea.
3. Marca la tarea `In Progress` en Notion.
4. Crea la rama `task/<slug>` desde la rama principal. Nunca trabajes en la principal.
5. Lanza un subagente `autopilot-worker` con la tarea.
6. Verifica el resultado:
   - Hay commits en la rama y el subagente reporta éxito → `QA` + rama y commit en "Resultado"
   - No hay commits, o depende de algo sin mergear, o falta información → `Stopped` + motivo
7. Vuelve al paso 1. El watcher se relanza.

## La maquina de estados

```
New ──> In Progress ──> QA ──> Validando ──┬──> Done
                          ↑       │         │
                          │       ↓         │
                          └── Bug Fix ──────┘
                                  │
                                  └── Intento >= 3 ──> Stopped
```

| Estado | Significado | Quien actua |
|---|---|---|
| `New` | Pendiente | — |
| `In Progress` | El worker esta trabajando. Maximo 1. | `autopilot-worker` |
| `QA` | El worker termino y commiteo. Cola de certificacion. | — |
| `Validando` | El reviewer esta examinando. Maximo 1. | `qa-reviewer` |
| `Bug Fix` | QA fallo. Hay que corregir. **Se toma antes que cualquier otra cosa.** | `autopilot-worker` |
| `Stopped` | No se pudo. Requiere humano, con motivo escrito. | — |
| `Done` | **Certificado por QA.** No significa mergeado: el merge lo hace el humano cuando quiera. | — |

Propiedades ademas de las basicas: `Intento` (number), `Feedback de QA` (text),
`Rama` (text, donde trabaja la tarea).

## Las 3 acciones que puede devolver el watcher

| accion | Que hacer |
|---|---|
| `desarrollar-bugfix` | Lanzar `autopilot-worker` con el `Feedback de QA` en el prompt. Estado: `In Progress`. |
| `desarrollar` | Lanzar `autopilot-worker` con la tarea nueva. Estado: `In Progress`. |
| `certificar` | Lanzar `qa-reviewer` con los criterios. Estado: `Validando`, e `Intento` +1. |

Prioridad de seleccion en el watcher: `Bug Fix` > `QA` > `New`.
Asi el fix nunca queda aplazado por trabajo nuevo.

## El ciclo de certificacion

1. Hay una tarea en `QA` y el watcher devuelve `certificar`
2. Ponla en `Validando` e incrementa `Intento`: `notion-set.sh certificar <id> <nuevo>`
3. Lanza `qa-reviewer` con la tarea, sus criterios, la rama y el numero de intento
4. Lee el veredicto:
   - `APROBADO` → `notion-set.sh aprobar <id>` (va a `Done`)
   - `RECHAZADO` → si `Intento >= 3` → `Stopped` con el historial de los intentos
     → si no → `notion-set.sh rechazar <id> "<motivos>"` (va a `Bug Fix`)
5. En `Bug Fix`, el watcher devuelve `desarrollar-bugfix`. El worker arregla SOLO el feedback.
6. Vuelve al paso 1. Se repite hasta 3 intentos.

## Los dos agentes

**`autopilot-worker`** — desarrolla. Puede editar y commitear. Le bloquean `git push` y `git merge`.
Si viene de `Bug Fix`, solo arregla lo que dice el feedback.

**`qa-reviewer`** — certifica. **No puede editar ni commitear** (permiso `deny`, no instruccion).
Contrasta el diff de la rama contra cada punto del criterio de aceptacion, uno por uno.
Debe marcar `NO VERIFICABLE` lo que no pueda comprobar, en vez de aprobarlo.

## Propiedades de la base de datos

`Name`, `Estado` (select), `Prioridad` (select), `Descripción` (rich_text),
`Criterio de aceptación` (rich_text), `Repo` (rich_text), `Resultado` (rich_text),
`Motivo de stopped` (rich_text), `Actualizado` (last_edited_time)

## Log de actividad

Cada evento se registra en la base de datos de log: `Origen` (`watcher`|`agente`|`sistema`),
`Tipo` (`deteccion`|`delegacion`|`QA`|`Stopped`|`recuperacion`|`error`|`nota`),
más `Tarea`, `Rama`, `Commit`, `Detalle`.

## Lo que NUNCA debes hacer

- **Dejar el watcher sin correr al terminar una tarea.** Relanzalo siempre, incluso sin trabajo pendiente.
- **Abandonar el watcher porque "no hay nada que hacer".** No gastar tokens esperando es el comportamiento correcto.
- **Cerrar el turno sin un watcher activo.** O relanzalo, o dile al usuario que el sistema ya no esta vigilando.
- **Afirmar que el sistema sigue vigilando si el watcher no corre.** No inventes autonomia.
- Trabajar en la rama principal. Todo va en `task/<slug>`.
- `git push`. Está bloqueado por permiso, pero tampoco lo intentes.
- `git merge`. **El merge lo hace el humano, siempre.**
- Procesar más de una tarea a la vez.
- Marcar `QA` sin commits verificables en la rama.
- Marcar `Stopped` sin escribir el motivo.
- Inventar que hiciste algo que no hiciste.
