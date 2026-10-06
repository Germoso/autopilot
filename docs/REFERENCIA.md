# Referencia del Autopilot

Todo el detalle técnico. Para empezar a usarlo, lee primero el [README](../README.md).

**Índice**

1. [Cómo funciona: estados, ramas y reglas](#cómo-funciona)
2. [Instalación y configurar un proyecto](#instalación)
3. [autopilot.env: todas las variables](#autopilotenv)
4. [Uso: entrada de tareas, adjuntos y el watcher](#uso)
5. [Trabajo en paralelo, vigilante, producción, QA y E2E](#puestos-en-paralelo)
6. [Telegram](#telegram)
7. [Casos de prueba guardados y el comando `test`](#casos-de-prueba-guardados-tests)
8. [Comandos de wi.sh](#comandos-de-wish)
9. [Estructura del kit](#qué-incluye)
10. [Seguridad](#seguridad)

---

## Cómo funciona

```
new ──> in-progress ──> qa ──> validando ──┬──────────────────────────────> done ──(humano)──> reviewed
 (coder programa)          (QA prueba)      │  (E2E=true)                     ↑
                          ↑       │         └──> e2e ──> probando-e2e ───────┘
                          │       ↓                          │
                          └── bug-fix <──────────────────────┘
                                  │
                                  └── intento >= 3 o NO CERTIFICABLE ──> stopped
```

---

### El board

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
    ├── adjuntos/<clave>/         # capturas y videos de la tarea (archivos)
    ├── planes/<slug>.md          # planes de /autopilot-plan (brainstorming y desglose)
    ├── autopilot.db              # la base: fuente de verdad de las tareas
    └── log.md                    # log de actividad (solo se agregan filas)
```

- **La fuente de verdad es `autopilot.db`** (SQLite, modo WAL: varios agentes escriben a la vez sin
  pisarse). Cada `.md` de las carpetas es una **vista generada** que se reescribe con cada cambio. Solo muestra el bug original (descripción, criterio y adjuntos originales); notas, reportes, feedback e historial se consultan con `get` o en la app web.
- **El estado de una tarea es la carpeta donde está su `.md`.** Podés mover tareas a mano
  (explorador, VS Code, Obsidian) o crear un `.md` en `new/`: el próximo comando lo pasa a la base y
  el watcher lo ve en segundos. Para editar textos usa la app web o `wi.sh` (`descripcion`,
  `criterio`, `titulo`, `prioridad`).
- **`reviewed`**: cuando revisas una tarea de `done`, muévela a `reviewed/` (arrastrando el archivo
  o con `wi.sh <env> reviewed <clave>`). Así `done` queda solo con lo pendiente de revisar. Con
  `AUTO_MERGE=true` el autopilot la mueve sola (además de mergearla) al aprobar el QA/E2E; sin la
  variable, el autopilot nunca mueve tareas a `reviewed` ni las vuelve a tocar.
- **Feedback y devolver** (`done`, `reviewed` o `stopped` → coder, QA o E2E): botón **💬 Feedback y
  devolver** de la app web, que pregunta a quién se la devuelves (por dentro, `wi.sh <env> pedir-cambios <clave> "<texto>" --a
  coder|qa|e2e`).
  | Destino | Pasa a | Feedback | Intento |
  |---|---|---|---|
  | coder (defecto) | `bug-fix` (misma rama) | `## Feedback de QA` | a 0 |
  | qa | `qa` (vuelve a certificar) | `## Feedback de QA` | a 0 |
  | e2e (`E2E=true`) | `e2e` (vuelve a probar) | `## Feedback de E2E` | no cambia |

  El texto queda como `### FEEDBACK DEL HUMANO para el coder|QA|E2E` (las tareas viejas pueden traer
  `CAMBIOS PEDIDOS en la revisión humana`, que se sigue reconociendo): el agente lo ve como
  *Último feedback* en `get` y sus instrucciones le dicen que lo trate como un criterio prioritario.
  También se suma al `## Criterio de aceptación`. Aviso 💬 por Telegram.
- **El nombre del archivo es `<tipo>-<id>-<slug>.md`.** `<tipo>-<id>` es la clave de
  la tarea y **el nombre de su rama**. El `<id>` lo da quien crea la tarea: número (`140123`) o
  texto (`login_social`), en minúsculas, dígitos y `_` (sin `-`, que separa la clave del slug).
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
origen: manual
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

#### La base (`autopilot.db`)

| Tabla | Qué guarda |
|---|---|
| `tareas` | una fila por tarea: estado, metadatos, título, descripción, criterio, resultado, motivo |
| `entradas` | una fila por bloque de historial: tipo (`notas_dev`, `reporte_qa`, `feedback_qa`, `reporte_e2e`, `feedback_e2e`), intento, fecha, título, texto |
| `adjuntos` | cada archivo de `adjuntos/<clave>/`: ruta relativa a `.workitems/`, origen (original/humano/coder/qa/e2e), intento, tipo, tamaño, sha256 |
| `log` | el log de actividad (también se sigue agregando a `log.md`) |
| `meta` | versión del esquema y marca de migración |

Cada adjunto sabe **qué paso lo produjo** (`origen` + `intento`, sacados de su carpeta:
`coder-intento0/`, `qa-intento1/`, `e2e-intento1/`, `humano/`; el resto es de la tarea original).
`wi.sh get <clave> adjuntos` y la app web los muestran agrupados en el orden en que ocurrieron:
tarea original → subidos por el humano → coder 0 → QA 1 → E2E 1 → coder 1 → QA 2 → … (los fotogramas
de un video se resumen en una línea).

Los adjuntos siguen siendo archivos (la base guarda su ruta): así los textos los enlazan con
`![..](../adjuntos/...)` y se ven igual en el `.md`, en la app web y en el visor de imágenes.

**Migración:** la primera vez que un comando abre un tablero con `.md` y sin base, lo pasa solo (cada
`### Intento …` queda como una fila de `entradas`, cada adjunto se registra) y deja los `.md`
originales en `.workitems/.respaldo-md-<fecha>/`. También a mano: `wi.sh <env> migrate`.

**Leer por partes:** `wi.sh <env> get <clave> [parte]` devuelve solo lo que hace falta. Los agentes
leen `get <clave>` (descripción y criterio completos, adjuntos y lo último de cada historial) y piden
el resto (`notas --ultimo`, `qa --ultimo`, `historial`...) en vez de leer el `.md` entero.

---

### Ramas

- **Una rama independiente por workitem**: `task-<id>` o `bug-<id>` (ej. `bug-140123`, `task-login_social`).
- **Siempre desde la rama base de su repo**, definida en `autopilot.env` (obligatoria):
  `BASE_BRANCH=<rama>` en un repo, o `REPO.<carpeta>=<rama>` por repo en un workspace.
  Si está vacía o la rama no existe (ni local ni en `origin`), la tarea pasa a `stopped`:
  no se inventa otra base.
- **Siempre desde lo último de `origin`:** antes de crear la rama, el kit hace `git fetch` de la base
  (lo que haría un `pull`, pero sin merges; los agentes no hacen `pull`, lo bloquea git-guard).
  - `origin/<base>` va adelante → la rama nace de `origin/<base>` y tu base local se adelanta
    (fast-forward) si tu copia está limpia; con cambios sin commitear no se toca.
  - Tu base local tiene commits que `origin` no tiene (p. ej. dependencias mergeadas sin push) → nace
    de la base local, que ya incluye todo `origin`.
  - Divergieron, o no hay red/credenciales → nace de la base local, queda en el log de la tarea y avisa
    por Telegram. La tarea no se detiene.
  - Un bug-fix sigue en su rama existente: no se vuelve a traer la base.
- **Workspace:** la rama se crea **dentro del repo de la tarea** (`repo:` en su frontmatter).
  Una tarea sin repo, o con un repo que no está en `autopilot.env`, pasa a `stopped`.
- Cada tarea se trabaja en su **propia copia del repo** (`git worktree`): tu copia principal no se
  toca ni cambia de rama, aunque tenga cambios sin commitear.
- Si la rama de una tarea nueva ya existe, `stopped`: no se pisa trabajo previo.
- Un rechazo de QA se corrige **en la misma rama**.
- **Nunca `push`, nunca `merge`.** Bloqueados por permiso. El merge lo hace el humano.

---

### Reglas de trabajo

Fijadas en `SKILL.md`, se aplican sin que nadie las recuerde:

- **Puestos en paralelo, una tarea cada uno:** 1 coder (`in-progress`), 1 QA (`validando`) y, con `E2E=true`, 1 E2E (`probando-e2e`).
  `wi.sh` rechaza una segunda tarea en el mismo puesto.
- **Una rama por workitem:** `task-<id>` / `bug-<id>` desde `BASE_BRANCH`.
- **Nadie hace `push` ni `merge`** (ni `pull`, que mergea). Bloqueado por permiso/hook, no por instrucción.
- **QA y E2E no tocan el código:** prueban en sus propias copias (worktree); solo escriben pruebas temporales ahí; no commitean ni cambian de rama.
- **Nada se certifica sin probarlo:** sin compilación, tests y una prueba por criterio, el veredicto es `NO CERTIFICABLE` y la tarea queda en `stopped`. En E2E, un criterio sin capturas no está probado.
- **Nunca contra producción:** solo `.env.autopilot` / `.env.autopilot.e2e` que crea el humano (local o QA), apps apuntadas al backend local, red cortada en navegador y emulador.
- **Todo queda escrito en la tarea:** repos modificados, notas del desarrollador, reporte de QA y reporte E2E (con capturas), por intento.
- **`bug-fix` tiene prioridad** sobre trabajo nuevo: siempre se toma primero.
- **3 intentos** de certificación (los rechazos de QA y de E2E suman juntos). Al cuarto, `stopped` con el historial.
- **`stopped` es para el humano**, con motivo escrito. Nunca inventar.

---

## Instalación

```sh
git clone <tu-repo> dotenvs
cd dotenvs
./install.sh                              # detecta OpenCode y Claude Code
./install.sh --claude                     # o solo uno
```

No pisa nada que no haya generado el kit: si ya existe una skill o agente con el mismo
nombre y no es del kit, lo deja y avisa. Reinstalar actualiza lo que sí es del kit.

Para las pruebas E2E (opcional), además, una vez: `~/.local/share/autopilot-kit/e2e-setup.sh`
(ver *Pruebas E2E: terminar de certificar*).

### Desinstalar

```sh
./install.sh --uninstall
```

Quita scripts, skills, agentes, comandos y las integraciones instaladas. Quedan intactos los proyectos
(`.env`, board, guardas) y `~/.config/autopilot-kit/`. Las herramientas E2E
(`~/.local/share/autopilot-e2e/`, ~6 GB) tampoco se tocan: bórralas con
`rm -rf ~/.local/share/autopilot-e2e` si ya no las usas.

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

- crea `autopilot.env` y el board `.workitems/`
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
├── .workitems/                 un solo board; cada tarea dice su repo (repo: <carpeta>)
├── Konectame_App_Clientes/     <- la rama bug-140123 se crea ACÁ, desde dev
└── Konectame_BackOffice/
```

- Cada repo tiene **su propia rama base**. La rama de cada tarea se crea dentro de su repo.
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

Todas las variables: [autopilot.env](#autopilotenv).

**La rama base se define por proyecto/repo** en su `autopilot.env`. Para cambiarla, editá la
línea o volvé a correr `/autopilot-init`; no hace falta reinstalar nada.

---

## autopilot.env

Lo crea `/autopilot-init`; se edita a mano. En un workspace va en la carpeta padre de los repos.

| Variable | Default | Qué es |
|---|---|---|
| `BASE_BRANCH` | **obligatoria** (un repo) | Rama desde la que nacen las ramas de los workitems |
| `REPO.<carpeta>` | **una por repo** (workspace) | Rama base de ese repo. Si hay alguna, es un workspace |
| `REPO_PATH` | carpeta del `.env` | Ruta del repo (modo un repo) |
| `WORKITEMS_DIR` | `.workitems` junto al `.env` | Carpeta del board |
| `POLL_INTERVAL` | `5` | Segundos entre lecturas del board |
| `PARALLEL` | `false` | `true` = varios agentes por puesto (hasta los `MAX_*`) |
| `MAX_CODERS`, `MAX_QA`, `MAX_E2E` | `2`, `2`, `1` | Máximo por puesto con `PARALLEL=true` |
| `WATCHDOG` | `true` | Vigilante de procesos colgados/huérfanos |
| `WATCHDOG_INTERVAL` | `60` | Segundos entre revisiones del vigilante |
| `HUNG_MINUTES` | `10` | Minutos sin CPU para considerar un proceso colgado |
| `STALE_MINUTES` | `45` | Minutos sin actividad para avisar de una tarea atascada |
| `COMMAND_TIMEOUT` | `900` | Segundos máximos de un comando por `aenv.sh` |
| `TELEGRAM` | `false` | Avisos por Telegram y comandos desde el chat |
| `TELEGRAM_ALERTS_ONLY` | `false` | Solo los avisos que necesitan intervención (🚨) |
| `CADENA_MIN` | `20` | Minutos de cadena detenida esperando al humano antes de avisar por Telegram |
| `CADENA_REAVISO_MIN` | `240` | Cada cuántos minutos re-avisar mientras la cadena siga detenida |
| `AUTO_MERGE` | `false` | Con `true`: al aprobar (done) el kit mergea la rama a la base (solo local, sin push) y deja `reviewed`; con conflicto, `stopped` y la base intacta |
| `E2E` | `false` | Etapa de pruebas E2E después del QA |
| `E2E_COMMAND_TIMEOUT` | `2400` | Segundos máximos por comando en E2E |
| `E2E_CLIENTS.<backend>` | — | Qué frontends consumen ese backend (`app1,app2`) |
| `E2E_PLATFORMS.<front>` | Flutter: `web,android`; web: `web` | En qué plataformas se prueba |
| `E2E_API.<app-flutter>` | — | `<archivo>\|<regex de la línea>\|<reemplazo con {API}>`: cómo apuntar la app al backend local |
| `E2E_API.<front-web>` | — | `env:VAR1,VAR2`: variables de URL que se apuntan al backend local |

Valores booleanos: solo `true` o `false`.

---

## Uso

```sh
/autopilot-init   # una vez por proyecto/workspace
/autopilot-plan   # idea o documento -> brainstorming -> tareas en new/ (con dependencias)
/autopilot        # arranca el bucle: espera tareas y las trabaja
```

### Entrada de tareas

Cómo llegan las tareas es **externo al autopilot**: él solo trabaja lo que hay en `new/`. Hay tres
puertas de entrada, las mismas para una persona o para una integración con un tracker:

1. `wi.sh add-task` (valida el formato, el id único y, en un workspace, el repo):

```sh
~/.local/share/autopilot-kit/wi.sh ./autopilot.env \
  add-task bug 140123 High "Login falla con Google" "descripcion" "criterio" [repo]   # repo: obligatorio en workspace
```

   El `<id>` lo das tú: número o texto (`add-task task login_social Medium ...` → rama `task-login_social`).
2. Un `.md` en `.workitems/new/` con el nombre `<tipo>-<id>-*.md` (se importa en el próximo comando).
3. La app web (*Nueva tarea*), con adjuntos.

`add-task` acepta además `--depende <clave>[,<clave>...]`, `--origen <texto>` y `@<archivo>` en lugar del
texto de la descripción o el criterio (Markdown largo sin pelear con las comillas).

**Dependencias** (`depende:`): la tarea queda en `new` y el coder no la toma hasta que **todas** sus
dependencias estén en `reviewed`. Es a propósito: la rama de la tarea nace de la rama base, que solo tiene
lo que el humano ya mergeó. El watcher las lista en `en_espera` con `depende_de`; la app web muestra
"depende de ...". Se cambian con `wi.sh <env> depende <clave> <claves>` (`-` las quita). No se aceptan
dependencias inexistentes ni ciclos.

**`/autopilot-plan`** hace todo esto por ti desde una idea o un documento: lee el código, hace un
brainstorming con preguntas hasta que no queda nada abierto (el plan se va guardando en
`.workitems/planes/<slug>.md`), propone el desglose en tareas pequeñas y verificables con sus
dependencias y una matriz de cobertura, y las crea recién cuando lo apruebas.

Una integración puede además dejar archivos en `.workitems/adjuntos/<clave>/` (aparecen como *Tarea
original*) y usar `origen:` para marcar de dónde vino la tarea (`manual` por defecto). Ejemplo completo:
[integraciones/azure](../integraciones/azure/README.md) (Azure DevOps, opcional).

En un proyecto sin `autopilot.env`, `/autopilot` dice que el proyecto no participa
y no hace nada.

### Adjuntos: capturas y videos

Los adjuntos de una tarea viven en `.workitems/adjuntos/<clave>/`: los de la tarea original (los deja
quien la crea), los que subes desde la app web (`humano/`) y los que producen coder, QA y E2E en cada
intento. El autopilot le pasa las imágenes y fotogramas (`<video>.frames/fNN.png`, porque ningún modelo
ve video) al coder, al QA y al agente E2E (`tarea.adjuntos`).

### El watcher

`/autopilot` lanza `watcher.sh`, que espera sin gastar tokens y retorna cuando hay trabajo.

- **OpenCode:** en primer plano.
- **Claude Code:** en segundo plano; Claude Code re-invoca al agente cuando el watcher termina
  (en primer plano lo cortaría a los 10 minutos).

No hay demonios que abran sesiones aparte. **Limitación:** si cerrás el cliente, deja de vigilar.

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
- **OpenCode (v2):** igual que en Claude Code. Cada tarea corre como **subagente en segundo plano**
  (herramienta `task` con `background: true`), que es una **sesión hija** de la del autopilot: la ves
  anidada debajo y podés abrirla y mirarla en vivo. El principal no la espera; OpenCode le avisa cuando
  termina, y el watcher también (el orquestador registra el id de la sesión con `wi.sh sesion`). Si
  cerrás OpenCode, esas sesiones siguen en su servicio; al volver, `/autopilot` las retoma. En OpenCode
  viejo, donde un subagente bloquea al principal, se usa `oc_sesion.py lanzar` (una sesión suelta por
  la API). **Nunca te piden permiso:** cada sesión (y cada agente de OpenCode) puede
  usar sin preguntar su copia de trabajo (`~/.cache/autopilot-kit/<puesto>/`), el kit y `/tmp`; cualquier
  otro directorio externo se **deniega** al instante. Si igual queda un pedido pendiente, el watcher lo
  rechaza solo en su siguiente vuelta, le dice al agente que siga sin eso, lo anota en el log de la
  tarea y avisa por Telegram (`⛔`).
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

Las imágenes **originales** quedan enlazadas en el `.md` de la tarea (las del coder y del QA se ven en la app web y con `get`), para verlas junto al texto en VS
Code, Obsidian o GitHub:

- las del work item (capturas y fotogramas), en `## Adjuntos` y en su lugar dentro del texto;
- las que el **coder** genera o usa, en sus notas (`adjuntos/<clave>/coder-intentoN/`);
- las **capturas del QA** (sus tests de widget), en su reporte (`adjuntos/<clave>/qa-intentoN/`).
  Se copian del worktree del QA antes de borrarlo, así no se pierden.
- las **capturas de cada paso de las pruebas E2E** (web y Android) y sus videos, en el
  `## Reporte E2E` (`adjuntos/<clave>/e2e-intentoN/`), referenciadas en el paso que muestran.

Cualquier ruta de imagen que un agente escriba en sus notas o su reporte queda como `📷 <nombre>`
(referenciada, no incrustada; si está fuera del board, primero se copia a la carpeta del intento), y el
intento termina con una línea `📎 N capturas → [<paso>-intentoN/](...)`. La app web muestra esas imágenes
en una galería plegable bajo su intento. Las tareas viejas se convierten con `wi.sh <env> limpiar-imagenes`
(o solas, la primera vez que corre el kit nuevo; antes se respalda `autopilot.db`).

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

- Los **backends corren locales**, desde las copias E2E, con `aenv.sh --e2e`. Usan el
  **`.env.autopilot.e2e`** del repo si lo creaste (p. ej. otra base u otro puerto) y, si no, el mismo
  **`.env.autopilot`** (la base de QA). Mismas reglas en los dos: BD con "qa" en el nombre, nada de
  producción. El puerto es su `PORT` (o el del `.env` si no lo define). Las pruebas crean datos en
  esa base.
- Las **apps Flutter** se apuntan a ese backend local con `e2e.sh api` (`E2E_API`: reemplaza la línea
  de la URL en la copia E2E, nunca se commitea; la URL la pone el kit: `http://localhost:<PORT>` en
  web y `http://10.0.2.2:<PORT>` en Android). Si alguien edita ese archivo después, `e2e.sh app` no
  corre.
- Los **fronts web** (BackOffice) se apuntan solos al backend local: con
  `E2E_API.<front>=env:VITE_API_BASE_URL,VITE_WEBSOCKET_URL`, `aenv.sh --e2e` reemplaza esas
  variables por `http://localhost:<PORT>` (conserva la ruta; `https`→`http`, `wss`→`ws`). Sin
  `E2E_API`, el front usa la API de su `.env.autopilot` (QA, no el backend de la tarea).
- **Internet abierto, producción bloqueada.** `e2e.py hosts_produccion` saca, para cualquier proyecto,
  los servidores de producción: destinos (URLs/hosts) de los `.env` reales de cada repo que no son local
  ni QA, URLs del archivo de `E2E_API` de cada app (p. ej. `baseUrlMain`) y `E2E_BLOCK_HOSTS`; nunca los
  que el humano permitió en `AUTOPILOT_PERMITIR`. `e2e.sh produccion <copia|autopilot.env>` los lista.
  - Navegador: `--host-resolver-rules` con `MAP <host> ~NOTFOUND` para esos hosts; el resto resuelve.
    Lo bloqueado queda en `red-bloqueada.txt`.
  - Emulador: `-http-proxy` a un proxy del kit (`proxy_e2e.py`) que deja pasar todo, rechaza esos
    hosts (por nombre y por las IPs a las que resuelven) y anota cada destino en
    `.e2e-capturas/red-emulador-<serial>.log` (`OK` / `BLOQUEADO`). `10.0.2.2` va al backend local.
- Apps, emulador y navegador solo por `e2e.sh`; el hook/permisos bloquean `flutter build/run/drive`,
  `playwright` y `emulator` directos.

Ejemplos: `examples/proyecto/cuentas-e2e.env.example` (cuentas) y
`examples/proyecto/env.autopilot.e2e.example` (opcional: otra base/puerto para un backend).

**Cuentas de prueba:** en `cuentas-e2e.env` junto a `autopilot.env` (nunca en `autopilot.env`, que
leen los agentes). Nombre libre si empieza con `E2E_`:
`E2E_CLIENTE_USER=…`, `E2E_CLIENTE_PASSWORD=…`, `E2E_ADMIN_USER=…` (un par por rol; solo cuentas
de QA que existan en la base que usa el E2E). El agente nunca las escribe en el reporte.

**Para activarlo:**

1. `~/.local/share/autopilot-kit/e2e-setup.sh` (una vez, sin sudo, ~6 GB en
   `~/.local/share/autopilot-e2e`: Java 17, Android SDK + emulador + AVD `autopilot_e2e`, Playwright +
   Chromium). No toca tu Flutter, tu Java ni `~/.android`. Si no tienes acceso a `/dev/kvm`:
   `sudo usermod -aG kvm $USER`. Para quitarlo: `rm -rf ~/.local/share/autopilot-e2e`.
2. Pon las cuentas de prueba en `cuentas-e2e.env` junto a `autopilot.env`. Revisa que el
   `.env.autopilot` de cada backend tenga `PORT` (puertos distintos entre backends). Opcional: un
   `.env.autopilot.e2e` en un backend si quieres otra base u otro puerto solo para E2E.
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
   E2E_API.Konectame_BackOffice=env:VITE_API_BASE_URL,VITE_WEBSOCKET_URL
   ```
   Con `E2E_CLIENTS`, una tarea que solo toca un backend igual se prueba desde sus apps (en su rama
   base), y una que solo toca una app levanta su backend.
4. `wi.sh <env> check` no debe dar avisos de E2E. Reinicia `/autopilot`.

Memoria: emulador (2 GB) + build de Android + backend pesan; con 8 GB de RAM deja `MAX_E2E=1`.

Comandos útiles (todos los de `wi.sh`: `wi.sh <env> help`):

```sh
K=~/.local/share/autopilot-kit
$K/e2e.sh doctor                                  # qué herramientas E2E faltan
$K/wi.sh <env> check                              # avisos: herramientas, ambientes, cuentas, E2E_API
$K/wi.sh <env> entorno <repo>                     # .env.autopilot (sin mostrar valores)
python3 $K/entorno.py <repo> --e2e                # ambiente que usa el E2E en ese repo (ok / inseguro...)
$K/wi.sh <env> validar-e2e <clave>                # ¿el último Reporte E2E alcanza para aprobar?
$K/wi.sh <env> re-e2e <clave>                     # volver a probar en E2E (tras resolver un NO CERTIFICABLE)
$K/wi.sh <env> e2e-worktree <clave>               # copias E2E para probar tú mismo (y e2e-worktree-borrar)
```

---

## Telegram

`lib/telegram.py` (atajo `telegram.sh`). Bot propio del autopilot; credenciales en
`~/.config/autopilot-kit/telegram.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, permiso 600), creadas
con `wi.sh <env> telegram-setup`. `wi.sh <env> notify-test` manda una prueba; `wi.sh <env> notify
"<texto>" [--alert]` o `telegram.sh send ...` manda un aviso.

- **Salida:** `Board.modificar` avisa cada cambio de estado; también `esperar`, el vigía (atascadas,
  colgados), run-tests (resultado o health check que bloquea) y el watcher
  (arranque con `--inicio`, y si lo detienen). Se manda en segundo plano (nunca bloquea `wi.sh`), se
  filtran los valores de todos los `.env*` y de `cuentas-e2e.env`, y los avisos repetibles (vigía,
  arranque) no se repiten en 10 minutos. `TELEGRAM_ALERTS_ONLY=true`: solo 🚨 (done, stopped, atascada,
  pruebas fallidas, watcher detenido).
- **Entrada:** en cada vuelta el watcher llama `telegram.py poll` (`getUpdates` sin espera, offset
  guardado, lock por bot para que un solo watcher lea). Solo acepta `TELEGRAM_CHAT_ID`. Los comandos
  (`/estado`, `/cola`, `/tarea`, `/health`, `/reqa`, `/re-e2e`, `/stop`, `/reviewed`, `/pausa`,
  `/seguir`, `/ayuda`) se resuelven sin IA, por `wi.sh`. El texto libre se devuelve como `mensajes` y
  el orquestador responde con `telegram.sh send`.
- **Menú de botones:** `/start`, `/ayuda` y los comandos desconocidos mandan, además de la
  documentación, un reply keyboard (`TECLADO`) con los comandos sin argumento (`/estado`, `/cola`,
  `/health`, `/pausa`, `/seguir`, `/ayuda`); tocar un botón envía ese comando como texto normal. El
  menú persiste sobre el campo de texto hasta que se reemplace o se cierre desde Telegram.
- **Cadena detenida** (`lib/cadena.py`): en cada vuelta el watcher llama `cadena.py <env>`; si el
  autopilot quedó esperando al humano (sin puestos ocupados, sin trabajo que pueda tomar solo, y con
  pendiente que solo el humano destraba: done sin revisar, stopped o bloqueadas por dependencias),
  avisa por Telegram 🚨 tras `CADENA_MIN` minutos desde que se detuvo y re-avisa cada
  `CADENA_REAVISO_MIN` mientras siga parado (una vez por episodio; en pausa explícita no avisa). El
  estado por proyecto vive en `~/.cache/autopilot-kit/cadena-<hash>.json` y la app web lo muestra
  como banner "🧊 Cadena detenida".
- **Pausa:** `/pausa` crea `.workitems/.pausa`; mientras exista, `plan()` no ofrece acciones nuevas
  (`"pausa": true`).
- **Health check:** credenciales, permisos del archivo, token válido (`getMe`) y que ningún otro
  programa lea el bot (409). `--deep` manda un mensaje de prueba. Un problema de Telegram no bloquea
  `run-tests`.

## Health check (health-check)

`~/.local/share/autopilot-kit/health-check [<clave>|smoke|--all] [--web|--android] [--deep] [--json]`
(o `wi.sh <env> health ...`). Busca `autopilot.env` en la carpeta actual o la de arriba. Sale con 1 si
hay algo que bloquea. Con una clave o `smoke`, revisa solo los repos que usan esos casos (y sus
servicios).

| Área | Qué revisa | Nivel |
|---|---|---|
| herramientas | Java, Android SDK, emulador, AVD, Playwright, Chromium | ❌ |
| kvm | acceso a `/dev/kvm`; en el grupo pero sesión vieja → usa `sg kvm` | ⚠️ / ❌ |
| config | `E2E`, fronts sin `E2E_CLIENTS`, `E2E_API` encuentra 1 línea en la rama | ⚠️ / ❌ |
| ambiente | `.env.autopilot(.e2e)` válido, `PORT` definido y distinto, puertos libres | ❌ / ⚠️ |
| cuentas | `cuentas-e2e.env` y los roles de `needs.accounts` | ❌ |
| compila | imports Dart con mayúsculas que no existen (Linux), `org.gradle.java.home` ajeno, Firebase sin web | ❌ / ⚠️ |
| casos | `cases.json` válidos, `tests/services.json` de los servicios pedidos | ❌ |
| produccion | servidores que se bloquean (aviso si no detecta ninguno) | ⚠️ |
| deep | arranca y apaga el emulador; abre Chromium | ❌ |

Cada ❌ lleva `responsable`: **`coder`** (área `compila` y `cases.json` inválido: se arregla con un commit
en la rama, aunque sea preexistente) o **`humano`** (todo lo demás). `run-tests` lo corre antes de
ejecutar (salvo `--qa` o `--skip-check`) y no corre nada si hay ❌. El agente E2E lo corre como primer
paso. El orquestador, si todos los ❌ son `coder`, devuelve la tarea con
`wi.sh rechazar|rechazar-e2e <clave> "<qué corregir>" --bloqueo`: va a `bug-fix` **sin contar como
intento** (el feedback dice "BLOQUEO PREEXISTENTE") y el aviso de Telegram es 🔧, no 🚨. Si hay algún
`humano`, la tarea va a `stopped`. QA y E2E separan en su NO CERTIFICABLE `FALTA (codigo)` de
`FALTA (humano)`, con la misma regla; el coder corrige lo preexistente que bloquea en un commit aparte.

## Pruebas de humo (tests/smoke/)

Casos que no son de una tarea (p. ej. login). Se escriben en `tests/smoke/` de una copia de trabajo y
`wi.sh <env> smoke-save <copia>` los valida (mismas reglas que los de una tarea) y los commitea en la
rama **`smoke-tests`** del repo (sale de su rama base; la mergea el humano). Un repo que solo aporta
`tests/services.json` también se guarda así. Se corren con `run-tests smoke` (en `smoke-tests` si
existe; si no, en la base) y entran en `run-tests --all` una vez mergeados.

## Casos Android (Flutter)

`tests/<clave>/<nombre>_flow.dart` (`integration_test`) con `needs.platform = "android"`. El runner,
**solo en su copia temporal**, agrega `integration_test`/`flutter_driver` a `pubspec.yaml` y el driver
del kit en `test_driver/`, apunta la app al backend local, arranca el emulador y corre
`flutter drive --target=<archivo> -d <serial> --dart-define=E2E_...` (cuentas). Capturas con
`binding.takeScreenshot`. Si un plugin nativo no responde en la prueba, el caso simula su canal con
`setMockMethodCallHandler`.

## Borradores de pruebas (QA y E2E)

Para no reescribir pruebas en cada corrida. Al borrar sus copias (`qa-worktree-borrar`,
`e2e-worktree-borrar`), si la tarea **no** quedó aprobada por ese puesto, se guardan las pruebas
**nuevas** (no versionadas) de cada copia en `.workitems/adjuntos/<clave>/borradores/<qa|e2e>/<repo>/…`
con `borrador.json` (intento, fecha, estado, archivos). Cuentan como pruebas: lo que está en `tests/`,
`.e2e/`, `integration_test/`, `test_driver/` o se llama `*.spec.*`, `*.test.*`, `*.check.*`, `*_test.dart`,
`*_flow.dart`, `*.flow.cjs`, `__qa*`. Nunca `node_modules`, `build`, capturas, `.env*`, archivos > 1 MB
(tope 10 MB). Solo el último borrador por puesto; si una corrida no dejó pruebas, se conserva el anterior.
Al aprobar (QA: la tarea quedó en `e2e`/`probando-e2e`/`done`; E2E: en `done`) el borrador de ese puesto
se borra, porque sus pruebas ya están en la rama.

`qa-worktree` / `e2e-worktree` los restauran en las copias nuevas sin pisar lo que ya trae la rama y lo
informan (`"borrador": {"de_intento", "restaurados", "ya_existian"}`); el orquestador lo pasa en el
encargo y el agente parte de ahí. `wi.sh <env> borrador <clave> [qa|e2e]` muestra qué hay.

## Casos de prueba guardados (tests/)

Al aprobar, `wi.sh aprobar` (QA) y `wi.sh aprobar-e2e` (E2E) toman `tests/<clave>/` de las copias del
agente, lo validan y lo commitean en la rama de la tarea (`test: casos de prueba de <clave>`). Si un
repo del flujo E2E no era de la tarea, le abren la misma rama. Nunca frenan la aprobación: si algo no
es válido, no se guarda y el aviso queda en `## Resultado`.

**`tests/<clave>/cases.json`** (una entrada por caso):

```json
[
  {"type": "qa", "file": "tests/bug-37269/popular.check.ts",
   "command": "npx jest --rootDir . --testRegex 'tests/bug-37269/.*\\.check\\.(t|j)s$'",
   "criterion": "El detalle muestra el mismo estado que Editar", "needs": {"db": true}},
  {"type": "e2e", "file": "tests/bug-37269/detalle-popular.flow.cjs", "project": "web-escritorio",
   "criterion": "…", "needs": {"services": ["Konectame_BackOffice_BE", "Konectame_BackOffice"],
   "platform": "web", "accounts": ["E2E_BO_ADMIN"]}}
]
```

- `needs.db`: el comando va por `aenv.sh` (con `.env.autopilot`). Sin eso, la copia no tiene ningún
  `.env` y no se conecta a nada.
- E2E web: se corre con `e2e.sh web` (navegador sin red externa, video). Recibe `BASE_URL` (la del
  servicio de su repo), las cuentas `E2E_*` y `SCREENSHOTS_DIR` por variables de entorno.
- E2E android: `command` con `{device}` (el serial del emulador); se corre con `e2e.sh app`.

**`tests/services.json`** (uno por repo): `{"start": "...", "ready_url": "http://localhost:3001/…",
"ready_timeout": 300}`. `start` corre con `aenv.sh --e2e`; se espera a que `ready_url` responda.

**Validación al guardar** (si falla, no se guarda):
- `cases.json` válido y cada `file` dentro de `tests/<clave>/`;
- nombres que el runner del proyecto no toma: nada de `*.spec.*`, `*.test.*`, `*_test.dart`,
  `*.e2e-spec.ts` (se usan `*.check.ts|js`, `*_check.dart`, `*.flow.cjs`, `*_flow.dart`), y además
  `jest --listTests` del repo no debe listarlos;
- sin rastro del sistema (`autopilot`, `aenv.sh`, `e2e.sh`, `E2E_PASOS`, `.workitems`, `~/.cache/autopilot…`);
- sin `.env*`, sin enlaces simbólicos, sin valores de `cuentas-e2e.env`.

**Correrlos:** `wi.sh <env> test <clave>|--all [--qa|--e2e] [--ref <rama>]`, o el atajo
`~/.local/share/autopilot-kit/run-tests` (busca `autopilot.env` en la carpeta actual o la de arriba).
Una tarea usa su rama (o la base si ya no existe); `--all` usa la rama base de cada repo. Crea copias
en `~/.cache/autopilot-kit/run/`, instala dependencias, levanta los servicios, corre, apaga y borra
todo. Reporte en `<workspace>/test-results/<fecha>-<clave|all>.md` con capturas; sale con 1 si algo falla.

---

## Comandos de wi.sh

`wi.sh` es la única vía para cambiar el board (el watcher y los agentes la usan). Uso:
`~/.local/share/autopilot-kit/wi.sh <ruta/autopilot.env> <comando>`.

```
uso: wi.sh <env> <comando> [args]
  init                                   crea las carpetas del board y log.md
  in-progress|qa|validando|bugfix|done|new <clave>
  reviewed   <clave>                     done -> reviewed: el humano ya reviso la tarea
  merge      <clave>                     con AUTO_MERGE=true: mergea su rama a la base (solo local,
                                         nunca push ni borra ramas) y la deja reviewed; con conflicto
                                         queda stopped y la base intacta
  merge      <clave> --humano            SOLO el humano (app web): igual pero sin AUTO_MERGE y, si falla,
                                         la tarea no cambia de estado
  push       <clave> base|rama           SOLO el humano: sube a origin la base o la rama de cada repo de la
                                         tarea (done/reviewed), nunca --force
  pull-bases <clave>                     SOLO el humano: trae lo ultimo de origin a la rama base de cada
                                         repo de la tarea (fast-forward; nunca merge, rebase ni push)
  pr         <clave>                     SOLO el humano: sube la rama y abre un PR contra la base en cada repo
                                         con commits (GitHub con gh, Azure DevOps con AZURE_DEVOPS_PAT)
  git-estado <clave> [--fetch]           commits, archivos (+/-), integrada y remoto por repo (JSON)
  git-diff   <clave> <repo> <archivo>    diff de un archivo de la tarea contra la base
  stopped    <clave> <motivo>
  rama       <clave> nueva|existente [--repo <carpeta>]
                                         crea/cambia a la rama <clave> desde la base de su repo
                                         (nueva: antes trae lo ultimo de origin/<base>, sin merges).
                                         --repo (workspace): abre la MISMA rama en otro repo
                                         declarado y lo suma a la tarea (lo usa el coder)
  repos      <clave>                     repos de la tarea (principal + extra) en JSON
  repos-modificados <clave>              desde git: commits y archivos por repo (JSON). Al pasar a qa
                                         se escribe en la seccion '## Repos modificados' de la tarea
  resultado  <clave> <texto>
  motivo     <clave> <texto>
  feedback   <clave> <texto>             agrega al historial de Feedback de QA
  criterio   <clave> <texto>
  descripcion <clave> <texto>  ·  titulo <clave> <texto>  ·  prioridad <clave> <Critical|High|Medium|Low>
  adjuntar   <clave> <archivo>...        copia archivos a adjuntos/<clave>/humano/ y los registra
  get        <clave> [parte] [--intento N] [--ultimo] [--json]
                                         lee solo lo que necesitas de una tarea (menos tokens que el .md).
                                         parte: resumen (defecto: descripcion y criterio completos + adjuntos +
                                         lo ultimo de cada historial), descripcion, criterio, adjuntos, notas,
                                         qa, e2e, feedback, historial (indice), resultado, motivo, todo
  migrate                                pasa el tablero de .md a la base (se hace solo la primera vez; deja
                                         respaldo de los .md en .workitems/.respaldo-md-<fecha>/)
  intentos   <clave> <n>
  certificar <clave> <intento_nuevo>     qa -> validando, fija Intento
  aprobar    <clave>                     validando -> done (con E2E=true: -> e2e, la cola de pruebas E2E)
  rechazar   <clave> <feedback> [--bloqueo]   validando -> bug-fix. --bloqueo: algo preexistente que se
                                         arregla en codigo impide compilar/probar; no cuenta como intento
  reqa       <clave>                     -> qa, Intento a 0 (conserva el historial)
  pedir-cambios <clave> <texto> [--a coder|qa|e2e]
                                         SOLO el humano: done/reviewed/stopped -> bug-fix (coder, defecto),
                                         qa o e2e con su pedido (en el feedback de ese puesto y en el
                                         Criterio de aceptacion); Intento a 0 salvo e2e
  probar-e2e <clave>                     e2e -> probando-e2e (ocupa el puesto e2e)
  e2e-worktree <clave>                   copias para el E2E: repos de la tarea (su rama) + los que
                                         hacen falta para el flujo real (E2E_CLIENTS, en su base)
  e2e-worktree-borrar <clave>            (mata lo que haya quedado corriendo: backend, web, emulador)
  reporte-e2e <clave> <texto|-> [--imagenes <dir>]...  reporte del E2E con sus capturas
  validar-e2e <clave>                    revisa el ultimo Reporte E2E (JSON): criterios CUMPLE con capturas
  aprobar-e2e <clave>                    probando-e2e -> done, SOLO si validar-e2e da ok
  rechazar-e2e <clave> <feedback> [--bloqueo]   probando-e2e/e2e -> bug-fix (Feedback de E2E); --bloqueo igual
  re-e2e     <clave>                     -> e2e otra vez (p. ej. tras resolver un NO CERTIFICABLE)
  telegram-setup                         conecta el bot del autopilot a tu chat (interactivo, en tu terminal)
  notify-test                            manda un mensaje de prueba por Telegram
  notify     <texto> [--alert]           manda un aviso por Telegram (respeta TELEGRAM=true)
  smoke-save <copia>                     guarda tests/smoke/ de una copia de trabajo en la rama smoke-tests
                                         del repo (pruebas de humo: no son de una tarea)
  health     [<clave>|smoke|--all] [--web|--android] [--deep]
                                         health check E2E: que falta ANTES de correr. Alias: health-check
  test       <clave>|smoke|--all [--qa|--e2e] [--web|--android] [--ref <rama>]
                                         vuelve a correr los casos guardados en los repos
                                         (tests/<clave>/cases.json); --all = regresion en las ramas base.
                                         Reporte en <workspace>/test-results/. Alias: run-tests
  add-task   <task|bug> <id> <prioridad> <titulo> <descripcion> <criterio> [repo]
             [--depende <clave>[,<clave>...]] [--origen <texto>]
                                         (en un workspace, repo es obligatorio: la carpeta del repo)
                                         descripcion/criterio: @<archivo> lee el texto de ese archivo
  depende    <clave> <clave>[,<clave>...]|-
                                         la tarea no se toma hasta que esas esten en reviewed
                                         (mergeadas en la base); '-' quita las dependencias
  check                                  avisos de configuracion (ramas base vacias, repos faltantes,
                                         herramientas, .env.autopilot)
  entorno    <repo|clave>                valida el .env.autopilot (local/QA) sin mostrar valores
  log        <evento> <origen> <tipo> <tarea> <rama> <commit> <detalle>
  query      [estado]                    JSON con las tareas
  plan       [--recuperar]               lo que usa el watcher (--recuperar: solo al iniciar)
  sesion     <clave> <ses_id>            registra la sesion de OpenCode que trabaja la tarea
  notas-dev  <clave> <texto|-> [--imagenes <dir>]...   notas del coder (- = stdin)
  reporte-qa <clave> <texto|-> [--imagenes <dir>]...   reporte del QA (- = stdin)
                                         Las imagenes mencionadas en el texto (y las de --imagenes)
                                         se copian a adjuntos/<clave>/ y quedan como ![..](..) en el .md
  qa-worktree        <clave>             copia de trabajo aislada para el QA (en la punta de la rama). Si
                                         hay borrador de pruebas de una corrida anterior, lo pone en la copia
  borrador   <clave> [qa|e2e]            borrador de pruebas guardado (JSON): los tests de un QA/E2E que no
                                         aprobo se guardan al borrar sus copias y se reusan en la proxima
  coder-worktree-borrar <clave>          quita los worktrees del coder y libera sus reservas
  reservar   <clave> <archivo>...        reserva archivos para la tarea (ruta en su worktree o relativa
                                         al repo principal); falla si otra tarea activa los tiene
  solapes    <clave>                     archivos que la tarea comparte con otras activas (JSON)
  esperar    <clave> <otra>              choco con <otra>: vuelve a la cola hasta que <otra> termine
  qa-worktree-borrar <clave>

<clave> = task-<id> | bug-<id>   (es tambien el nombre de la rama; <id>: numero o texto, [a-z0-9_])
```

Otros scripts en `~/.local/share/autopilot-kit/`: `aenv.sh [--e2e] <repo> -- <cmd>` (corre con
`.env.autopilot` validado), `e2e.sh --help` (herramientas del agente E2E), `e2e-setup.sh`,
`vigia.py <env> --simular`, `autopilot-web [--lan] [--port N]`.

---

## App web (`autopilot-web`)

Servidor Python sin dependencias (`lib/web/servidor.py`) con la interfaz incluida en el kit (sin CDN).
Muestra todos los proyectos donde se usó el kit: cada `wi.sh` registra su `autopilot.env` en
`~/.config/autopilot-kit/proyectos.json`.

**Desde el cliente:** la skill `/autopilot-web` (`skills/autopilot-web/SKILL.md`) la arranca
desacoplada (`setsid nohup`, vive sin el cliente), verifica que responde, y si ya hay una
instancia reporta URL/PID/modo y pregunta antes de detenerla o rearrancarla. Argumentos:
`lan` (`--lan`), `puerto <n>` (`--port`), `detener` (mata solo un PID del kit y solo si el
usuario lo pidió).

- **Ver:** tablero (columnas vacías ocultas por defecto), detalle con historial por intento, adjuntos
  agrupados por paso (con filtro por agente), log, reportes de `test-results/`, estado del watcher y
  de la pausa.
- **Gestionar / editar:** cada botón llama a `wi.sh` (mismas validaciones, log y avisos de Telegram).
- **Panel Git** (detalle de la tarea): `GET /api/p/<id>/git/<clave>[?fetch=1]` (`git-estado`) y
  `GET /api/p/<id>/diff/<clave>?repo=&archivo=` (`git-diff`, recortado a 200 KB) para ver; `POST
  /api/p/<id>/git` con `op` = `merge` (`merge --humano`), `push-base`, `push-rama` o `pr` para actuar
  (solo con la tarea en `done`/`reviewed`; el resultado se muestra por repo), y `pull-base`
  (`pull-bases`, en cualquier estado): fast-forward de la base de cada repo desde `origin`, con la
  misma lógica que se usa antes de crear una rama. El git que habla con el
  remoto corre sin preguntas (`GIT_TERMINAL_PROMPT=0`): usa las credenciales que ya tenga tu git. Los
  PR de Azure DevOps usan `AZURE_DEVOPS_PAT` (entorno → `azure-sync.secrets.env` del proyecto →
  `~/.config/autopilot-kit/ado-mcp.secrets.env`), que va a curl por stdin, nunca en argv. Las URLs de
  los PR quedan en la sección `## Pull requests` de la tarea. `git-guard.sh` bloquea a los agentes
  `wi.sh push`, `pr`, `pull-bases` y `merge --humano`.
  Los adjuntos subidos van a `adjuntos/<clave>/humano/`; nunca se aceptan archivos `.env*`.
- **Correr:** `health-check` y `run-tests` como trabajos en segundo plano (uno de cada
  tipo por proyecto a la vez), con su salida.

**Seguridad:** sin `--lan` escucha solo en `127.0.0.1`. Con `--lan` escucha en la red y pide la clave
de `~/.config/autopilot-kit/web.env` (600, se genera sola); la sesión es una cookie
`HttpOnly; SameSite=Strict`. Toda acción (POST) exige el encabezado `X-Autopilot: 1` (contra CSRF). Solo
sirve archivos dentro de `.workitems/` y `test-results/` (nunca la base ni `.env*`); los SVG se
descargan en vez de mostrarse; la salida pasa por el mismo filtro de secretos que Telegram. Va sin
HTTPS: úsala solo en una red de confianza.

---

## Qué incluye

```
dotenvs/
├── install.sh                  # instala para OpenCode y/o Claude Code; --init prepara proyectos
├── lib/                        # -> ~/.local/share/autopilot-kit/  (compartido por ambos clientes)
│   ├── workitems.py            # el board (unica implementacion); vistas .md y migracion
│   ├── almacen.py              # la base SQLite del board (autopilot.db)
│   ├── web/, autopilot-web     # app web: ver, gestionar, crear y correr (stdlib + JS, sin CDN)
│   ├── wi.sh                   # unica via de escritura del board + ramas
│   ├── watcher.sh              # sensor: lee el board y retorna
│   ├── init.py                 # prepara un repo o workspace (lo usa /autopilot-init)
│   ├── git-guard.sh            # bloquea push/merge (hooks de Claude Code)
│   ├── aenv.sh / entorno.py    # nunca contra produccion: corre con .env.autopilot(.e2e) validado
│   ├── vigia.py                # vigilante: procesos colgados/huerfanos, tareas atascadas
│   ├── e2e.sh / e2e.py         # agente E2E: apps al backend local, internet abierto con produccion bloqueada
│   ├── proxy_e2e.py            # proxy del emulador: deja pasar internet, rechaza produccion
│   ├── salud.py, health-check  # health check E2E: que falta ANTES de correr
│   ├── telegram.py, telegram.sh # avisos por Telegram y comandos desde el chat
│   ├── e2e-setup.sh            # instala Java, Android SDK + emulador + AVD, Playwright (una vez, sin sudo)
│   ├── pruebas.py, run-tests   # vuelve a correr los casos guardados en los repos (tests/<clave>/)
│   └── e2e-playwright.config.cjs, e2e-pasos.cjs, e2e_driver.dart   # capturas en cada paso (web/Android)
├── skills/                     # -> carpeta de skills de cada cliente
│   ├── autopilot/SKILL.md      # reglas, maquina de estados, arranque por cliente
│   ├── autopilot-init/SKILL.md # /autopilot-init
│   ├── autopilot-plan/SKILL.md # /autopilot-plan: idea o documento -> brainstorming -> tareas
│   └── autopilot-web/SKILL.md  # /autopilot-web: arranca y gestiona la app web
├── agents/                     # fuente unica de los subagentes
│   ├── coder.md
│   ├── qa-reviewer.md
│   └── e2e-tester.md           # pruebas E2E en web y Android (con E2E=true)
├── clients/render.py           # genera agentes/comandos/guardas para cada cliente
├── examples/proyecto/          # autopilot.env, cuentas-e2e.env, .env.autopilot.e2e (ejemplos)
└── integraciones/              # opcionales y externas al autopilot: cargan tareas en el board
    └── azure/                  # Azure DevOps: azure-sync.py, skill /azure-sync, MCP (instalar.sh aparte)
```

### Qué se instala en cada cliente

| | OpenCode | Claude Code |
|---|---|---|
| Skills | `~/.config/opencode/skills/` | `~/.claude/skills/` |
| Subagentes | `~/.config/opencode/agents/*.md` | `~/.claude/agents/*.md` |
| `/autopilot-init`, `/autopilot-plan`, `/autopilot`, `/autopilot-web` | comandos en `~/.config/opencode/commands/` | las propias skills |
| Bloqueo de push/merge en subagentes | `permission.bash` con `deny` | hook `PreToolUse` → `git-guard.sh` |
| Bloqueo en el agente principal (por proyecto) | `opencode.json` del proyecto | `.claude/settings.local.json` (deny + hook) |
| Cómo espera el watcher | primer plano | segundo plano (`run_in_background`): Claude Code te re-invoca al terminar |
| Herramientas E2E (opcional, `e2e-setup.sh`) | `~/.local/share/autopilot-e2e/` | la misma carpeta |

Los agentes se escriben **una vez** en `agents/`; `clients/render.py` genera la versión de cada
cliente. Todo lo generado lleva una marca y `--uninstall` solo borra lo que tiene la marca.

---

## Seguridad

- El kit **no contiene secretos**. Solo plantillas.
- `.gitignore` bloquea `*.env`, `*.secrets.env` y los `.log`.
- En los proyectos, `.env.autopilot`, `.env.autopilot.e2e` y `cuentas-e2e.env` los crea solo el humano; ningún agente
  los crea, edita ni imprime sus valores. En modo un repo se ignoran en `.git/info/exclude`.
- Las cuentas de prueba del E2E son solo de QA y nunca se escriben en reportes ni capturas.
- Los tokens **nunca** se hardcodean: van en variable de entorno o en `*.secrets.env` / `~/.config/autopilot-kit/`.
