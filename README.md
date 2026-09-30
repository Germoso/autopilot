# Autopilot

Agentes de IA que **trabajan tus tareas solos** mientras tú revisas y mergeas.

Tú pones tareas en una carpeta (o las trae Azure DevOps). El autopilot las toma una por una:

```
 tarea nueva ──> CODER ────────> QA ─────────────> E2E (opcional) ─────> LISTA
                 la programa     la prueba y       la usa como una        tú la revisas
                 en su rama      la certifica      persona (web/Android)  y mergeas
```

- Funciona con **Claude Code** y **OpenCode**.
- Cada tarea tiene **su propia rama** (`bug-140123`, `task-2051`). **Nunca hace push ni merge**: eso lo haces tú.
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
/azure-sync     trae las tareas nuevas del sprint de Azure DevOps
/autopilot      arranca: toma las tareas y las trabaja
```

Mientras `/autopilot` corre, mira la carpeta **`.workitems/`** de tu proyecto. Cada tarea es un
archivo `.md` y **la carpeta donde está te dice cómo va**:

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

- **Tareas en `done`:** abre su `.md` y mira:
  - *Repos modificados*: qué ramas mergear y en qué repos;
  - *Notas del desarrollador*: qué hizo y por qué;
  - *Reporte de QA*: qué probó y **cómo probarlo tú a mano**.

  Si te convence, mergea la rama. Después mueve el archivo a `reviewed/`.
- **Tareas en `stopped`:** el motivo está al final del `.md` (*Motivo de stopped*), con lo que
  recomienda hacer. Cuando lo resuelvas, devuélvela a la cola:
  ```sh
  ~/.local/share/autopilot-kit/wi.sh autopilot.env reqa bug-140123
  ```
- **Crear una tarea a mano:** pon un `.md` en `.workitems/new/` llamado
  `bug-<número>-<título>.md` o `task-<número>-<título>.md`.

> Si cierras Claude Code / OpenCode, el autopilot se detiene. Al volver, escribe `/autopilot` otra vez.

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
y qué servidores de producción se van a bloquear. ✅ ok · ⚠️ aviso · ❌ bloquea.

```
❌ compila   Konectame_App_Clientes (dev): imports que no existen en Linux: …/AddPhoneNumber.dart
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
  `wi.sh`, Azure DevOps y su MCP, trabajo en paralelo, vigilante, E2E por dentro y estructura del kit.
- Actualizar el kit: `cd ~/code/dotenvs && git pull && ./install.sh`.
- Desinstalar: `./install.sh --uninstall` (no toca tus proyectos).
