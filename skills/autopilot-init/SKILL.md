---
name: autopilot-init
description: 'Prepara la carpeta actual para el autopilot.'
---

# Autopilot Init

Prepara **la carpeta en la que está abierto el cliente** (OpenCode, Claude Code o pi)
para usar `/autopilot`. No hay script: lo haces tú — detectar, preguntar y crear dos
cosas: `autopilot.env` y el board `.workitems/`.

## Arranque

1. **¿Está el kit LOCAL en esta carpeta?** Mira si existe `.autopilot/` (con
 `aenv.sh`). Si no, **no participa**: pídele al usuario correr el instalador
 local antes — `bash <ruta-al-repo-del-kit>/install.sh --local .` (o lo que él
 tenga a mano). El kit es local al proyecto: no hay instalación global. Si el
 usuario solo quiere ver el board, avísale igual que falta el kit.
2. **Detectar.** Mira la carpeta abierta:
   - Si tiene `.git/`, es un **repo** (`modo: repo`).
   - Si es una carpeta en la que hay **varias carpetas con `.git/`**, es un
   **workspace** (cada una es un repo del proyecto).
   - Si no es ninguna, díselo al usuario y para.

    Para cada repo, mira su rama actual (`git -C <repo> branch --show-current`) y
    sus ramas remotas (`git ls-remote --symref <repo> HEAD` o `git -C <repo> branch -r`).
    Si un repo tiene cambios sin commitear, anótalo (no lo toques).
3. **No tocar la rama base.** Cada worktree nace de la rama base que **Orca ya tiene
 definida** para su repo (la base por defecto). Este kit NO la pide ni la
 configura: `orca worktree create` sin `--base-branch` usa esa base. Si algo hay
 que ajustar, se ajusta en Orca (registro del repo), no acá.
4. **Crear `autopilot.env`** en la carpeta abierta (o en su padre, si es un workspace
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
5. **Crear el board.** El board es `$BOARD` = `$WORKITEMS_DIR` (por defecto `.workitems/`).
Crea `$BOARD/` con las 4 carpetas de estado y las de apoyo, si no existen:
   ```
    $BOARD/new/  $BOARD/working/  $BOARD/done/  $BOARD/stopped/
    $BOARD/adjuntos/  $BOARD/planes/  $BOARD/.autopilot/resultados/
   ```
6. **Ignorarlo de git.** Asegúrate de que `$BOARD/` (la ruta real, p. ej. `.workitems/`
o `.board/`) esté en el `.gitignore` del repo (o, en un workspace, en el de cada repo).
Si no está, agrégalo (solo eso).
7. **Reportar** en pocas líneas: qué se creó y los avisos. Avisa si un repo que hiere:  no tiene `.env.autopilot` (lo crea el humano  
 copiando `.env` y apuntando BD/URLs a QA/local) 