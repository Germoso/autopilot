---
name: autopilot
description: Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown. Arranca el watcher y trabaja las tareas con dos subagentes en paralelo (un coder y un QA, una tarea cada uno), una rama por workitem desde la rama base del proyecto (BASE_BRANCH), sin push ni merge. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.
---

# Sistema Autónomo de Desarrollo (Autopilot)

Sistema donde un **watcher** vigila un board de workitems (carpetas + `.md`) y tú, el agente
principal (orquestador), delegas en **dos puestos que trabajan en paralelo**:

| Puesto | Agente | Toma de | Estado mientras trabaja | Máximo |
|---|---|---|---|---|
| **coder** | `coder` | `bug-fix` > `new` | `in-progress` | `MAX_CODERS` |
| **qa** | `qa-reviewer` | `qa` | `validando` | `MAX_QA` |

**Capacidad** (en `autopilot.env`): `PARALLEL=false` (defecto) → 1 coder y 1 QA. `PARALLEL=true` →
hasta `MAX_CODERS` y `MAX_QA` (defecto 2 y 2) a la vez, **cada uno con un workitem distinto**.
`wi.sh` rechaza superar el máximo. En un workspace el límite es global, no por repo.

**Cada coder trabaja en su propia copia** (`git worktree` en `~/.cache/autopilot-kit/coder/<repo>-<clave>`),
con su rama. La copia principal del repo (la del humano) nunca cambia de rama. Dos workitems en
paralelo **no tocan el mismo archivo**: el primero que lo edita lo reserva (`wi.sh reservar`, y en
Claude Code automáticamente al editar); el otro se pone **en espera** hasta que el primero termine.

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
├── reviewed/                   # done que el humano ya revisó (lo mueve el humano)
└── log.md                      # log de actividad, solo se agregan filas
```

- **El estado de una tarea es la carpeta donde está.** No hay campo de estado.
- **Clave de la tarea = `<tipo>-<numero>`** (`task-123`, `bug-140123`). Es también el
  **nombre de su rama**. Es lo que se le pasa a `wi.sh`.
- Cada archivo tiene frontmatter (`id`, `tipo`, `prioridad`, `intento`, `rama`, `repo`,
  `origen`, `sesion`, `actualizado`) y las secciones `## Descripción`, `## Criterio de aceptación`,
  `## Adjuntos`, `## Notas del desarrollador` y `## Reporte de QA` (por intento),
  `## Feedback de QA`, `## Resultado`, `## Motivo de stopped`.
- El board **no va en git**: si estuviera versionado, al cambiar de rama cambiaría el tablero.

## Arranque

Los scripts del sistema están en `~/.local/share/autopilot-kit/` (en adelante `$K`); `W` y `E`
son `wi.sh` y el `autopilot.env` (ver *Una sola vía de escritura*).

1. Verifica que existe `autopilot.env` en la carpeta abierta (un repo, o la carpeta padre de un
   workspace con varios repos). Si no existe, para y dile al usuario que no participa y que se
   prepara con `/autopilot-init`. No lo busques en otro sitio ni lo adivines.
2. Lanza el watcher **con `--inicio`** (solo esta primera vez: recupera tareas que quedaron en un
   puesto sin agente de una sesión anterior): `$K/watcher.sh ./autopilot.env --inicio`.
   Todos los relanzamientos posteriores van **sin** `--inicio`.
3. Sigue **El bucle**.

### Cómo se lanza cada cosa según el cliente

| | **Claude Code** | **OpenCode** |
|---|---|---|
| Watcher | Bash con `run_in_background: true`. Te re-invoca cuando retorna. Mientras, no sondees su salida. | Bash en primer plano, con el timeout más largo posible. |
| Subagente de un puesto | Tool Agent con `subagent_type: coder` o `qa-reviewer`. Corren **en segundo plano** (definido en el agente): no los esperes; Claude Code te avisa cuando terminan. | **Sesión propia** vía API: `python3 $K/oc_sesion.py lanzar <agente> <carpeta abierta> "<clave>: <puesto>" - --adjunto <img>...` con el encargo por stdin. Devuelve `{"sesion": "ses_..."}`: regístralo con `$W "$E" sesion <clave> <ses>`. No espera. |
| Fin de un subagente | Llega como aviso de tarea terminada, con su respuesta. | El watcher lo devuelve en `terminadas`; la respuesta se lee con `python3 $K/oc_sesion.py resultado <ses>`. |
| Imágenes | Pásale las rutas en el encargo: las abre con Read. | Van como `--adjunto` (las ve directo) **y** también listadas en el encargo. |

Las sesiones de OpenCode se ven en su lista de sesiones: el usuario puede abrirlas y mirarlas en vivo.

### Por qué el watcher y no polling del agente

- **No consume tokens mientras espera.** El proceso duerme entre lecturas del board; no hay
  turnos de modelo hasta que retorna.
- **El despertar es la propia salida del script** (o, en Claude Code, el aviso de un subagente).
- **Un solo watcher a la vez.** Llévalo en la cuenta: si lo lanzaste y no retornó, sigue corriendo.

**LIMITACIÓN CONOCIDA:** el watcher vive dentro de la sesión. Si el usuario cierra el cliente, deja
de vigilar. En OpenCode las sesiones de los puestos sí siguen; al volver, `--inicio` las respeta
(no las marca huérfanas) y el watcher avisa cuando terminan.

## REGLA DE ORO: NUNCA DEJAR EL WATCHER PARADO

1. **El watcher se relanza SIEMPRE que retorna**, después de atender lo que trajo. Si ya hay
   uno corriendo (Claude Code, segundo plano), no lances otro.
2. **Si no hay tareas, el watcher sigue esperando.** No lo abandones por no haber nada que hacer.
3. **No cierres el turno sin un watcher corriendo.** O lo relanzas, o le dices al usuario que
   el sistema ya no está vigilando. (En Claude Code, "corriendo" = lanzado en segundo plano.)
4. **Nunca inventes que el sistema está vigilando si no lo está.**
5. **Si el usuario se ausenta y vuelve, el watcher ya no está.** Relánzalo antes de actuar.

## NUNCA CONTRA PRODUCCIÓN (por encima de todo)

- Nadie (tú, el coder ni el QA) ejecuta nada contra producción.
- Lo que se conecta a una base de datos o API (tests de integración/e2e, levantar un backend,
  migraciones, seeds, scripts, HTTP) corre **solo** con
  `$K/aenv.sh <repo o worktree> -- <comando>`, que usa el **`.env.autopilot` que el humano creó** en
  el repo y verifica que todo apunte a local o QA (la BD debe decir "qa" en su nombre). Los comandos
  directos están bloqueados por hook/permisos.
- Nadie crea, edita ni copia `.env*`. Nadie cambia la URL de API de una app para probar.
- En cada encargo, incluye el estado de ambiente de los repos de la tarea:
  `$W "$E" entorno <clave>` (`ok` / `falta` / `inseguro` / `incompleto`, sin valores).
- Un agente que se detiene por **posible producción** (coder `STOPPED` o QA `NO CERTIFICABLE`) →
  `$W "$E" stopped <clave> "POSIBLE PRODUCCIÓN: <lo que vio>. RECOMENDACIÓN: <lo que propone>"`.
  No lo reintentes: lo resuelve el humano (creando o corrigiendo `.env.autopilot`).
- Tú nunca ejecutas nada contra ambientes.

## REGLAS DE GIT (sin excepciones)

- **Una rama independiente por workitem.** Nombre: `task-<numero>` o `bug-<numero>`.
  Ejemplo: `bug-140123`.
- **Toda rama nueva sale de la rama base de SU repo**, definida en `autopilot.env`:
  `BASE_BRANCH=<rama>` si es un repo, o `REPO.<carpeta>=<rama>` por repo si es un workspace.
  Nunca de otra.
- **Workspace (varios repos):** cada tarea dice su repo principal (`repo:`) y su rama se crea
  **dentro de ese repo**. Si la corrección requiere **otro repo del workspace**, el coder **no se
  detiene**: abre la **misma rama** allí con `wi.sh rama <clave> nueva --repo <carpeta>` (desde la
  base de ese repo) y queda registrado en `repos_extra:`. Desde ahí, todo lo de la tarea (ramas de
  bug-fix, verificación de commits, worktrees del QA) abarca todos sus repos (`tarea.repos`).
- El watcher devuelve, dentro de `tarea`, **`repo_path`** (en este documento `<REPO>`) y
  **`base`** (`<BASE>`). Si trae `repo_error`, la tarea no tiene un repo válido: `stopped` con ese
  motivo.
- **La rama se prepara SOLO con `wi.sh rama`**, que valida todo y, si algo falla, pasa la tarea
  a `stopped` con el motivo:
  - `wi.sh rama <clave> nueva` → crea `<clave>` desde `<BASE>`. Si la rama ya existe, si
    la rama base está vacía o no existe, **no inventa nada**: `stopped`.
  - `wi.sh rama <clave> existente` → vuelve a la rama de la tarea en **todos** sus repos (bug-fix).
  - `wi.sh rama <clave> nueva --repo <carpeta>` → la usa el **coder** para sumar otro repo. Si
    falla, la tarea **no** pasa a stopped: el error vuelve al coder.
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

$W "$E" rama        <clave> nueva|existente [--repo <carpeta>]
$W "$E" repos       <clave>                   # repos de la tarea (principal + extra) y worktrees del coder
$W "$E" reservar    <clave> <archivo>...      # reserva archivos para la tarea (coder)
$W "$E" solapes     <clave>                   # archivos que comparte con otras tareas activas
$W "$E" esperar     <clave> <otra>            # choco con <otra>: vuelve a la cola hasta que termine
$W "$E" coder-worktree-borrar <clave>          # (también mata los procesos que queden en esa copia)
python3 $K/vigia.py "$E" [--simular]           # vigilante a mano: qué mataría / qué está atascado
$W "$E" entorno     <clave|repo>              # .env.autopilot de sus repos: ok/falta/inseguro/incompleto
$W "$E" in-progress <clave>
$W "$E" qa          <clave>
$W "$E" certificar  <clave> <intento_nuevo>   # qa -> validando
$W "$E" aprobar     <clave>                   # validando -> done
$W "$E" rechazar    <clave> "<motivos>"       # validando -> bug-fix
$W "$E" new         <clave>
$W "$E" reviewed    <clave>                   # SOLO el humano: done -> reviewed
$W "$E" stopped     <clave> "<motivo>"
$W "$E" resultado   <clave> "<rama | commit | resumen>"
$W "$E" add-task    <task|bug> <numero> <prioridad> "<titulo>" "<descripcion>" "<criterio>" [repo]   # repo obligatorio en workspace
$W "$E" log <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
$W "$E" query [estado]
$W "$E" sesion      <clave> <ses_id>          # OpenCode: sesión que trabaja la tarea
$W "$E" notas-dev   <clave> -   <<'FIN'       # notas del coder (stdin)
$W "$E" reporte-qa  <clave> -   <<'FIN'       # reporte del QA (stdin)
$W "$E" qa-worktree <clave>                   # copia de trabajo del QA
$W "$E" qa-worktree-borrar <clave>
```

## El bucle

Hay tres eventos. Atiende cada uno y **relanza el watcher si no está corriendo**.

### A. El watcher retorna con `acciones` (trabajo para un puesto libre)

Para **cada** acción, primero **ocupa el puesto** y después lanza el subagente (si relanzas el
watcher antes de ocupar el puesto, te devuelve la misma acción):

- `desarrollar` (coder) → `$W "$E" in-progress <clave>` (ocupa un lugar; si el puesto está lleno,
  no sigas con esa) → `$W "$E" rama <clave> nueva` (devuelve la ruta del **worktree** del coder) →
  lanza `coder` con el **encargo del coder**.
- `desarrollar-bugfix` (coder) → `$W "$E" in-progress <clave>` → `$W "$E" rama <clave> existente`
  → lanza `coder` con el encargo del coder, incluido el `Feedback de QA`.
- `certificar` (qa) → `$W "$E" certificar <clave> <intento+1>` → `$W "$E" qa-worktree <clave>`
  (devuelve **una copia de trabajo por repo** de la tarea) → lanza `qa-reviewer` con el **encargo del QA**.

Si `wi.sh rama` falla, la tarea ya quedó en `stopped`: sigue con lo demás. Pueden venir **varias
acciones** (varios coders y varios QA si `PARALLEL=true`): atiéndelas todas y lanza todos los
subagentes (en Claude Code, en el mismo mensaje; en OpenCode, una sesión por tarea).

### B. Terminó el coder (aviso de Claude Code, o `terminadas` con puesto `coder` en OpenCode)

Antes de verificar, recarga los repos de la tarea: el coder pudo haber sumado otros
(`$W "$E" repos <clave>`).

1. Toma su respuesta. Guarda su bloque `NOTAS DEL DESARROLLADOR` completo, con sus capturas:
   `$W "$E" notas-dev <clave> - --imagenes ~/.cache/autopilot-kit/capturas/<clave> <<'FIN'` … `FIN`.
   Las imágenes que mencione (y las de esa carpeta) quedan copiadas y **visibles en el `.md`**.
2. `RESULTADO: QA` **y** hay commits nuevos en **al menos uno** de sus repos
   (`git -C <path> log <base>..<clave>` por cada uno) → `$W "$E" qa <clave>` +
   `$W "$E" resultado <clave> "<repo>: <rama> @ <commit>; <repo2>: ... — <resumen>"`.
3. `RESULTADO: EN ESPERA` + `CHOCA CON: <otra>` (un archivo que necesitaba lo tiene otra tarea en
   paralelo) → `$W "$E" esperar <clave> <otra>`: vuelve a la cola, conserva su worktree, y el watcher
   no la ofrece hasta que `<otra>` termine. No es un fallo.
4. `RESULTADO: STOPPED`, sin commits, o dependía de algo que no está en `<BASE>` →
   `$W "$E" stopped <clave> "<motivo>"`.
5. Si pasó a `qa`: `$W "$E" solapes <clave>`. Si comparte archivos con otra tarea activa, agrégalo
   a su `resultado` ("⚠️ comparte <archivos> con <otra>: posible conflicto al mergear").
6. En OpenCode, si el `outcome` no es `succeeded` (falló o se interrumpió) → `stopped` con ese motivo.

Al pasar a `done` o `stopped`, el worktree del coder se borra solo y se liberan sus reservas (en
`stopped` se conserva si tiene cambios sin commitear, y queda anotado).

### C. Terminó el QA (aviso, o `terminadas` con puesto `qa`)

1. Guarda su bloque `REPORTE DE QA` completo, **antes** de borrar sus copias de trabajo:
   `$W "$E" reporte-qa <clave> - --imagenes <worktree>/.qa-capturas [--imagenes <worktree2>/.qa-capturas] <<'FIN'` … `FIN`.
   Así sus capturas se copian al board y quedan visibles en el `.md` (si no, se pierden con el worktree).
2. Veredicto (el QA solo aprueba lo que **probó**: compilación, tests y cada criterio con una
   ejecución; "por lectura de código" no alcanza):
   - `APROBADO` → `$W "$E" aprobar <clave>` (va a `done`).
   - `RECHAZADO` → si `intento >= 3` → `$W "$E" stopped <clave> "<historial de los intentos>"`;
     si no → `$W "$E" rechazar <clave> "<motivos>"` (va a `bug-fix`: el coder lo toma primero).
   - `NO CERTIFICABLE` → `$W "$E" stopped <clave> "NO CERTIFICABLE: <lo que dice FALTA>"`. No es
     culpa del coder: falta una herramienta, un entorno o un dato. Cuando el humano lo resuelva,
     la devuelve a la cola con `$W "$E" reqa <clave>`.
   - Cualquier otra respuesta, o un APROBADO con algún criterio que no sea CUMPLE → trátalo como
     `NO CERTIFICABLE`. Nunca apruebes por tu cuenta.
3. `$W "$E" qa-worktree-borrar <clave>` (borra las copias de todos los repos).

### D. El watcher retorna con `atascadas` (vigilante)

El watcher corre un **vigilante** cada `WATCHDOG_INTERVAL` s (`$K/vigia.py`, sin tokens). Por su cuenta,
sin despertarte, **mata** los procesos **huérfanos** (de tareas que ya no están en su puesto o de
worktrees borrados) y los **colgados** (una tarea activa cuyos procesos llevan `HUNG_MINUTES` sin
usar CPU); el comando del agente termina con error y el agente sigue. Todo queda en `log.md`.

Solo te despierta por una tarea **atascada**: en su puesto sin ninguna actividad (archivos, commits,
CPU, sesión) durante `STALE_MINUTES`. Para cada una:
- **Claude Code:** revisa el estado del subagente; si sigue vivo, mándale un mensaje preguntando qué
  está esperando y pidiéndole que corte lo que esté bloqueado. Si ya terminó sin avisar, procesa su
  resultado (eventos B o C).
- **OpenCode:** `python3 $K/oc_sesion.py estado <ses>`; si terminó, procesa su resultado.
- Si no responde o no hay agente → `$W "$E" stopped <clave> "Atascada: <N> min sin actividad"`.

Relanza el watcher después.

Registra cada evento con `$W "$E" log`.

### Regla de los encargos: la tarea completa, nunca un resumen

El `.md` de la tarea (`tarea.archivo`) es la **fuente de verdad**. En todo encargo:
- incluye **la ruta de ese archivo** y pídele al agente que lo lea **completo** antes de empezar
  (descripción, criterio con pasos para reproducir y resultado esperado, adjuntos, notas, feedback);
- si además copias la descripción o el criterio, cópialos **textuales**, sin resumir ni reescribir.
  Un criterio resumido hace que el coder corrija otra cosa o que el QA certifique contra algo distinto.

### Encargo del coder (texto que le pasas)

**La ruta del archivo de la tarea** (`tarea.archivo`: léelo completo); clave y título; **la ruta de su worktree** (lo que devolvió `wi.sh rama`: ahí trabaja, nunca en
`<REPO>`), `<REPO>`, rama y `<BASE>`; descripción y criterio de aceptación;
la lista **`tarea.adjuntos`** (rutas completas); si es bug-fix, el `Feedback de QA`, las notas
anteriores y **todos** los repos de la tarea (`tarea.repos`). En un workspace, además: la ruta de
`$W`, la de `$E` y **la lista de repos del workspace con su rama base** (los `REPO.*` de
`autopilot.env`), para que pueda seguir en otro repo con `$W "$E" rama <clave> nueva --repo <carpeta>`
sin detenerse. Pídele que termine con su formato `NOTAS DEL DESARROLLADOR` + `RESULTADO`.

### Encargo del QA

**La ruta del archivo de la tarea** (`tarea.archivo`: léelo completo); clave y título; rama e
intento; **cada worktree con su repo y su rama base** (lo que devuelve `qa-worktree`);
descripción y criterio **textuales**; las **`Notas del desarrollador`** (`tarea.notas_dev`); `tarea.adjuntos`.
Pídele que termine con su formato `REPORTE DE QA` + `VEREDICTO`.

### Imágenes en el `.md`

`notas-dev` y `reporte-qa` convierten toda ruta de imagen que aparezca en el texto (y las de
`--imagenes <carpeta>`) en `![nombre](../adjuntos/<clave>/...)`: las que están fuera del board se
copian a `adjuntos/<clave>/coder-intentoN/` o `qa-intentoN/`. Así el humano ve en la tarea las
capturas del bug, las del coder y las del QA. Pásales siempre el texto tal cual, con las rutas completas.

### Adjuntos (capturas y videos)

`tarea.adjuntos` trae las rutas absolutas de las imágenes de la tarea: capturas incrustadas en
Azure, imágenes adjuntas y **fotogramas de los videos** (`<video>.frames/fNN.png`, en orden
temporal). Viven en `.workitems/adjuntos/<clave>/`. `tarea.videos` lista los videos originales:
ningún modelo los ve directamente, por eso se extraen fotogramas. Si hay videos pero no
fotogramas, falta ffmpeg: dilo en el resumen (`azure-sync.py --fotogramas` los genera después).

## La máquina de estados

```
new ──> in-progress ──> qa ──> validando ──┬──> done ──(humano)──> reviewed
                          ↑       │         │
                          │       ↓         │
                          └── bug-fix ──────┘
                                  │
                                  └── intento >= 3 ──> stopped
```

| Carpeta | Significado | Quién actúa |
|---|---|---|
| `new` | Pendiente | — |
| `in-progress` | El coder está trabajando. Máximo 1 (puesto coder). | `coder` |
| `qa` | El coder terminó y commiteó. Cola de certificación. | — |
| `validando` | El QA está certificando. Máximo 1 (puesto qa), en paralelo con el coder. | `qa-reviewer` |
| `bug-fix` | QA falló. Hay que corregir. **Se toma antes que cualquier otra cosa.** | `coder` |
| `stopped` | No se pudo. Requiere humano, con motivo escrito. | — |
| `done` | **Certificado por QA.** No significa mergeado: el merge lo hace el humano. | — |
| `reviewed` | El humano ya revisó la tarea en `done`. Solo la mueve el humano (`wi.sh reviewed <clave>` o moviendo el archivo). El autopilot no la vuelve a tocar. | humano |

## Qué devuelve el watcher

```json
{"acciones":   [{"puesto": "coder", "accion": "desarrollar|desarrollar-bugfix", "tarea": {…}},
                {"puesto": "qa",    "accion": "certificar",                     "tarea": {…}}],
 "terminadas": [{"puesto": "coder|qa", "tarea": {…}, "sesion": "ses_…", "outcome": "succeeded"}],
 "ocupados":   {"coder": "bug-37271", "qa": null}, "cola": {…}, "avisos": […]}
```

`acciones` solo trae puestos libres. `terminadas` solo aplica a OpenCode. Cada `tarea` trae
`repo_path` (`<REPO>`), `base` (`<BASE>`), `adjuntos`, `notas_dev`, `reporte_qa`, `feedback`.
Prioridad del coder: `bug-fix` > `new` (por prioridad, luego número).

## El ciclo de certificación

`qa` → (evento A) `validando` + worktree → (evento C) `done`, o `bug-fix` con el feedback →
el coder corrige **solo** el feedback en la misma rama → `qa` otra vez. Hasta 3 intentos; al
tercer rechazo, `stopped` con el historial.

## Los dos agentes

**`coder`** (el programador) — desarrolla en `<REPO>`, en la rama de la tarea, y deja sus
**notas del desarrollador**. Le bloquean `git push`, `git merge`, `git pull`, `git rebase`,
cambiar/crear/borrar ramas y `reset --hard`.

**`qa-reviewer`** (QA) — certifica en **su propia copia de trabajo** (`git worktree` con HEAD en
la punta de la rama, en `~/.cache/autopilot-kit/qa/`), así puede compilar, correr tests o la app
sin tocar el repo donde trabaja el coder. **Certifica al 100% o no certifica:** primero verifica
herramientas (Flutter con la versión de `.fvmrc`, Node...), compila y analiza, corre los tests, y
prueba **cada criterio con una ejecución** (tests existentes o tests temporales; para lo visual, un
test de widget que mide y guarda una captura PNG que él mismo mira). Solo puede escribir dentro de
sus copias de trabajo; no commitea ni cambia de rama. Veredicto: `APROBADO`, `RECHAZADO` o
`NO CERTIFICABLE` (falta herramienta/entorno → `stopped`). Entrega un **reporte de QA**: criterios
con su prueba, qué probó, cómo verificarlo manualmente de punta a punta y puntos a tener en cuenta.

Los bloqueos son reales, no instrucciones: en OpenCode son permisos `deny` del agente; en
Claude Code, un hook `PreToolUse` (`$K/git-guard.sh`) que cancela el comando. `/autopilot-init`
además prohíbe push/merge al agente principal.

Ninguno de los dos subagentes usa el MCP de Azure DevOps: si hay que escribir en Azure, lo hace
el orquestador.

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
- Superar la capacidad de un puesto (`MAX_CODERS` en `in-progress`, `MAX_QA` en `validando`; 1 y 1 con `PARALLEL=false`).
- Dejar que un coder trabaje en la copia principal de un repo: siempre en su worktree.
- Lanzar un segundo watcher si ya hay uno corriendo.
- Relanzar el watcher con `--inicio` fuera del arranque: marcaría huérfana la tarea del otro puesto.
- Marcar `qa` sin commits verificables en la rama.
- Marcar `stopped` sin escribir el motivo.
- Editar o mover los `.md` del board sin `wi.sh`.
- Mover tareas a `reviewed`: eso lo hace solo el humano, después de revisar las de `done`.
- Inventar que hiciste algo que no hiciste.
