---
name: autopilot-plan
description: Convierte una idea o un documento (PRD, spec, notas, acta, correo, imagenes) en tareas listas para el autopilot. Primero hace un brainstorming con el usuario, pregunta todo lo que haga falta hasta que no quede nada ambiguo, y recien entonces propone el desglose en tareas (con criterios de aceptacion verificables y dependencias) y, con su aprobacion, las crea en el board como new. Usar cuando el usuario diga /autopilot-plan, "convierte esto en tareas", "arma las tareas de esta idea", "planifica esto para el autopilot", "desglosa este documento" o similar. NO usar en proyectos sin autopilot.env.
---

# Autopilot Plan — de una idea o documento a tareas del board

Convierte una idea o un documento en tareas que el autopilot puede ejecutar solo: un coder las programa en
su rama y un QA (y, con `E2E=true`, un agente E2E) las certifica **criterio por criterio**, sin poder
preguntarle nada a nadie. Por eso el trabajo de esta skill es **sacar toda la ambigüedad antes** de crear
una sola tarea.

Tres fases, en orden:

1. **Entender:** leer la idea o el documento y el código.
2. **Brainstorming:** preguntar hasta que todo esté 100 % claro, y que el usuario lo confirme.
3. **Tareas:** proponer el desglose, iterarlo con el usuario y crearlo en el board solo cuando lo apruebe.

Tú **no programas**. No creas ramas, no tocas los repos y no arrancas el autopilot.

```sh
K=~/.local/share/autopilot-kit
W=$K/wi.sh
E=<carpeta abierta>/autopilot.env
```

## Cuándo usar

Solo si la carpeta abierta tiene `autopilot.env`. Si no lo tiene, para y dile al usuario que primero prepare
el proyecto con `/autopilot-init`.

## Arranque

Verifica `autopilot.env` (ver *Cuándo usar*) y sigue las tres fases en orden, desde la Fase 1. Si ya
existe un plan en `<board>/planes/` para esta idea, léelo y retoma donde quedó.

## Fase 1 — Entender

1. **La entrada.** Puede llegar de varias formas:
   - una idea escrita en el mensaje o en los argumentos del comando;
   - una o varias rutas a documentos (`.md`, `.txt`, `.pdf`, `.docx`, imágenes, mockups);
   - un enlace;
   - una mezcla de todo eso.

   Léelo **completo**. Si algo no se puede leer, dilo y pide otra forma de pasarlo. Si no hay entrada, pregunta
   cuál es la idea.
2. **El proyecto.** Lee `autopilot.env` (no tiene secretos):
   - si es un repo o un workspace (`REPO.<carpeta>=<rama base>` por repo);
   - la rama base de cada repo;
   - si `E2E=true` y qué frontends consume cada backend (`E2E_CLIENTS`).

   El board está en `WORKITEMS_DIR`, o en `.workitems/` si no está definido.
3. **El código.** Explora los repos, solo en modo lectura, en su rama base:
   - stack y estructura, módulos relacionados, qué ya existe y qué falta;
   - convenciones, cómo son los tests y cómo se configuran los ambientes.

   En Claude Code puedes delegar la búsqueda en subagentes `Explore`, en paralelo.
   **No preguntes lo que el código ya responde.** Pregunta lo que el código no puede decidir.
4. **El board.** Corre `$W "$E" query`: tareas que ya existen, para no duplicarlas y para saber qué ids están usados.
5. **Devuelve lo que entendiste** en 5 a 10 líneas:
   - qué se quiere lograr y para quién;
   - qué hay hoy en el código;
   - qué repos parecen afectados.

   Pide que te corrijan antes de seguir.

## Fase 2 — Brainstorming hasta tenerlo 100 % claro

Crea el **documento del plan** en `<board>/planes/<slug>.md` y mantenlo al día después de cada respuesta.
Es la memoria del brainstorming y la fuente de las tareas. Si la conversación se corta, se retoma desde ahí.
Tiene estas secciones:

```markdown
# Plan: <nombre>
Origen: <idea / ruta del documento>   ·   Estado: brainstorming | definido | tareas creadas

## Objetivo            por qué se hace y cómo se sabe que salió bien
## Alcance             lo que entra, en viñetas concretas
## Fuera de alcance    lo que explícitamente NO entra (tan importante como el alcance)
## Usuarios y roles    quién lo usa y con qué permisos
## Flujos              paso a paso de cada flujo, incluidos los alternativos
## Reglas de negocio   validaciones, límites, cálculos, estados
## Datos               entidades, campos, migraciones, datos existentes que se tocan
## Interfaz            pantallas, textos, estados vacíos, carga y error (mockups si hay)
## API e integraciones endpoints, contratos, servicios externos
## Errores y casos borde
## Seguridad y permisos
## Repos afectados     y qué cambia en cada uno
## Cómo se prueba      datos y cuentas de QA necesarios, qué se verifica en web y en Android
## Decisiones          P: pregunta → R: respuesta del usuario (con fecha)
## Pendientes          lo que todavía no está claro. La fase termina cuando esto queda vacío.
```

**Cómo preguntar:**

- **En rondas cortas, de 1 a 4 preguntas**, empezando por lo que más cambia el diseño (alcance, flujos,
  datos) y dejando para después los detalles.
- **Cada pregunta con opciones concretas y tu recomendación** (y por qué), basadas en el código y en lo que ya
  se decidió. En Claude Code usa la herramienta `AskUserQuestion`; en OpenCode, la herramienta `question`.
  Si no hay herramienta de preguntas, numéralas en el mensaje.
- **Nunca inventes un requisito.** Todo supuesto se pregunta o se anota como supuesto confirmado por el usuario.
- **Haz de sparring, no de secretario:**
  - señala contradicciones y huecos (qué pasa si..., quién puede..., qué se muestra cuando no hay datos...);
  - propone simplificaciones y recortes (un MVP primero);
  - avisa de riesgos: migraciones de datos, compatibilidad y rendimiento.
- **Piensa en la verificación desde ya.** Si algo no se va a poder probar en QA (falta un dato, una cuenta, un
  servicio externo), pregúntalo ahora: el QA dejaría la tarea en `stopped`.
- Mueve cada respuesta a su sección y a *Decisiones*, y actualiza *Pendientes*.

**La fase termina solo cuando:**

1. *Pendientes* está vacío.
2. Le muestras al usuario un **resumen de la definición**: objetivo, alcance, fuera de alcance, flujos
   principales y decisiones clave.
3. El usuario confirma **explícitamente** que es eso.

Entonces cambia el estado del plan a `definido`. Si el usuario quiere cortar antes, avísale qué quedó sin
definir y anótalo en el plan. No crees tareas con puntos abiertos que afecten a lo que el coder tiene que hacer.

## Fase 3 — Desglose en tareas

### Qué es una buena tarea para el autopilot

- **Una tarea = una rama = un coder, en una sesión.** Que se pueda programar, probar y certificar sola.
  - Pequeña: pocos archivos por repo.
  - Si el criterio pasa de unos 6 a 8 puntos o mezcla cosas distintas, divídela.
  - Si es trivial, júntala con otra.
- **Cortes verticales**, no por capas. Mejor "el usuario puede X" de punta a punta que "hacer el modelo",
  "hacer el endpoint", "hacer la pantalla".
  - En un **workspace**, una tarea puede tocar varios repos: el coder abre la misma rama en cada uno, y
    backend + front de una misma función pueden ir juntos si son pequeños.
  - El repo principal va en `repo`; los otros se mencionan en la descripción.
- **Pocas dependencias.** Una rama nace de la rama base, que solo tiene lo que el humano ya mergeó. Por eso
  una tarea con `--depende` **no se empieza hasta que sus dependencias estén en `reviewed`**, es decir,
  revisadas y mergeadas.
  - Cada dependencia pone un paso humano en medio: úsalas solo cuando de verdad hacen falta (por ejemplo, una
    migración o un contrato que otras usan).
  - Prefiere tareas independientes, que corren en paralelo.
- **Tareas paralelas que no pisen los mismos archivos.** Si dos tareas tienen que tocar lo mismo, es mejor que
  una dependa de la otra o que sean una sola.
- **Autocontenida.** El coder y el QA **no ven esta conversación**: todo lo decidido que afecta a la tarea
  tiene que estar escrito en ella.

### Campos de cada tarea

| Campo | Cómo |
|---|---|
| `tipo` | `task`. Solo `bug` si corrige algo que hoy funciona mal. |
| `id` | Texto corto y con sentido, `[a-z0-9_]`, sin `-`, que no exista en el board. Usa un prefijo común del plan: `pagos_modelo`, `pagos_checkout_web`. La clave queda `task-<id>` y es también el nombre de la rama. |
| `prioridad` | `Critical`, `High`, `Medium` o `Low`. Lo que desbloquea a otras va más alto. |
| `repo` | Obligatorio en un workspace: la carpeta del repo principal. |
| título | Qué se consigue, en una línea: "Checkout con tarjeta guardada". |
| `--depende` | Claves de las que depende, separadas por comas (solo si hace falta). |
| `--origen` | `plan:<slug>`, para rastrear de qué plan salió. |

**Descripción** (Markdown), con este esquema:

```markdown
**Contexto:** por qué existe la tarea y qué parte del plan cubre (planes/<slug>.md).

**Qué hay que hacer:**
- ... (comportamiento esperado, no la implementación línea a línea)

**Decisiones ya tomadas:** reglas, textos, validaciones, formatos que el usuario definió.

**Dónde (orientativo):** módulos o archivos que encontraste al explorar; otros repos que toca.

**Fuera de alcance:** lo que NO debe hacer esta tarea (y qué tarea lo hace, si otra lo hace).

**Depende de:** <clave> — qué necesita de ella. (Si no aplica, omitir.)

**Para probar:** datos o cuentas de QA necesarios, cómo llegar a la pantalla o el endpoint.
```

**Criterio de aceptación**: una lista numerada. Cada punto tiene que ser **observable y verificable por sí
solo**, porque el QA lo prueba y lo certifica uno por uno:

- Formato *dado / cuando / entonces*, o una afirmación concreta: "Con el carrito vacío, el botón Pagar está
  deshabilitado y se muestra *Tu carrito está vacío*".
- Incluye los casos de error y borde decididos, no solo el camino feliz.
- Nada vago: no "funciona bien", no "es rápido", no "buena UX". Si importa, cuantifícalo.
- Si el repo tiene tests, añade un punto: "tests automatizados que cubran X".
- Con `E2E=true`, redacta los puntos de interfaz como el flujo que ve el usuario (el agente E2E los recorre
  con capturas en web y Android).

### Revisión con el usuario

1. Muestra una **tabla** con clave, título, repo, prioridad, dependencias y cantidad de criterios. Debajo,
   dibuja el **orden de ejecución** (qué corre en paralelo y qué espera a qué).
2. Añade una **matriz de cobertura**: cada punto del *Alcance* del plan tiene que quedar cubierto por al menos
   una tarea. Si algo no está cubierto, dilo.
3. Muestra el texto completo de las tareas: todas, si son pocas, o las que el usuario pida.
4. Itera: dividir, juntar, reordenar, cambiar prioridades o criterios. Guarda el desglose en el plan
   (sección `## Tareas`).
5. **No crees nada sin un "sí" explícito** al desglose final.

### Crear las tareas

1. Escribe la descripción y el criterio de cada tarea en archivos:
   - `<board>/planes/<slug>/<id>.descripcion.md`
   - `<board>/planes/<slug>/<id>.criterio.md`

   Así el Markdown largo no pelea con las comillas del shell.
2. Créalas **en orden de dependencias**: primero las que no dependen de nada, porque `--depende` exige que la
   otra ya exista.

   ```sh
   $W "$E" add-task task pagos_modelo High "Modelo de pagos y migración" \
     @<board>/planes/pagos/pagos_modelo.descripcion.md @<board>/planes/pagos/pagos_modelo.criterio.md \
     [repo] --origen plan:pagos
   $W "$E" add-task task pagos_checkout_web Medium "Checkout con tarjeta guardada" \
     @.../pagos_checkout_web.descripcion.md @.../pagos_checkout_web.criterio.md \
     [repo] --depende task-pagos_modelo --origen plan:pagos
   ```

3. Si el documento traía imágenes o mockups que ayudan a una tarea, adjúntalos:
   `$W "$E" adjuntar <clave> <archivo>...`.
4. Si una creación falla (id repetido, repo inválido, dependencia inexistente), corrige **esa** tarea y
   reintenta. No borres ni recrees las que ya salieron bien.
5. Cambia el estado del plan a `tareas creadas` y anota las claves.
6. **Reporta:**
   - las claves creadas y el orden en que el autopilot las va a tomar;
   - qué tareas esperan a que mergees otras (quedan en `new` con "depende de", y el coder no las toma hasta
     que sus dependencias estén en `reviewed`);
   - la ruta del plan.

   Ofrece `/autopilot` para empezar. No lo arranques si el usuario no lo pide.

Para cambiar dependencias después: `$W "$E" depende <clave> <clave>[,<clave>...]` (con `-` se quitan).

## Lo que NUNCA debes hacer

- Crear tareas antes de que el usuario confirme la definición **y** el desglose.
- Inventar requisitos, textos, reglas o datos que el usuario no decidió.
- Programar, crear ramas, hacer commits o modificar los repos.
- Poner secretos (contraseñas, tokens, valores de `.env`) en las tareas o en el plan. Las cuentas de QA se
  nombran por rol; el humano las define en `cuentas-e2e.env`.
- Crear tareas con puntos del criterio que el QA no pueda verificar.
