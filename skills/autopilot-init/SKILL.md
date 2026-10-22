---
name: autopilot-init
description: Prepara la carpeta actual para el autopilot. Detecta si es un repo o un workspace con varios repos, propone la rama base de cada uno, pregunta, y crea autopilot.env y el board (.workitems/ con carpetas). Usar cuando el usuario diga /autopilot-init, "inicializa el autopilot", "prepara este proyecto" o similar, o cuando /autopilot diga que el proyecto no participa y el usuario quiera sumarlo.
---

# Autopilot Init

Prepara **la carpeta en la que está abierto el cliente** (OpenCode, Claude Code o pi)
para usar `/autopilot`. No hay script: lo haces tú — detectar, preguntar y crear dos
cosas: `autopilot.env` y el board `.workitems/`.

## Arranque

1. **Detectar.** Mira la carpeta abierta:
   - Si tiene `.git/`, es un **repo** (`modo: repo`).
   - Si es una carpeta en la que hay **varias carpetas con `.git/`**, es un
     **workspace** (cada una es un repo del proyecto, p. ej. `konectame/` con apps,
     backends y BackOffice).
   - Si no es ninguna, díselo al usuario y para.

   Para cada repo, mira su rama actual (`git -C <repo> branch --show-current`) y
   sus ramas remotas (`git ls-remote --symref <repo> HEAD` o `git -C <repo> branch -r`).
   Si un repo tiene cambios sin commitear, anótalo (no lo toques).

2. **Mostrar y preguntar la rama base.** Presenta una tabla corta: repo y rama
   sugerida (primera de `develop`/`dev`/`main`/`master` que exista, o la rama por
   defecto del remoto). Pregunta al usuario si confirma las sugeridas o cuáles
   cambia. **No asumas**: la rama base define desde dónde nacen todas las ramas de
   los workitems. Si un repo no tiene sugerida, muéstrale sus ramas remotas y
   pregunta. Si el usuario no quiere un repo en el sistema, anótalo (no le crees
   línea `REPO.`).

   Si ya existe `autopilot.env`, dilo: solo se actualizan las ramas base que confirme.

3. **Crear `autopilot.env`** en la carpeta abierta (o en su padre, si es un workspace
   y los repos están en subcarpetas). Te lo dicta el esquema:

   ```env
   # --- Modo un repo ---
   BASE_BRANCH=<rama base>
   # --- Modo workspace (una linea por repo) ---
   # REPO.<carpeta>=<rama base>

   # --- Ambos ---
   WORKITEMS_DIR=            # vacio = .workitems/ junto a este archivo
   PARALLEL=false            # true = hasta MAX_CODERS coders a la vez
   MAX_CODERS=2
   AUTO_MERGE=false          # true = el kit mergea la rama solo local al aprobar el humano
   COMMAND_TIMEOUT=900       # tiempo maximo (s) de lo que corre por aenv.sh
   ```

   Si ya existía, conserva el resto de variables que puso el usuario y solo ajusta
   la rama base.

4. **Crear el board.** Crea `.workitems/` (o `$WORKITEMS_DIR`) con las carpetas de
   estados y las de apoyo, si no existen:

   ```
   .workitems/new/  .workitems/in-progress/  .workitems/bug-fix/
   .workitems/stopped/  .workitems/done/  .workitems/reviewed/
   .workitems/adjuntos/  .workitems/planes/  .workitems/.autopilot/resultados/
   ```

5. **Ignorarlo de git.** Asegúrate de que `.workitems/` esté en el `.gitignore` del
   repo (o, en un workspace, en el de cada repo). Si no está, agrégalo (solo eso).

6. **Reportar** en pocas líneas: qué se creó, las ramas base de cada repo y los
   avisos. Avisa si un repo que hiere:  no tiene `.env.autopilot` (lo crea el humano
   copiando `.env` y apuntando BD/URLs a QA/local) — sin él no se ejecuta nada contra
   BD/API en ese repo; o le faltan herramientas para compilar/probar (p. ej. `fvm`
   con la versión de `.fvmrc`, `flutter`, `node`) — el coder no podrá terminar y
   decíselo.

7. **Siguiente paso**, en una línea: cargar tareas (escribir `.md` en
   `.workitems/new/`, a mano o con `/autopilot-plan`; también las puede traer una
   integración externa como Azure DevOps) y `/autopilot` para trabajar.

## Qué NO hace

- No toca archivos versionados de los repos ni su `.gitignore` salvo el agregado de
  `.workitems/`.
- No crea ramas, no hace commits, no hace push.
- No sobrescribe un `autopilot.env` existente (salvo las ramas base que pases).