---
name: autopilot
description: Sistema autonomo de desarrollo sobre un board de workitems en carpetas y archivos Markdown. Arranca el watcher y trabaja las tareas con subagentes en paralelo (coder, QA y, con E2E=true, un agente de pruebas E2E en web y Android; una tarea cada uno), una rama por workitem desde la rama base del proyecto (BASE_BRANCH), sin push ni merge. Usar cuando el usuario mencione el tablero de tareas, el board, workitems, autopilot, /autopilot, o pida trabajo autonomo sobre tareas. NO usar en proyectos que no tengan un archivo autopilot.env.
---

# Sistema Autónomo de Desarrollo (Autopilot)

Sistema donde un **watcher** vigila un board de workitems (carpetas + `.md`) y tú, el agente
principal (orquestador), delegas en **puestos que trabajan en paralelo**:

| Puesto | Agente | Toma de | Estado mientras trabaja | Máximo |
|---|---|---|---|---|
| **coder** | `coder` | `bug-fix` > `new` | `in-progress` | `MAX_CODERS` |
| **qa** | `qa-reviewer` | `qa` | `validando` | `MAX_QA` |
| **e2e** (solo con `E2E=true`) | `e2e-tester` | `e2e` | `probando-e2e` | `MAX_E2E` |

**Capacidad** (en `autopilot.env`): `PARALLEL=false` (defecto) → 1 coder, 1 QA y 1 E2E. `PARALLEL=true` →
hasta `MAX_CODERS`, `MAX_QA` y `MAX_E2E` (defecto 2, 2 y 1) a la vez, **cada uno con un workitem distinto**.

**Pruebas E2E** (`E2E=true`): lo que el QA aprueba no va a `done` sino a la cola `e2e`. El
`e2e-tester` recorre el flujo real de cada criterio (app o BackOffice → backend local → base de QA)
en web y en emulador Android, con capturas de cada paso, y recién ahí va a `done`.
`wi.sh` rechaza superar el máximo. En un workspace el límite es global, no por repo.

**Cada coder trabaja en su propia copia** (`git worktree` en `~/.cache/autopilot-kit/coder/<repo>-<clave>`),
con su rama. La copia principal del repo (la del humano) nunca cambia de rama. Dos workitems en
paralelo **no tocan el mismo archivo**: el primero que lo edita lo reserva (`wi.sh reservar`, y en
Claude Code automáticamente al editar); el otro se pone **en espera** hasta que el primero termine.

**Dependencias entre tareas** (`depende:`, las pone quien crea la tarea, p. ej. `/autopilot-plan`): la
tarea no se ofrece al coder hasta que todas sus dependencias estén en `reviewed`, porque su rama nace de
la base y ahí solo está lo que el humano ya mergeó. El watcher las lista en `en_espera` con `depende_de`:
en tu resumen dile al humano qué tiene que revisar y mergear para destrabarlas.

## Cuándo usar esta skill

Solo si el proyecto tiene un archivo `autopilot.env` en la raíz.
Si no existe, este proyecto **no participa** del sistema. No preguntes, no asumas, no la busques.

## El board

```
.workitems/                     # WORKITEMS_DIR; NO esta en git (va en .gitignore)
├── autopilot.db                # LA FUENTE DE VERDAD: tareas, historial por intento, adjuntos, log (SQLite)
├── new/          bug-140123-login-falla.md     # vistas .md de lectura, una por tarea, en la carpeta de su estado
├── in-progress/ qa/ validando/ e2e/ probando-e2e/ bug-fix/ stopped/ done/ reviewed/
├── adjuntos/<clave>/           # imagenes, videos y capturas (archivos; la base guarda su ruta)
├── planes/<slug>.md            # planes de /autopilot-plan (brainstorming y desglose)
└── log.md                      # vista del log
```

- **La tarea vive en la base.** Los `.md` se regeneran solos en la carpeta de su estado para que el
  humano los lea; si el humano mueve o edita uno a mano, el cambio se importa. Tú **no los leas** (crecen
  con cada intento): usa `$W "$E" get <clave> [parte]`, y escribe siempre con `wi.sh`.
- **Clave de la tarea = `<tipo>-<id>`** (`task-123`, `bug-login_social`). El `<id>` lo da quien crea la
  tarea: número o texto (minúsculas, dígitos y `_`). Es también el **nombre de su rama**. Es lo que se le
  pasa a `wi.sh`.
- **Cómo llegan las tareas es externo al autopilot**: `wi.sh add-task`, un `.md` en `.workitems/new/` o la
  app web. Cualquier integración (un tracker, un script) usa esos mismos puntos de entrada; el autopilot
  solo trabaja lo que hay en el board.
- Cada tarea tiene estado, prioridad, intento, rama, repo(s), origen, descripción, criterio, adjuntos,
  repos modificados, resultado, motivo de stopped y un **historial por intento** (notas del desarrollador,
  reporte y feedback de QA, reporte y feedback de E2E).
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
| Subagente de un puesto | Tool Agent con `subagent_type: coder`, `qa-reviewer` o `e2e-tester`. Corren **en segundo plano** (definido en el agente): no los esperes; Claude Code te avisa cuando terminan. | Herramienta de subagentes (`task`) con `agent: coder`, `qa-reviewer` o `e2e-tester`, `description: "<clave>: <puesto>"` y **`background: true`**: corre como **sesión hija** de la tuya, en paralelo, y la herramienta vuelve enseguida con su `sessionID`. **Regístralo siempre**: `$W "$E" sesion <clave> <sessionID>` (con él el watcher sabe cuándo termina, el vigía mide su actividad y los pedidos de permiso se rechazan solos). No la esperes ni la sondees. Sus permisos vienen de la definición del agente: solo su copia de trabajo, el kit y `/tmp`; lo demás se deniega (**nunca pregunta**). *Solo si tu OpenCode no acepta `background` en `task`* (versiones viejas): `python3 $K/oc_sesion.py lanzar <agente> <carpeta abierta> "<clave>: <puesto>" - --adjunto <img>...` con el encargo por stdin, y registra el `sesion` que devuelve. |
| Fin de un subagente | Llega como aviso de tarea terminada, con su respuesta. | Llega el aviso de OpenCode ("subagent … completed") **y** el watcher lo devuelve en `terminadas`. Procésalo una sola vez: con el primero que llegue. La respuesta completa: `python3 $K/oc_sesion.py resultado <ses>`. Si la tarea ya no está en ese puesto, ya la procesaste: ignora el otro aviso. |
| Imágenes | Pásale las rutas en el encargo: las abre con Read. | Igual: rutas completas en el encargo (las abre con su herramienta de lectura). Con `oc_sesion.py`, además como `--adjunto`. |

En OpenCode cada puesto se ve como sesión hija de la tuya: el usuario puede abrirla y mirarla en vivo.

### Por qué el watcher y no polling del agente

- **No consume tokens mientras espera.** El proceso duerme entre lecturas del board; no hay
  turnos de modelo hasta que retorna.
- **El despertar es la propia salida del script** (o, en Claude Code, el aviso de un subagente).
- **Un solo watcher a la vez.** Llévalo en la cuenta: si lo lanzaste y no retornó, sigue corriendo.

**LIMITACIÓN CONOCIDA:** el watcher vive dentro de la sesión. Si el usuario cierra el cliente, deja
de vigilar. En OpenCode las sesiones de los puestos (registradas con `wi.sh sesion`) sí siguen en su
servicio; al volver, `--inicio` las respeta (no las marca huérfanas) y el watcher avisa cuando terminan.

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
- Nadie crea, edita ni copia `.env*`. Nadie cambia a mano la URL de API de una app para probar.
- **E2E:** los backends corren locales con `aenv.sh --e2e` (su `.env.autopilot.e2e` si el humano lo
  creó; si no, su `.env.autopilot`: la base de QA); los fronts web se apuntan solos a ese backend
  local; las apps, el emulador y el navegador solo con `$K/e2e.sh`, que apunta la app al backend
  local (`E2E_API`); navegador y emulador con internet, pero con los servidores de producción del
  proyecto bloqueados (los detecta el kit).
- En cada encargo, incluye el estado de ambiente de los repos de la tarea:
  `$W "$E" entorno <clave>` (`ok` / `falta` / `inseguro` / `incompleto`, sin valores).
- Un agente que se detiene por **posible producción** (coder `STOPPED` o QA `NO CERTIFICABLE`) →
  `$W "$E" stopped <clave> "POSIBLE PRODUCCIÓN: <lo que vio>. RECOMENDACIÓN: <lo que propone>"`.
  No lo reintentes: lo resuelve el humano (creando o corrigiendo `.env.autopilot`).
- Tú nunca ejecutas nada contra ambientes.

## REGLAS DE GIT (sin excepciones)

- **Una rama independiente por workitem.** Nombre: `task-<id>` o `bug-<id>`.
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
$W "$E" depende     <clave> <clave>[,...]|-   # no se toma hasta que esas esten en reviewed ('-' las quita)
$W "$E" coder-worktree-borrar <clave>          # (también mata los procesos que queden en esa copia)
python3 $K/vigia.py "$E" [--simular]           # vigilante a mano: qué mataría / qué está atascado
$W "$E" entorno     <clave|repo>              # .env.autopilot de sus repos: ok/falta/inseguro/incompleto
$W "$E" in-progress <clave>
$W "$E" qa          <clave>
$W "$E" certificar  <clave> <intento_nuevo>   # qa -> validando
$W "$E" aprobar     <clave>                   # validando -> done (con E2E=true: -> e2e)
$W "$E" rechazar    <clave> "<motivos>"       # validando -> bug-fix
$W "$E" new         <clave>
$W "$E" reviewed    <clave>                   # SOLO el humano: done -> reviewed
$W "$E" stopped     <clave> "<motivo>"
$W "$E" resultado   <clave> "<rama | commit | resumen>"
$W "$E" add-task    <task|bug> <id> <prioridad> "<titulo>" "<descripcion>" "<criterio>" [repo] [--depende <claves>] [--origen <texto>]   # repo obligatorio en workspace; @archivo en descripcion/criterio
$W "$E" log <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
$W "$E" query [estado]
$W "$E" sesion      <clave> <ses_id>          # OpenCode: sesión que trabaja la tarea
$W "$E" notas-dev   <clave> -   <<'FIN'       # notas del coder (stdin)
$W "$E" reporte-qa  <clave> -   <<'FIN'       # reporte del QA (stdin)
$W "$E" qa-worktree <clave>                   # copia de trabajo del QA
$W "$E" qa-worktree-borrar <clave>
# E2E (solo con E2E=true)
$W "$E" probar-e2e  <clave>                   # e2e -> probando-e2e (ocupa el puesto e2e)
$W "$E" e2e-worktree <clave>                  # copias E2E: repos de la tarea + los que pide el flujo real
$W "$E" reporte-e2e <clave> - --imagenes <copia>/.e2e-capturas <<'FIN'   # reporte + capturas al .md
$W "$E" validar-e2e <clave>                   # ¿cada criterio CUMPLE y con capturas? (JSON)
$W "$E" aprobar-e2e <clave>                   # probando-e2e -> done (se niega si validar-e2e falla)
$W "$E" rechazar-e2e <clave> "<motivos>"      # probando-e2e -> bug-fix
$W "$E" re-e2e      <clave>                   # -> e2e otra vez (tras resolver un NO CERTIFICABLE)
$W "$E" e2e-worktree-borrar <clave>           # mata backend, web y emulador que queden ahí
# Casos guardados en los repos (tests/<clave>/cases.json): volver a correrlos
$W "$E" test <clave>|smoke|--all [--qa|--e2e] [--web|--android]   # o $K/run-tests ...; reporte en test-results/
$W "$E" health [<clave>|smoke|--all] [--web|--android] [--deep]   # o $K/health-check: que falta ANTES de correr
$W "$E" smoke-save <copia>                    # pruebas de humo (tests/smoke/) a la rama smoke-tests del repo
```

## El bucle

Hay seis eventos. Atiende cada uno y **relanza el watcher si no está corriendo**.

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
- `probar-e2e` (e2e) → `$W "$E" probar-e2e <clave>` → `$W "$E" e2e-worktree <clave>` (una copia por
  repo: los de la tarea en su rama y los que pide el flujo real en su base, con tipo, plataformas,
  `api` y `entorno_e2e`) → lanza `e2e-tester` con el **encargo del E2E**. (No cambia el intento.)

Si `wi.sh rama` falla, la tarea ya quedó en `stopped`: sigue con lo demás. Pueden venir **varias
acciones** (varios coders y varios QA si `PARALLEL=true`): atiéndelas todas y lanza todos los
subagentes en segundo plano, uno por tarea (en Claude Code y en OpenCode, en el mismo mensaje).

### B. Terminó el coder (aviso de Claude Code, o `terminadas` con puesto `coder` en OpenCode)

Antes de verificar, recarga los repos de la tarea: el coder pudo haber sumado otros
(`$W "$E" repos <clave>`).

1. Toma su respuesta. Guarda su bloque `NOTAS DEL DESARROLLADOR` completo, con sus capturas:
   `$W "$E" notas-dev <clave> - --imagenes ~/.cache/autopilot-kit/capturas/<clave> <<'FIN'` … `FIN`.
   Las imágenes que mencione (y las de esa carpeta) se copian a `adjuntos/<clave>/coder-intentoN/` y quedan
   **referenciadas** en su intento (`📷 nombre` + carpeta), no incrustadas en el texto.
2. `RESULTADO: QA` **y** hay commits nuevos en **al menos uno** de sus repos
   (`$W "$E" repos-modificados <clave>`: commits y archivos por repo, desde git) →
   `$W "$E" qa <clave>` (escribe solo la sección **`## Repos modificados`** en la tarea y avisa si
   no coincide con el bloque `REPOS MODIFICADOS` que declaró el coder) +
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
   - `APROBADO` → `$W "$E" aprobar <clave>` (va a `done`; con `E2E=true` va a la cola `e2e`: lo
     dice su salida, `ok -> done` u `ok -> e2e`). **Antes**, guarda solo los casos del QA
     (`tests/<clave>/` de sus copias) en la rama de la tarea con un commit `test: casos de prueba de
     <clave>`; si no son válidos no los guarda y lo avisa (`AVISO:`), sin frenar la aprobación.
     Hazlo **antes** de `qa-worktree-borrar` (si no, se pierden).
   - `RECHAZADO` → si `intento >= 3` → `$W "$E" stopped <clave> "<historial de los intentos>"`;
     si no → `$W "$E" rechazar <clave> "<motivos>"` (va a `bug-fix`: el coder lo toma primero).
   - `NO CERTIFICABLE` → mira **quién lo resuelve** (el QA separa `FALTA (codigo):` de `FALTA (humano):`;
     ver *Bloqueos: ¿coder o humano?*):
     - solo `FALTA (codigo)` (algo preexistente en el repo impide compilar o probar: un import roto,
       un archivo que no compila) → `$W "$E" rechazar <clave> "<qué corregir y cómo>" --bloqueo`. Vuelve
       al coder **sin contar como intento** y sin molestar al humano.
     - algún `FALTA (humano)` (herramienta, `.env.autopilot`, cuenta, dato, posible producción) →
       `$W "$E" stopped <clave> "NO CERTIFICABLE: <lo que falta>"`. Cuando el humano lo resuelva,
       la devuelve a la cola con `$W "$E" reqa <clave>`.
   - Cualquier otra respuesta, o un APROBADO con algún criterio que no sea CUMPLE → trátalo como
     `NO CERTIFICABLE`. Nunca apruebes por tu cuenta.
3. `$W "$E" qa-worktree-borrar <clave>` (borra las copias de todos los repos). Si la tarea no quedó
   aprobada, **guarda solo** las pruebas del QA como borrador (`adjuntos/<clave>/borradores/qa/`) y la
   próxima `qa-worktree` las vuelve a poner en la copia: el QA no las reescribe desde cero.

### D. Terminó el E2E (aviso, o `terminadas` con puesto `e2e`)

1. Guarda su bloque `REPORTE E2E` completo, **antes** de borrar sus copias:
   `$W "$E" reporte-e2e <clave> - --imagenes <copia1>/.e2e-capturas [--imagenes <copia2>/.e2e-capturas] <<'FIN'` … `FIN`.
   Las capturas que cita (y las de esas carpetas) se copian a `adjuntos/<clave>/e2e-intentoN/` y
   quedan **referenciadas** (`📷 nombre`) en el paso que muestran; la app web las muestra en la galería del intento.
2. Veredicto:
   - `APROBADO` → `$W "$E" aprobar-e2e <clave>` (va a `done`). También guarda los casos E2E y los
     `tests/services.json` de sus copias en la rama (commit `test: ...`); si un repo del flujo no era
     de la tarea, le abre la rama. **Antes** de `e2e-worktree-borrar`. **Se niega** si algún criterio del
     reporte no dice CUMPLE, no tiene capturas o falta una plataforma esperada: entonces trátalo como
     `NO CERTIFICABLE` con lo que dijo `validar-e2e`. Nunca apruebes por tu cuenta.
   - `RECHAZADO` → si `intento >= 3` → `$W "$E" stopped <clave> "<historial>"`; si no →
     `$W "$E" rechazar-e2e <clave> "<motivos>"` (va a `bug-fix`: el coder recibe el `Feedback de E2E`
     y el Reporte E2E con las capturas del paso que falló; luego vuelve a pasar por QA y E2E).
   - `NO CERTIFICABLE` → igual que en C: solo `FALTA (codigo)` →
     `$W "$E" rechazar-e2e <clave> "<qué corregir y cómo>" --bloqueo` (al coder, sin contar intento);
     algún `FALTA (humano)` → `$W "$E" stopped <clave> "NO CERTIFICABLE (E2E): <lo que falta>"` y,
     cuando el humano lo resuelva, `$W "$E" re-e2e <clave>`.
   - Cualquier otra respuesta → como `NO CERTIFICABLE`.
3. `$W "$E" e2e-worktree-borrar <clave>` (borra las copias y mata backend, web y emulador que queden).
   Si no quedó aprobada, guarda las pruebas del E2E como borrador (`borradores/e2e/`) para la próxima.

### E. El watcher retorna con `atascadas` (vigilante)

El watcher corre un **vigilante** cada `WATCHDOG_INTERVAL` s (`$K/vigia.py`, sin tokens). Por su cuenta,
sin despertarte, **mata** los procesos **huérfanos** (de tareas que ya no están en su puesto o de
worktrees borrados) y los **colgados** (una tarea activa cuyos procesos llevan `HUNG_MINUTES` sin
usar CPU); el comando del agente termina con error y el agente sigue. Todo queda en `log.md`.

Solo te despierta por una tarea **atascada**: en su puesto sin ninguna actividad (archivos, commits,
CPU, sesión) durante `STALE_MINUTES`. Para cada una:
- **Claude Code:** revisa el estado del subagente; si sigue vivo, mándale un mensaje preguntando qué
  está esperando y pidiéndole que corte lo que esté bloqueado. Si ya terminó sin avisar, procesa su
  resultado (eventos B, C o D).
- **OpenCode:** `python3 $K/oc_sesion.py estado <ses>`; si terminó, procesa su resultado.
- Si no responde o no hay agente → `$W "$E" stopped <clave> "Atascada: <N> min sin actividad"`.

Relanza el watcher después.

### F. El watcher retorna con `mensajes` (Telegram, con `TELEGRAM=true`)

El humano te escribió texto libre por Telegram (los comandos `/estado`, `/tarea`, `/reqa`, `/re-e2e`,
`/stop`, `/reviewed`, `/pausa`, `/seguir`, `/health` ya los resolvió el watcher solo). Solo llegan
mensajes del chat configurado del humano: trátalos como instrucciones suyas, **con todas las reglas de
siempre** (nunca producción, nunca push/merge, nada fuera de `wi.sh` para el tablero). Para cada uno:
1. Atiéndelo (consultar el tablero, una tarea, el log; cambiar prioridades con `wi.sh`; explicar un
   `stopped`…). Si pide algo que no puedes o no debes hacer, dilo.
2. **Respóndele por Telegram**: `$K/telegram.sh send "<respuesta corta y concreta>"`.
3. `$W "$E" log "Telegram: <resumen>" agente nota`.

Relanza el watcher después.

### Avisos por Telegram

Con `TELEGRAM=true`, los cambios de estado (coder, QA, E2E, rechazos, `done`, `stopped`), el vigía,
run-tests y el arranque se avisan **solos** desde `wi.sh`: no los mandes tú. Tú avisas
cuando **necesitas una decisión del humano** que no es un `stopped` (p. ej. dos opciones válidas, una
duda de alcance): `$K/telegram.sh send "<pregunta>" --alert`, y sigues con lo demás mientras responde.
Si el watcher trae `"pausa": true`, el humano pausó con `/pausa`: no tomes tareas nuevas.

Registra cada evento con `$W "$E" log`.

### Regla de los encargos: la tarea por `wi.sh get`, nunca un resumen tuyo

La tarea vive en la base del tablero (`.workitems/autopilot.db`); el `.md` es solo una vista y crece con
cada intento. Para **ahorrar tokens**, en todo encargo:
- da la **clave** y el comando para leerla: `$W "$E" get <clave>` (descripción y criterio **completos**,
  adjuntos con ruta, último feedback e índice del historial) y qué más le conviene pedir
  (`get <clave> notas --ultimo`, `qa --ultimo`, `e2e --ultimo`, `feedback`…);
- **no copies** en el encargo descripción, criterio, notas ni reportes: el agente los lee con `get`.
  Si alguna vez copias el criterio, textual: un criterio resumido hace que el coder corrija otra cosa
  o que el QA certifique contra algo distinto;
- tú tampoco necesitas leer el `.md`: `$W "$E" get <clave> [parte]` también te sirve a ti.

### Encargo del coder (texto que le pasas)

Clave y título; el comando `$W "$E" get <clave>` (ahí están descripción, criterio, adjuntos y el último
feedback; si el rechazo vino de E2E, que pida también `get <clave> e2e --ultimo` para ver las capturas del
paso que falló); **la ruta de su worktree** (lo que devolvió `wi.sh rama`: ahí trabaja, nunca en
`<REPO>`), `<REPO>`, rama y `<BASE>`; si es bug-fix, **todos** los repos de la tarea (`tarea.repos`). En un workspace, además: la ruta de
`$W`, la de `$E` y **la lista de repos del workspace con su rama base** (los `REPO.*` de
`autopilot.env`), para que pueda seguir en otro repo con `$W "$E" rama <clave> nueva --repo <carpeta>`
sin detenerse. Pídele que termine con su formato `NOTAS DEL DESARROLLADOR` + `RESULTADO`.

### Encargo del QA

Clave y título; rama e intento; los comandos `$W "$E" get <clave>` y `get <clave> notas --ultimo`;
**cada worktree con su repo y su rama base** (lo que devuelve `qa-worktree`, **incluido su `borrador`**
si lo trae: las pruebas de la corrida anterior, para que no las reescriba).
Pídele que termine con su formato `REPORTE DE QA` + `VEREDICTO`.

### Encargo del E2E

Clave, título, rama e intento; los comandos `$W "$E" get <clave>`, `get <clave> qa --ultimo` y
`get <clave> notas --ultimo`; **cada copia E2E** tal como la devuelve `e2e-worktree` (repo, ruta, ref, si es de la tarea,
`borrador` si lo trae,
tipo, plataformas, `api`, `entorno_e2e`); la ruta de `$E`; y el resultado de `$K/e2e.sh doctor` y de `$W "$E" check`
(herramientas y avisos) y la salida de `$K/health-check <clave>` (corrido en la carpeta de `$E`). Si el
health check marca ❌, no lances al agente y aplica *Bloqueos: ¿coder o humano?*.
Pídele que termine con su formato `REPORTE E2E` + `VEREDICTO`, citando la
ruta completa de cada captura en el paso que muestra.

### Bloqueos: ¿coder o humano?

Antes de detener una tarea, pregúntate **quién lo puede resolver**. `stopped` es solo para lo que
necesita al humano; todo lo que se arregla con un commit en la rama vuelve al coder.

| Lo que bloquea | Quién | Qué haces |
|---|---|---|
| El código no compila o no se puede probar por algo del repo (import con mayúsculas que no existe en Linux, error de compilación, `cases.json` inválido), aunque sea **preexistente** | coder | `rechazar` / `rechazar-e2e <clave> "<qué y cómo>" --bloqueo` |
| Falta una herramienta, acceso a KVM, `.env.autopilot` / `PORT`, una cuenta de prueba, un dato, configuración de `autopilot.env`, o hay duda de producción | humano | `stopped` con el motivo y la recomendación |

El health check ya lo marca: `❌ … [coder]` o `❌ … [humano]` (y en `--json`, `"responsable"`). Si **todos**
los ❌ son `[coder]` → `--bloqueo`; si hay alguno `[humano]` → `stopped`. En el feedback del `--bloqueo`
di exactamente qué corregir (archivo, línea, cómo) y que es preexistente pero impide certificar la tarea.
Si la misma tarea vuelve a bloquearse por lo mismo después de un `--bloqueo`, ahí sí `stopped`.

### Imágenes: referenciadas por intento, no incrustadas

`notas-dev`, `reporte-qa` y `reporte-e2e` copian toda imagen que aparezca en el texto (y las de
`--imagenes <carpeta>`) a `adjuntos/<clave>/coder-intentoN/`, `qa-intentoN/` o `e2e-intentoN/`. En el
texto, cada ruta queda como `📷 <nombre>` (sin incrustar) y al final del intento va una sola línea
`📎 N capturas → [<paso>-intentoN/](...)`. La app web (`autopilot-web`) muestra esas imágenes en una galería
plegable bajo el intento al que pertenecen, y cada `📷` abre la suya. Los videos que mencionen (`.mp4`,
`.webm`...) también se copian y quedan enlazados. `validar-e2e` cuenta los `📷` de cada criterio.
Pásales siempre el texto tal cual, con las rutas completas. Las tareas viejas se convierten solas la primera
vez que corre el kit nuevo (o con `$W "$E" limpiar-imagenes [--simular]`).

### Adjuntos (capturas y videos)

`tarea.adjuntos` trae las rutas absolutas de las imágenes de la tarea: capturas de la tarea
original, imágenes adjuntas y **fotogramas de los videos** (`<video>.frames/fNN.png`, en orden
temporal). Viven en `.workitems/adjuntos/<clave>/`. `tarea.videos` lista los videos originales:
ningún modelo los ve directamente, por eso se extraen fotogramas. Si hay videos pero no
fotogramas, dilo en el resumen: el agente no puede ver ese video.

## La máquina de estados

```
new ──> in-progress ──> qa ──> validando ──┬──────────────────────────────> done ──(humano)──> reviewed
                          ↑       │         │  (E2E=true)                     ↑
                          │       │         └──> e2e ──> probando-e2e ───────┘
                          │       ↓                          │
                          └── bug-fix <──────────────────────┘ (RECHAZADO en E2E)
                                  │
                                  └── intento >= 3 ──> stopped   (NO CERTIFICABLE en QA o E2E ──> stopped)
```

| Carpeta | Significado | Quién actúa |
|---|---|---|
| `new` | Pendiente | — |
| `in-progress` | El coder está trabajando. Máximo 1 (puesto coder). | `coder` |
| `qa` | El coder terminó y commiteó. Cola de certificación. | — |
| `validando` | El QA está certificando. Máximo 1 (puesto qa), en paralelo con el coder. | `qa-reviewer` |
| `e2e` | QA aprobó y `E2E=true`. Cola de pruebas E2E. | — |
| `probando-e2e` | El agente E2E está recorriendo los flujos (web y Android). | `e2e-tester` |
| `bug-fix` | QA o E2E falló. Hay que corregir. **Se toma antes que cualquier otra cosa.** | `coder` |
| `stopped` | No se pudo. Requiere humano, con motivo escrito. | — |
| `done` | **Certificado por QA** (y por E2E si `E2E=true`). No significa mergeado: el merge lo hace el humano. | — |
| `reviewed` | El humano ya revisó la tarea en `done`. Solo la mueve el humano (`wi.sh reviewed <clave>` o moviendo el archivo). El autopilot no la vuelve a tocar. | humano |

## Qué devuelve el watcher

```json
{"acciones":   [{"puesto": "coder", "accion": "desarrollar|desarrollar-bugfix", "tarea": {…}},
                {"puesto": "qa",    "accion": "certificar",                     "tarea": {…}},
                {"puesto": "e2e",   "accion": "probar-e2e",                     "tarea": {…}}],
 "terminadas": [{"puesto": "coder|qa|e2e", "tarea": {…}, "sesion": "ses_…", "outcome": "succeeded"}],
 "ocupados":   {"coder": ["bug-37271"], "qa": [], "e2e": []}, "e2e": true,
 "cola": {"bugfix": 0, "qa": 1, "new": 3, "e2e": 0}, "avisos": […],
 "pausa": false, "mensajes": [{"texto": "¿por qué se detuvo la 37269?", "fecha": 1790000000}]}
```

`acciones` solo trae puestos libres. `terminadas` solo aplica a OpenCode. También solo en OpenCode:
`permisos_rechazados` (`[{"tarea", "puesto", "accion", "recursos"}]`). Si una sesión de un puesto quedó
esperando un permiso, el watcher lo rechaza solo, le explica al agente que siga sin eso, lo deja en el
log y avisa por Telegram. Nadie tiene que aprobar nada. Menciónalo en tu resumen; si el agente termina
diciendo que lo necesitaba, trátalo como cualquier bloqueo (`stopped` con el motivo). Cada `tarea` trae
`repo_path` (`<REPO>`), `base` (`<BASE>`), `adjuntos`, `notas_dev`, `reporte_qa`, `feedback`,
`reporte_e2e`, `feedback_e2e`, `repos_modificados`. `"e2e": true` = la etapa E2E está activa.
Prioridad del coder: `bug-fix` > `new` (por prioridad, luego número).

## El ciclo de certificación

`qa` → (evento A) `validando` + worktree → (evento C) `done`, o `bug-fix` con el feedback →
el coder corrige **solo** el feedback en la misma rama → `qa` otra vez. Hasta 3 intentos; al
tercer rechazo, `stopped` con el historial.

Con `E2E=true`, el `APROBADO` del QA va a `e2e` → (evento A) `probando-e2e` + copias E2E →
(evento D) `done`, o `bug-fix` con el `Feedback de E2E` → el coder corrige → `qa` → `e2e` otra vez.
El contador de intentos es uno solo (lo sube el QA): los rechazos de QA y de E2E suman juntos.

## Los agentes

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

**`e2e-tester`** (E2E, solo con `E2E=true`) — termina de certificar lo que el QA aprobó: levanta
los backends de la tarea **locales** contra la base de QA (`aenv.sh --e2e`), apunta
las apps a ese backend (`e2e.sh api`), y recorre el flujo de cada criterio como una persona: BackOffice
y apps Flutter en web (Playwright) y las apps en un **emulador Android** (internet abierto, producción
bloqueada). Saca **capturas
en cada paso** (y video) que quedan referenciadas en su paso del `## Reporte E2E`. Solo escribe en sus copias
E2E; no commitea. Veredicto `APROBADO` (cada criterio CUMPLE con capturas, en cada plataforma),
`RECHAZADO` (→ `bug-fix`) o `NO CERTIFICABLE` (→ `stopped`).

Los bloqueos son reales, no instrucciones: en OpenCode son permisos `deny` del agente; en
Claude Code, un hook `PreToolUse` (`$K/git-guard.sh`) que cancela el comando. `/autopilot-init`
además prohíbe push/merge al agente principal.

## Log de actividad

`log.md` es una tabla a la que solo se agregan filas: `Hora`, `Origen`
(`watcher`|`agente`|`sistema`), `Tipo` (`deteccion`|`delegacion`|`QA`|`E2E`|`Stopped`|`recuperacion`|`error`|`nota`),
`Tarea`, `Rama`, `Commit`, `Evento`, `Detalle`.

## Lo que NUNCA debes hacer

- **Dejar el watcher sin correr al terminar una tarea.** Relánzalo siempre.
- **Cerrar el turno sin un watcher activo** sin decírselo al usuario.
- **Afirmar que el sistema sigue vigilando si el watcher no corre.**
- `git push` o `git merge`. **El merge lo hace el humano, siempre.**
- Crear una rama desde otra que no sea `<BASE>`, o con otro nombre que `task-<n>`/`bug-<n>`.
- Trabajar en `<BASE>` directamente.
- Superar la capacidad de un puesto (`MAX_CODERS` en `in-progress`, `MAX_QA` en `validando`, `MAX_E2E`
  en `probando-e2e`; 1 cada uno con `PARALLEL=false`).
- Aprobar en E2E sin `aprobar-e2e` (que exige capturas por criterio) o mover a `done` una tarea de `e2e`.
- Dejar que un coder trabaje en la copia principal de un repo: siempre en su worktree.
- Lanzar un segundo watcher si ya hay uno corriendo.
- Relanzar el watcher con `--inicio` fuera del arranque: marcaría huérfana la tarea del otro puesto.
- Marcar `qa` sin commits verificables en la rama.
- Marcar `stopped` sin escribir el motivo.
- Editar o mover los `.md` del board sin `wi.sh`.
- Mover tareas a `reviewed`: eso lo hace solo el humano, después de revisar las de `done`.
- Inventar que hiciste algo que no hiciste.
