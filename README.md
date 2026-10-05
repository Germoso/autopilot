# Autopilot

Agentes de IA que **trabajan tus tareas solos** mientras tú revisas y mergeas.

Tú pones tareas en el tablero (a mano, desde la app web o con cualquier integración que las traiga de
afuera). El autopilot las toma una por una:

```
 tarea nueva ──> CODER ────────> QA ─────────────> E2E (opcional) ─────> LISTA
                 la programa     la prueba y       la usa como una        tú la revisas
                 en su rama      la certifica      persona (web/Android)  y mergeas
```

- Funciona con **Claude Code** y **OpenCode**.
- Cada tarea tiene **su propia rama** (`bug-140123`, `task-login_social`). **Nunca hace push**: eso lo haces tú. El merge a la base lo haces tú también (desde la app web con un botón, a mano, o activás `AUTO_MERGE=true` y el kit lo hace por vos al aprobar, solo local y sin push).
- **Nunca toca producción.** Solo usa los ambientes de QA que tú le das.
- Todo queda escrito en un archivo `.md` por tarea: qué hizo el coder, qué probó el QA, capturas.

---

## Empezar (una sola vez)

**1. Instalar el kit**

```sh
git clone https://github.com/Germoso/azure_devops_coding_autopilot.git ~/code/dotenvs
cd ~/code/dotenvs
./install.sh
```

**2. Preparar tu proyecto.** Abre Claude Code u OpenCode **en la carpeta del proyecto** y escribe:

```
/autopilot-init
```

Te pregunta de qué rama salen las ramas de las tareas (p. ej. `qa` o `dev`) y crea todo. Sirve
para un repo o para una carpeta con **varios repos** (p. ej. `konectame/` con apps, backends y
BackOffice).

**3. Darle un ambiente de QA** a cada repo que use base de datos o APIs (a mano, una vez):

```sh
cd Konectame_BackOffice_BE
cp .env .env.autopilot      # y dentro cambia la base de datos y las URLs a las de QA
```

La base de datos **tiene que decir "qa" en su nombre**. Si no, el autopilot no ejecuta nada ahí.

**4. Listo.**

---

## Usarlo (día a día)

```
/autopilot-plan   convierte una idea o un documento en tareas (te pregunta hasta tenerlo claro)
/autopilot        arranca: toma las tareas y las trabaja
```

**De una idea a tareas:** `/autopilot-plan` y le pasas la idea o la ruta de un documento (PRD, notas,
mockups). Primero lee el código y hace un brainstorming contigo, con preguntas, hasta que no quede nada
ambiguo; después propone las tareas (con criterios de aceptación que el QA puede verificar y el orden entre
ellas) y, cuando las apruebas, las crea en `new/`. El plan queda en `.workitems/planes/`. Si una tarea
depende de otra, el autopilot no la empieza hasta que mergees la otra y la marques como revisada.

Las tareas también entran al tablero por la app web (*Nueva tarea*), con `wi.sh autopilot.env add-task ...` o
poniendo un `.md` en `.workitems/new/`. Cómo llegan es cosa tuya: si vienen de un tracker, una
integración las carga por esos mismos caminos (hay una de ejemplo para Azure DevOps en
[integraciones/azure](integraciones/azure/README.md)).

Mientras `/autopilot` corre, abre la **[app web](#app-web)** o mira la carpeta **`.workitems/`** de tu
proyecto. Cada tarea se ve como un archivo `.md` y **la carpeta donde está te dice cómo va**:

| Carpeta | Qué significa | ¿Tienes que hacer algo? |
|---|---|---|
| `new` | Pendiente | No |
| `in-progress` | El coder la está programando | No |
| `qa` / `validando` | Esperando al QA / el QA la está probando | No |
| `e2e` / `probando-e2e` | Pruebas E2E (solo si las activaste) | No |
| `bug-fix` | El QA encontró un problema; el coder lo corrige | No |
| **`done`** | **Terminada y certificada** | **Sí: revísala y mergea su rama** |
| **`stopped`** | **No se pudo; dice por qué** | **Sí: lee el motivo y resuélvelo** |
| `reviewed` | Ya la revisaste | No (la mueves tú desde `done`) |

### Qué haces tú

- **Tareas en `done`:** ábrela (en la app web o su `.md`) y mira:
  - *Repos modificados*: qué ramas mergear y en qué repos;
  - *Notas del desarrollador*: qué hizo y por qué;
  - *Reporte de QA*: qué probó y **cómo probarlo tú a mano**.

  Si te convence, mergea la rama. Después márcala como revisada (botón en la app web, o mueve el
  archivo a `reviewed/`).

  **Todo desde la app web — panel Git de la tarea:** por cada repo ves la rama contra su base, los
  commits y los archivos cambiados (+/−); clic en un archivo para ver su diff. Con la tarea en `done`
  o `reviewed` tienes los botones:
  - **⤵ Mergear a la base**: merge local en cada repo (sin push); si sale bien la tarea pasa a
    `reviewed` y la rama se conserva. Si hay conflicto, la base queda intacta y la tarea no cambia.
  - **⬆ Push de la base**: sube a `origin` la base que mergeaste (nunca `--force`; si el remoto
    avanzó, te lo dice).
  - **⬆ Crear PR**: sube la rama y abre un Pull Request contra la base en cada repo con cambios.
    GitHub con `gh`; **Azure DevOps** con el PAT `AZURE_DEVOPS_PAT` (en `azure-sync.secrets.env`
    del proyecto o en `~/.config/autopilot-kit/ado-mcp.secrets.env`, permiso *Code: Read & Write*).
    El link al PR queda en la tarea.
  - **↻ Actualizar** hace `git fetch` y recalcula.

  **¿Hace falta otra vuelta?** (esté en `done`, `reviewed` o `stopped`): en la app web, abre la tarea
  y pulsa **💬 Feedback y devolver**. Elige **a quién se la devuelves** y escribe tu feedback (y, si
  quieres, adjunta capturas):
  - **Coder**: qué está mal, qué esperas y dónde. Vuelve al coder **en la misma rama** y pasa otra
    vez por QA (y E2E).
  - **QA**: qué tiene que verificar o cómo probarlo (datos, pasos, casos). Vuelve a la cola de QA,
    que la certifica otra vez con tus indicaciones; si algo no cumple, va al coder.
  - **E2E** (con `E2E=true`): qué flujo probar de punta a punta, con qué datos o en qué plataforma.
    Vuelve a la cola de E2E.

  Tu feedback queda como el último de ese puesto y se suma al criterio de aceptación, así QA y
  E2E lo certifican. El contador de intentos vuelve a 0 (salvo E2E, que no cuenta intentos). Si ya la
  habías mergeado y el coder cambia algo, después mergea la rama de nuevo.

  **Opcional — `AUTO_MERGE=true`:** si no querés mergear a mano, activá `AUTO_MERGE=true` en
  `autopilot.env`: en cuanto el QA (y el E2E, si lo usás) aprueban, **el kit mergea la rama a la base
  por vos** (solo local: nunca hace push ni borra ramas) y deja la tarea en `reviewed` sola. Si el
  merge no entra limpio (conflicto, o cambios sin commitear en tu copia), la base queda intacta, la
  tarea pasa a `stopped` con el motivo y te avisa por Telegram.
- **Tareas en `stopped`:** el motivo está al final del `.md` (*Motivo de stopped*), con lo que
  recomienda hacer. Cuando lo resuelvas, devuélvela a la cola:
  ```sh
  ~/.local/share/autopilot-kit/wi.sh autopilot.env reqa bug-140123
  ```
- **Crear una tarea a mano:** desde la app web (*Nueva tarea*), o pon un `.md` en `.workitems/new/` llamado
  `bug-<id>-<título>.md` o `task-<id>-<título>.md`. El `<id>` lo eliges tú: un número (`140123`) o un
  texto (`login_social`: minúsculas, dígitos y `_`, sin `-`). Es también el nombre de la rama.

> Si cierras Claude Code / OpenCode, el autopilot se detiene. Al volver, escribe `/autopilot` otra vez.

> Las tareas se guardan en una base (`.workitems/autopilot.db`); los `.md` se generan solos a partir
> de ella para que puedas leerlas. Mover un `.md` de carpeta o crear uno nuevo sigue funcionando; para
> editar una tarea usa la app web. La primera vez que actualizas el kit, el tablero se pasa solo a la
> base y los `.md` originales quedan de respaldo en `.workitems/.respaldo-md-<fecha>/`.

### App web

```sh
~/.local/share/autopilot-kit/autopilot-web          # solo en esta PC: http://localhost:8765
~/.local/share/autopilot-kit/autopilot-web --lan    # también desde el celular u otra PC de tu red
```

Desde el cliente puedes usar la skill **`/autopilot-web`**: arranca la web por ti (desacoplada
del cliente), y si ya está corriendo te dice en qué URL y PID, y pregunta si quieres detenerla
o rearrancarla en otro modo (`/autopilot-web lan`, `/autopilot-web puerto 9000`,
`/autopilot-web detener`).

Muestra todos tus proyectos del autopilot:

- **Tablero** por estado, con búsqueda y filtros; **detalle** de cada tarea con descripción,
  criterio, el historial de cada intento (notas del coder, reportes de QA y E2E) y los **adjuntos
  agrupados por paso**: tarea original, subidos por ti, y coder / QA / E2E de cada intento, con
  botones para ver solo los de un agente.
- **Gestionar:** panel Git (diff, mergear a la base, push, crear PR en GitHub o Azure DevOps), dar feedback y devolver una tarea revisada al coder, a QA o a E2E, devolver a QA o a E2E, detener, marcar revisada, cambiar prioridad, pausar el autopilot.
- **Crear y editar** tareas y subirles capturas.
- **Correr** el health check y las pruebas guardadas, viendo la salida.
- El **log** de actividad y los reportes de `run-tests`.

Con `--lan` pide una clave, que está en `~/.config/autopilot-kit/web.env` (se crea sola). Va sin
HTTPS: úsalo solo en una red de confianza. Nunca muestra valores de los `.env`.

---

## Qué hace cada agente

**Coder** — Lee la tarea completa (con sus capturas y videos), la programa en su rama y commitea.
Si hace falta tocar otro repo del proyecto (p. ej. el backend), abre la misma rama ahí. Al terminar
deja sus notas: qué hizo, por qué y cómo probarlo.

**QA** — Certifica **solo lo que prueba**: compila, corre los tests y prueba cada criterio de
aceptación (con tests temporales y capturas de pantalla si hace falta). Tres resultados:

- **Aprobado** → `done` (o a E2E, si está activo).
- **Rechazado** → vuelve al coder con lo que falló. Máximo 3 intentos.
- **No certificable** → `stopped`: le falta algo (una herramienta, un ambiente) y te dice qué.

**E2E** *(opcional)* — Usa la app como una persona, de punta a punta, en **web y en un emulador
Android**, contra tu backend local y una base de datos de pruebas. Saca **una captura en cada
paso** y las pone en la tarea. Ver [Pruebas E2E](#pruebas-e2e-opcional).

Los agentes **no pueden** hacer push, merge, borrar ramas ni tocar tus archivos `.env`. Está
bloqueado de verdad, no es solo una instrucción.

---

## Seguridad: nunca producción

- Los agentes solo se conectan a bases de datos o APIs usando **`.env.autopilot`**, que **creas tú**.
- Antes de cada uso se revisa: todo debe ser **local o QA** (la base de datos debe decir "qa" en
  su nombre y `NODE_ENV` no puede ser `production`).
- Si algo parece producción, **no se ejecuta**: la tarea va a `stopped` diciendo qué vio y qué
  recomienda.
- Ningún agente crea, edita ni muestra tus `.env`.

Revisar si un repo está bien configurado (no muestra valores):

```sh
~/.local/share/autopilot-kit/wi.sh autopilot.env entorno Konectame_BackOffice_BE
```

¿Un servicio externo que no tiene versión de QA (p. ej. una pasarela de pagos de pruebas)?
Permítelo a propósito en tu `.env.autopilot`: `AUTOPILOT_PERMITIR=AZUL_PAYMENT_URL`.

---

## Ajustes

Todo está en **`autopilot.env`**, en la carpeta de tu proyecto. Lo más común:

| Quiero… | Cambia |
|---|---|
| Cambiar la rama de la que salen las tareas | `REPO.<repo>=<rama>` (o `BASE_BRANCH=` si es un solo repo) |
| Más de un coder y un QA a la vez | `PARALLEL=true`, y `MAX_CODERS` / `MAX_QA` |
| Activar las pruebas E2E | `E2E=true` (ver abajo) |
| Que un comando pueda tardar más | `COMMAND_TIMEOUT=900` (segundos) |
| Recibir avisos y responder por Telegram | `TELEGRAM=true` (ver *Avisos por Telegram*) |

Con 8 GB de RAM y Flutter, lo razonable es **1 coder + 1 QA** (`PARALLEL=false`, el valor por
defecto). Todas las variables: [docs/REFERENCIA.md](docs/REFERENCIA.md#autopilotenv).

---

## Pruebas E2E (opcional)

Un agente más que, después del QA, **usa la app de verdad** (web y Android) y deja capturas de cada
paso. Actívalo cuando quieras más confianza antes de mergear.

**1. Instalar las herramientas** (una vez, ~6 GB, sin sudo; no toca tu Flutter ni tu Java):

```sh
~/.local/share/autopilot-kit/e2e-setup.sh
```

**2. Poner las cuentas de prueba** en **`cuentas-e2e.env`**, en la carpeta del proyecto (junto a
`autopilot.env`). Una por rol, que existan en la base de QA. El nombre es libre si empieza con `E2E_`:

```
E2E_BO_ADMIN_USER=admin@prueba.com
E2E_BO_ADMIN_PASSWORD=...
E2E_CLIENTE_USER=cliente@prueba.com
E2E_CLIENTE_PASSWORD=...
```

No las pongas en `autopilot.env`: ese archivo lo leen los agentes y no debe tener contraseñas.
Ejemplo: [`examples/proyecto/cuentas-e2e.env.example`](examples/proyecto/cuentas-e2e.env.example).

**3. Base de datos.** Por defecto el E2E usa **la misma base de QA** del `.env.autopilot` de cada
backend: no tienes que crear nada. Solo asegúrate de que ese `.env.autopilot` tenga `PORT` (el
puerto del backend; si no, se toma el del `.env`).

¿Prefieres otra base u otro puerto solo para E2E? *(opcional)* Crea un `.env.autopilot.e2e` en ese
backend (igual que `.env.autopilot`, con los cambios). Si existe, el E2E usa ese. Ejemplo:
[`examples/proyecto/env.autopilot.e2e.example`](examples/proyecto/env.autopilot.e2e.example).

**4. Activarlo.** En `autopilot.env`, `/autopilot-init` ya dejó un bloque E2E sugerido. Revísalo
(sobre todo `E2E_CLIENTS`: qué app usa cada backend) y cambia `E2E=false` por `E2E=true`.
No tienes que cambiar las URLs de las apps ni del BackOffice: en E2E el kit las apunta solo al
backend local.

**5. Comprobar y arrancar.** Desde la carpeta del proyecto:

```sh
~/.local/share/autopilot-kit/health-check
```

Revisa **todo lo que hace falta antes de correr una prueba** y dice qué hacer con cada problema:
herramientas, acceso al emulador (KVM), config E2E, `.env.autopilot` y puertos de cada backend,
cuentas de prueba, apps que no compilan en Linux (imports con mayúsculas), apps que no soportan web,
y qué servidores de producción se van a bloquear. ✅ ok · ⚠️ aviso · ❌ bloquea. Cada ❌ dice **quién**
lo resuelve: `[coder]` (se arregla con un commit, p. ej. un import roto) o `[humano]` (herramienta,
ambiente, cuenta, configuración). Lo del coder **vuelve solo al coder**, sin contar como intento
fallido y sin molestarte; solo lo `[humano]` detiene la tarea y te avisa.

```
❌ compila   Konectame_App_Clientes (dev): imports que no existen en Linux: …/AddPhoneNumber.dart [coder]
             → corregir las mayusculas del import en el repo
⚠️  kvm       estas en el grupo kvm pero esta sesion aun no lo ve; el kit usa `sg kvm` solo
✅ produccion internet abierto; se bloquean: konectame-be-main.azurewebsites.net, …
```

Variantes: `health-check bug-37269` (solo lo que usan los casos de esa tarea), `--android` / `--web`,
`--deep` (además arranca el emulador y Chromium). `run-tests` y el agente E2E lo corren solos antes
de empezar: si hay algo ❌, no ejecutan nada.

Luego `/autopilot`. Las tareas aprobadas por el QA pasan por E2E antes de llegar a `done`.

**Resumen de archivos** (todos los creas tú; ningún agente los crea ni los edita):

| Archivo | Dónde | Qué tiene |
|---|---|---|
| `autopilot.env` | carpeta del proyecto | Configuración del kit. **Sin contraseñas.** |
| `cuentas-e2e.env` | carpeta del proyecto | Cuentas de prueba del E2E |
| `.env.autopilot` | cada repo con BD o API | Ambiente de QA (coder, QA y E2E) |
| `.env.autopilot.e2e` | un repo, opcional | Otra base u otro puerto solo para E2E |

Los `.env`, `.env.local`, `.env.qa`… de tu equipo el autopilot no los usa para correr nada.

**Cómo protege producción:** los backends corren en tu máquina contra la base de QA (o la que
pongas en `.env.autopilot.e2e`) y el kit apunta las apps y el BackOffice a ese backend local. El
navegador y el emulador **tienen internet** (íconos, imágenes, Google…), pero **los servidores de
producción del proyecto están bloqueados**. El kit los detecta solo, en cualquier proyecto: los
destinos de los `.env` reales que no son locales ni de QA, y las URLs del config de la app (p. ej.
`baseUrlMain`). Para agregar otros: `E2E_BLOCK_HOSTS=host1,host2` en `autopilot.env`. Si la app intenta
llegar a uno, se rechaza y queda anotado en el reporte. Las pruebas crean datos en la base de QA.

---

## Volver a correr las pruebas

Cuando el QA o el E2E **aprueban** una tarea, las pruebas que demuestran cada criterio quedan
guardadas **en la rama de la tarea**, como tests normales del proyecto, y viajan en el PR:

```
tests/
├── bug-37269/
│   ├── cases.json               qué casos hay y cómo se corre cada uno
│   ├── popular.check.ts         caso del QA
│   └── detalle-popular.flow.cjs caso E2E (navegador)
└── services.json                cómo levantar este repo para los casos E2E
```

Casos E2E de apps Flutter en Android: `tests/<tarea>/<nombre>_flow.dart` (un `integration_test`).
En el repo **solo** queda ese archivo: lo que Flutter necesita para correrlo (`integration_test` en
`pubspec.yaml`, el driver) lo agrega `run-tests` en su copia temporal.

Si el QA o el E2E **no aprueban**, sus pruebas no se pierden: se guardan como **borrador** en
`.workitems/adjuntos/<tarea>/borradores/` (fuera del repo) y en la siguiente corrida el agente parte de
ellas en vez de escribirlas desde cero (ahorra tokens). Ver qué hay: `wi.sh autopilot.env borrador <tarea>`.

**Pruebas de humo** (no son de una tarea, p. ej. "el cliente puede iniciar sesión"): en
`tests/smoke/`, guardadas en una rama **`smoke-tests`** de cada repo que tú mergeas. Se guardan con
`wi.sh autopilot.env smoke-save <copia>` y se corren con `run-tests smoke`.

- **No dejan rastro del sistema** (nada dice "autopilot" ni usa el kit) y **no cambian nada del
  proyecto**: tienen nombres que `npm test` / `flutter test` no toman solos. Si un caso no cumple
  eso, no se guarda y queda el aviso en la tarea.
- Se guardan con un commit aparte: `test: casos de prueba de bug-37269`.

Para correrlos otra vez, desde la carpeta del proyecto:

```sh
K=~/.local/share/autopilot-kit
$K/run-tests bug-37269          # los de una tarea (QA + E2E), en su rama
$K/run-tests bug-37269 --e2e    # solo E2E (o --qa); --android / --web: solo esa plataforma
$K/run-tests smoke              # pruebas de humo
$K/run-tests --all              # regresión: todos los guardados, en la rama base de cada repo
```

Levanta lo que haga falta (backend y BackOffice en local, contra la base de QA), corre los casos,
apaga todo y deja un **reporte con capturas** en `test-results/`. Si algo falla, termina con error.

---

## Avisos por Telegram

El autopilot te va contando por Telegram qué hace, te avisa con 🚨 cuando **necesita tu intervención**
(tarea detenida, tarea lista para revisar y mergear, tarea atascada, pruebas que fallan) y **le puedes
responder desde el chat**.

**Configurarlo (una vez, en tu terminal):**

1. En Telegram, habla con **@BotFather** → `/newbot` y crea un bot **solo para el autopilot**. No uses
   el del plugin de Claude Code: Telegram deja que un solo programa lea los mensajes de cada bot.
2. Conecta ese bot con tu chat:
   ```sh
   ~/.local/share/autopilot-kit/wi.sh autopilot.env telegram-setup
   ```
   Te pide el token (no se muestra), te pide mandarle `/start` al bot, y guarda todo en
   `~/.config/autopilot-kit/telegram.env` (solo tú puedes leerlo).
3. En `autopilot.env`: `TELEGRAM=true`. Si solo quieres lo urgente: `TELEGRAM_ALERTS_ONLY=true`.
4. `health-check` debe mostrar `✅ telegram`.

**Qué te llega:** coder empezó / terminó, QA y E2E certificando, rechazos con el motivo, ✅ lista para
mergear, 🚨 detenida (con el motivo y cómo resolverla), 🚨 atascada, resultado
de `run-tests`, y cuando el autopilot arranca o se detiene. Nunca contraseñas ni valores de los `.env`.

**Qué le puedes escribir:**

| Mensaje | Qué hace |
|---|---|
| `/estado` · `/cola` | Qué hace cada agente y qué hay en cola |
| `/tarea bug-37269` | Estado, motivo y última nota de una tarea |
| `/reqa bug-37269` · `/re-e2e bug-37269` | Devolverla a QA o a E2E (p. ej. después de resolver un `stopped`) |
| `/stop bug-37269 <motivo>` · `/reviewed bug-37269` | Detenerla · marcarla como revisada |
| `/pausa` · `/seguir` | Dejar de tomar tareas nuevas (lo que está en curso termina) · volver |
| `/health` | Health check resumido |
| Cualquier otro texto | Se lo pasa al orquestador, que te responde por el chat (solo con `/autopilot` corriendo) |

Solo responde a **tu** chat; los mensajes de cualquier otro se ignoran.

Los comandos sin argumento (`/estado`, `/cola`, `/health`, `/pausa`, `/seguir`) también se muestran
como un **menú de botones** fijo sobre el campo de texto (junto a `/ayuda`, que vuelve a mandar esta
tabla); los que llevan clave o motivo se siguen escribiendo a mano.

**Si el autopilot se queda parado esperándote** (todo en `done` sin revisar, en `stopped` o bloqueado
por dependencias, sin ningún puesto ocupado), te avisa por Telegram una vez tras `CADENA_MIN`
minutos (default 20) y de nuevo cada `CADENA_REAVISO_MIN` (default 240) hasta que lo destrabes. En
pausa explícita no avisa. El mismo estado se ve en la app web como un banner "🧊 Cadena detenida".

---

## Problemas comunes

| Veo… | Qué hago |
|---|---|
| `stopped` con *NO CERTIFICABLE: falta …* | Instala o crea lo que dice, y `wi.sh autopilot.env reqa <clave>` |
| `stopped` con *POSIBLE PRODUCCIÓN* | Revisa el `.env.autopilot` de ese repo (la base debe decir "qa") y `reqa` |
| `stopped` con *no existe la rama base* | Corrige `REPO.<repo>=` en `autopilot.env` |
| Nada avanza | ¿Está corriendo `/autopilot`? Si cerraste el cliente, lánzalo otra vez |
| Algo se colgó | El vigilante mata lo que lleva 10 min sin hacer nada y avisa de tareas atascadas |
| ¿Qué le falta a mi proyecto? | `wi.sh autopilot.env check` |
| ¿Qué le falta al E2E? | `~/.local/share/autopilot-kit/health-check` |

---

## Más información

- **[docs/REFERENCIA.md](docs/REFERENCIA.md)** — todo el detalle: estados, variables, comandos de
  `wi.sh`, cómo cargar tareas desde afuera, trabajo en paralelo, vigilante, E2E por dentro y estructura del kit.
- Actualizar el kit: `cd ~/code/dotenvs && git pull && ./install.sh`.
- Desinstalar: `./install.sh --uninstall` (no toca tus proyectos).
