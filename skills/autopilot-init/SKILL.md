---
name: autopilot-init
description: 'Prepara la carpeta actual para el autopilot. Detecta si es un repo o un workspace con varios repos, y crea autopilot.env y el board (.workitems/ con carpetas). La rama base NO se pide ni se configura: la define Orca (cada worktree nace de la base por defecto del repo). Usar cuando el usuario diga /autopilot-init, "inicializa el autopilot", "prepara este proyecto" o similar, o cuando /autopilot diga que el proyecto no participa y el usuario quiera sumarlo.'
---

# Autopilot Init

Prepara **la carpeta en la que está abierto el cliente** (OpenCode, Claude Code o pi)
para usar `/autopilot`. No hay script: lo haces tú — detectar, preguntar y crear dos
cosas: `autopilot.env` y el board `.workitems/`.

## Arranque

0. **¿Está el kit LOCAL en esta carpeta?** Mira si existe `.autopilot/` (con
   `aenv.sh`). Si no, **no participa**: pídele al usuario correr el instalador
   local antes — `bash <ruta-al-repo-del-kit>/install.sh --local .` (o lo que él
   tenga a mano). El kit es local al proyecto: no hay instalación global. Si el
   usuario solo quiere ver el board, avísale igual que falta el kit.

1. **Detectar.** Mira la carpeta abierta:
   - Si tiene `.git/`, es un **repo** (`modo: repo`).
   - Si es una carpeta en la que hay **varias carpetas con `.git/`**, es un
     **workspace** (cada una es un repo del proyecto, p. ej. `konectame/` con apps,
     backends y BackOffice).
   - Si no es ninguna, díselo al usuario y para.

   Para cada repo, mira su rama actual (`git -C <repo> branch --show-current`) y
   sus ramas remotas (`git ls-remote --symref <repo> HEAD` o `git -C <repo> branch -r`).
   Si un repo tiene cambios sin commitear, anótalo (no lo toques).

2. **No tocar la rama base.** Cada worktree nace de la rama base que **Orca ya tiene
   definida** para su repo (la base por defecto). Este kit NO la pide ni la
   configura: `orca worktree create` sin `--base-branch` usa esa base. Si algo hay
   que ajustar, se ajusta en Orca (registro del repo), no acá.

3. **Crear `autopilot.env`** en la carpeta abierta (o en su padre, si es un workspace
   y los repos están en subcarpetas). Te lo dicta el esquema:

   ```env
   # --- Ambos ---
   WORKITEMS_DIR=            # vacio = .workitems/ junto a este archivo
   PARALLEL=false            # true = hasta MAX_CODERS coders a la vez
   MAX_CODERS=2
   AUTO_MERGE=false          # true = el autopilot mergea la rama solo local al aprobar el humano
   COMMAND_TIMEOUT=900       # tiempo maximo (s) de lo que corre por aenv.sh
   AGENT=                    # agente del coder: pi, claude, opencode (o una cuenta de orca); vacio = decidir al orquestar
   ```

   Si ya existía, conserva el resto de variables que puso el usuario (no
   sobrescribas nada). La rama base no se escribe aquí: la usa Orca.

4. **Crear el board.** El board es `$BOARD` = `$WORKITEMS_DIR` (por defecto `.workitems/`).
Crea `$BOARD/` con las 4 carpetas de estado y las de apoyo, si no existen:

   ```
   $BOARD/new/  $BOARD/working/  $BOARD/done/  $BOARD/stopped/
   $BOARD/adjuntos/  $BOARD/planes/  $BOARD/.autopilot/resultados/
   ```

   (Solo estas: los estados son 4. Las devueltas por el humano vuelven a `new/` con
   `## Feedback del humano`; lo que no se pudo va a `stopped/` con `## Motivo de
   stopped`, requiriendo tu intervención.)

5. **Ignorarlo de git.** Asegúrate de que `$BOARD/` (la ruta real, p. ej. `.workitems/`
o `.board/`) esté en el `.gitignore` del repo (o, en un workspace, en el de cada repo).
Si no está, agrégalo (solo eso).

6. **Reportar** en pocas líneas: qué se creó y los avisos. Avisa si un repo que hiere:  no tiene `.env.autopilot` (lo crea el humano
   copiando `.env` y apuntando BD/URLs a QA/local) — sin él no se ejecuta nada contra
   BD/API en ese repo; o le faltan herramientas para compilar/probar (p. ej. `fvm`
   con la versión de `.fvmrc`, `flutter`, `node`) — el coder no podrá terminar y
   decíselo.

7. **Siguiente paso**, en una línea: cargar tareas (escribir `.md` en
   `$BOARD/new/` —`WORKITEMS_DIR`, por defecto `.workitems/`— a mano o con
   `/autopilot-plan`; también las puede traer una
   integración externa como Azure DevOps) y `/autopilot` para trabajar.

## Qué NO hace

- No toca archivos versionados de los repos ni su `.gitignore` salvo el agregado de
  `.workitems/`.
- No crea ramas, no hace commits, no hace push.
- No sobrescribe un `autopilot.env` existente.
