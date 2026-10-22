# Autopilot

Agentes de IA que **trabajan tus tareas solos** mientras tú revisas y mergeas.

Tú pones tareas en el tablero `.workitems/` (a mano o con cualquier integración que las
traiga de afuera, p. ej. Azure DevOps). **Orca** crea un `git worktree` por tarea y
lanza al coder; cuando termina, tú revisas:

```
 tarea (new) ──> CODER ─────> done
                 en su rama   presentada   tú la revisas: si está bien, queda;
                                           si pedís cambios, vuelve a new con feedback
```

- Funciona con **Claude Code**, **OpenCode** y **pi** (pi-coding-agent), y con **Orca**
  como runtime de orquestación.
- Cada tarea tiene **su propia rama** (`bug-140123`, `task-login_social`). **Nunca hace
  push**: eso lo haces tú. El merge a la base lo haces tú también (a mano, o activás
  `AUTO_MERGE=true` y el kit lo hace por vos al aprobar, solo local y sin push).
- **Nunca toca producción.** Lo que se conecta a una BD o API se ejecuta con
  `aenv.sh`, que valida el `.env.autopilot` que tú creaste.
- **Sin QA ni E2E:** el humano **eres tú**. El coder deja sus notas y las pruebas que
  corrió; la certificación final es tu revisión de la tarea en `done`.
- El board son **carpetas + archivos `.md`** (sin base de datos): el estado es la
  carpeta y la tarea, el archivo.

---

## Empezar (una sola vez)

**1. Instalar el kit (LOCAL, por proyecto).** El kit se instala **dentro de la carpeta
del proyecto** donde lo corras: no toca tu config global (por eso solo funciona
donde se instaló). Baja el repo del kit una vez y úsalo para instalar en cada proyecto:

```sh
git clone https://github.com/Germoso/azure_devops_coding_autopilot.git ~/code/autopilot
cd ~/code/autopilot
./install.sh --local ~/code/konectame   # o: cd ~/code/konectame && bash ~/code/autopilot/install.sh
```

Dentro del proyecto se crea `.autopilot/` (validadores `aenv.sh`+`entorno.py`, skills,
agente fuente) y el enrutado por cliente `.pi/`, `.opencode/` y/o `.claude/`. Nada se
commitea. Otras carpetas siguen sin autopilot.

**2. Preparar tu proyecto.** Abre Claude Code, OpenCode o pi **en la carpeta del proyecto** y escribe:

```
/autopilot-init
```

Detecta si es un repo o una carpeta con **varios repos** (`konectame/` con apps, backends
y BackOffice), te pregunta de qué rama salen las ramas de las tareas y crea `autopilot.env`
y el board `.workitems/`.

**3. Darle un ambiente seguro** a cada repo que use base de datos o APIs (a mano, una vez):

```sh
cd Konectame_BackOffice_BE
cp .env .env.autopilot      # y dentro cambia la base de datos y las URLs a las de QA
```

La base de datos **tiene que decir "qa" en su nombre**. Si no, el autopilot no ejecuta nada ahí.

**4. Registrar el repo en Orca** (necesario para que Orca cree worktrees y lance al coder):

```sh
orca status                  # si no está corriendo: orca open
orca repo add --path ~/code/konectame   # una vez por repo (o por la carpeta del workspace)
orca account list            # debe haber al menos un agente (si no: orca account add)
```

**5. Listo.**

---

## Usarlo (día a día)

```
/autopilot-plan   convierte una idea o un documento en tareas (te pregunta hasta tenerlo claro)
/autopilot        arranca: toma las tareas y las trabaja con Orca
```

**De una idea a tareas:** `/autopilot-plan` y le pasas la idea o la ruta de un documento
(PRD, notas, mockups). Primero lee el código y hace un brainstorming contigo, con preguntas,
hasta que no quede nada ambiguo; después propone las tareas (con criterios de aceptación
**que tú puedas verificar** y el orden entre ellas) y, cuando las apruebas, las crea en
`new/`. El plan queda en `.workitems/planes/`. Si una tarea depende de otra, el autopilot
no la empieza hasta que la otra esté en `done` (aprobada por ti).

Las tareas también entran al tablero poniendo un `.md` en `.workitems/new/`
(`task-<id>-<slug>.md` o `bug-<id>-<slug>.md`). Cómo llegan es cosa tuya: si vienen de un
tracker, una integración las carga por esos mismos caminos (hay una de ejemplo para Azure
DevOps en [integraciones/azure](integraciones/azure/README.md)).

Mientras `/autopilot` corre, mira la carpeta **`.workitems/`** de tu proyecto. Cada tarea se
ve como un `.md` y **la carpeta donde está te dice cómo va**:

| Carpeta | Qué significa | ¿Tienes que hacer algo? |
|---|---|---|
| `new` | Pendiente (incluye las que vuelves con feedback) | No |
| `working` | El coder la está programando | No |
| **`done`** | **El coder terminó. Lista para tu revisión (y estado final si la apruebas)** | **Sí: revísala** |
| **`stopped`** | **No se pudo y dice por qué: necesita tu intervención** | **Sí: lee el `## Motivo de stopped` y resuélvelo** |

(Solo son 4 carpetas de estado. Las `stopped` no se relanzan solas: las resuelves tú
y, cuando puedas, las vuelves a `new/`.)

### Qué haces tú

- **Tareas en `done`:** abre el `.md` de la tarea y mira:
  - *Repos modificados*: qué ramas mergear y en qué repos;
  - *Notas del desarrollador*: qué hizo, por qué y **cómo probarlo**;
  - *Pruebas que corriste*: los comandos y su resultado.

  Si te convence, **mergea la rama** a la base (la tarea queda en `done`, es el estado
  final). Si no, escribe tu feedback como sección `## Feedback del humano` en el `.md` y
  muévelo a `new/`: el coder la retoma en la misma rama y la vuelve a dejar en `done`.

  **Opcional — `AUTO_MERGE=true`:** si no querés mergear a mano, activá `AUTO_MERGE=true`
  en `autopilot.env`: cuando le digas `aprobá <clave>` a `/autopilot`, el sistema mergea la
  rama a la base por vos **solo local** (nunca hace push ni borra ramas) y la tarea queda en
  `done`. Si el merge no entra limpio (conflicto), la base queda intacta y la tarea pasa a
  `stopped/` con el motivo del conflicto.

- **Tareas en `stopped`:** el motivo está en el `.md` (*Motivo de stopped*), con lo que
  recomienda hacer. Cuando lo resuelvas, devuélvela a la cola moviéndola a `new/`
  (o decíselo al orquestador en el chat: la mueve él).

- **Crear una tarea a mano:** pon un `.md` en `.workitems/new/` llamado
  `bug-<id>-<título>.md` o `task-<id>-<título>.md`. El `<id>` lo eliges tú: un número
  (`140123`) o un texto (`login_social`: minúsculas, dígitos y `_`, sin `-`). Es también
  el nombre de la rama.

> Si cierras Claude Code / OpenCode / pi, el autopilot se detiene. Al volver, escribe
> `/autopilot` otra vez (Orca retoma los worktrees que quedaron).

---

## Qué hace cada agente

**Coder** — Lee la tarea completa (con sus capturas y videos), la programa en el worktree
de Orca de su rama y commitea. Si hace falta tocar otro repo del proyecto (p. ej. el
backend), Orca abre la misma rama ahí. Al terminar deja sus notas: qué hizo, por qué,
cómo probarlo y qué pruebas corrió. Tres resultados:

- `done` → la tarea pasa a `done/` esperando tu revisión.
- `EN ESPERA` + `CHOCA CON <otra>` → otro workitem está tocando un archivo que necesita;
  se retoma cuando la otra termine (no cuenta como no-fallo: es colisión de paralelo).
- `STOPPED` → no pudo (le falta una herramienta, o **posible producción**) y te dice qué.
  La tarea va a `stopped/` con `## Motivo de stopped` y no se relanza sola: la resuelves tú.

**Tú (revisor)** — Reemplazas al QA: revisas cada criterio de `done`, mergeas su rama, o le
pides cambios (la tarea vuelve a `new/` y el coder la retoma con tu feedback).

Los agentes **no pueden** hacer push, merge, borrar ramas ni tocar tus archivos `.env`.
Está bloqueado de verdad, no es solo una instrucción (reglas de permisos de cada cliente).

---

## Seguridad: nunca producción

- Los agentes solo se conectan a bases de datos o APIs usando **`aenv.sh`**, que valida el
  `**.env.autopilot`** que **creas tú**.
- Antes de cada uso se revisa: todo debe ser **local o QA** (la base de datos debe decir
  "qa" en su nombre y `NODE_ENV` no puede ser `production`).
- Si algo parece producción, **no se ejecuta**: la tarea va a `stopped` diciendo qué vio y
  qué recomienda.
- Ningún agente crea, edita ni muestra tus `.env`.

Revisar si un repo está bien configurado (no muestra valores):

```sh
<proyecto>/.autopilot/entorno.py Konectame_BackOffice_BE
```

(El coder usa `$K/aenv.sh` y `$K/entorno.py` con `$K = <proyecto>/.autopilot`, el kit
local de esa carpeta.)

¿Un servicio externo que no tiene versión de QA (p. ej. una pasarela de pagos de pruebas)?
Permítelo a propósito en tu `.env.autopilot`: `AUTOPILOT_PERMITIR=AZUL_PAYMENT_URL`.

---

## Ajustes

Todo está en **`autopilot.env`**, en la carpeta de tu proyecto. Lo más común:

| Quiero… | Cambia |
|---|---|
| Cambiar la rama de la que salen las tareas | `REPO.<repo>=<rama>` (o `BASE_BRANCH=` si es un solo repo) |
| Más de un coder a la vez | `PARALLEL=true`, y `MAX_CODERS` |
| Que el kit mergee al aprobar yo | `AUTO_MERGE=true` |
| Que un comando pueda tardar más | `COMMAND_TIMEOUT=900` (segundos) |

Con 8 GB de RAM y Flutter, lo razonable es **1 coder** (`PARALLEL=false`, el valor por
defecto). Todas las variables: [docs/REFERENCIA.md](docs/REFERENCIA.md#autopilotenv).

---

## Trabajo en paralelo y colisiones

Con `PARALLEL=true` pueden trabajar varios coders a la vez (hasta `MAX_CODERS`). Cada
uno está en su propio worktree y su propia rama, pero **dos workitems no pueden tocar el
mismo archivo a la vez**: si un coder necesita un archivo que otro workitem activo ya tocó,
termina con `EN ESPERA` (+ `CHOCA CON <clave>`) y tu orquestador lo retoma en su mismo
worktree cuando el otro termine. No es un fallo: es la forma de no patearse los archivos.

Para evitar esperas, planificá tareas independientes que no toquen los mismos archivos
(lo que `/autopilot-plan` tiene en cuenta).

---

## Problemas comunes

| Veo… | Qué hago |
|---|---|
| `stopped` con *POSIBLE PRODUCCIÓN* o *falta .env.autopilot* | Revisa el `.env.autopilot` de ese repo (la base debe decir "qa") y devuelve la tarea a `new/` |
| `stopped` con *no existe la rama base* | Corrige `REPO.<repo>=` en `autopilot.env` |
| `stopped` con *falta herramienta* | Instala lo que dice (p. ej. `fvm`, `flutter`, `node`) y devuelve la tarea |
| Nada avanza | ¿Está corriendo `/autopilot` y **Orca** (`orca status`)? Si cerraste el cliente, lánzalo otra vez |
| El coder no arranca | ¿Hay agente en `orca account list`? ¿El repo está en `orca repo list`? |
| No se ejecuta nada contra BD/API | `entorno.py <repo>` para ver qué falta en `.env.autopilot` |

---

## Más información

- **[docs/REFERENCIA.md](docs/REFERENCIA.md)** — todo el detalle: estados, variables, el
  bucle del orquestador, cómo crear tareas desde afuera, trabajo en paralelo, Orca por
  dentro y estructura del kit.
- Actualizar el kit de un proyecto: `cd ~/code/autopilot && git pull && ./install.sh --local ~/code/konectame` (re-usa la misma ruta).
- Desinstalar de un proyecto (solo esa carpeta): `cd ~/code/autopilot && ./install.sh --uninstall --local ~/code/konectame`.
- Quitar una copia GLOBAL vieja (de versiones anteriores del kit): `./install.sh --uninstall`.