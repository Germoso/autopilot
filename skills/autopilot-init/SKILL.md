---
name: autopilot-init
description: Prepara la carpeta actual para el autopilot. Detecta si es un repo o un workspace con varios repos, propone la rama base de cada uno, pregunta, y crea autopilot.env (con la config E2E sugerida, apagada), azure-sync.env y el board. Usar cuando el usuario diga /autopilot-init, "inicializa el autopilot", "prepara este proyecto" o similar, o cuando /autopilot o /azure-sync digan que el proyecto no participa y el usuario quiera sumarlo.
---

# Autopilot Init

Prepara **la carpeta en la que está abierto el cliente** (OpenCode o Claude Code) para usar
`/autopilot` y `/azure-sync`. Todo lo hace `init.py`; tu trabajo es detectar, preguntar y reportar.

```sh
I=~/.local/share/autopilot-kit/init.py
```

## Arranque

1. **Detectar.** Corre `python3 "$I" . --detect` y lee el JSON:
   - `modo`: `repo` (la carpeta es un repo) o `workspace` (la carpeta contiene varios repos).
   - por repo: `ramas_remotas`, `rama_actual`, `sugerida` (primera de develop/dev/main/master que
     exista, o la rama por defecto del remoto), `azure` (org y proyecto deducidos del remoto),
     `sucio` (cambios sin commitear).
   - Si da error (no es repo ni contiene repos), díselo al usuario y para.

2. **Mostrar y preguntar la rama base.** Presenta una tabla corta: repo, rama sugerida, proyecto
   de Azure. Pregunta al usuario si confirma las sugeridas o cuáles cambia. **No asumas**: la rama
   base define desde dónde nacen todas las ramas de los workitems. Si un repo no tiene sugerida,
   muéstrale sus ramas remotas y pregunta. Si el usuario no quiere un repo en el sistema, anótalo.

   Si ya existe `autopilot.env`, dilo: solo se actualizarán las ramas base que confirme.

3. **Inicializar** con las ramas confirmadas:
   - repo: `python3 "$I" . --base <rama>`
   - workspace: `python3 "$I" . --base <repo1>=<rama> --base <repo2>=<rama> ...`
   - añade `--sin-azure` si el usuario no va a importar de Azure.

4. **Quitar repos excluidos** (solo workspace): si el usuario dejó fuera algún repo, borra su línea
   `REPO.<repo>=` de `autopilot.env` y su `SYNC.<repo>=` de `azure-sync.env`.

5. **Reportar** el JSON de salida en pocas líneas: qué se creó (`hecho`) y **todos** los `avisos`.
   Si hay avisos, explica qué hacer con cada uno (rama inexistente, falta
   ffmpeg para ver los videos de los bugs, **faltan herramientas de un repo** — p. ej. `fvm` con la
   versión de `.fvmrc`, `flutter`, `node` —: sin ellas el QA no puede certificar las tareas de ese
   repo y quedarán en `stopped`; di qué instalar; **falta o no es válido `.env.autopilot`** en
   un repo con `.env`: explica que lo crea el humano copiando `.env` y apuntando BD y URLs a QA/local,
   y que sin él no se ejecuta nada contra BD/API en ese repo).
   Avisos de **E2E** (solo si `E2E=true`): faltan herramientas → correr
   `~/.local/share/autopilot-kit/e2e-setup.sh`; falta o es `compartida` la `.env.autopilot.e2e` de un
   backend/front web → la crea el humano con una base de datos **exclusiva** de E2E (distinta de la de
   QA) y `PORT`; faltan cuentas → `E2E_<ROL>_USER` / `E2E_<ROL>_PASSWORD` en `.env.autopilot.e2e` junto
   a `autopilot.env`; falta `E2E_API.<app>` → cómo apuntar esa app Flutter al backend local.

6. **Config E2E.** `init.py` deja en `autopilot.env` un bloque E2E **apagado** (`E2E=false`) con lo que
   dedujo: `E2E_CLIENTS` (qué frontends consumen cada backend, por el nombre), `E2E_PLATFORMS` y
   `E2E_API` (la línea de la URL del API de cada app Flutter). Si `autopilot.env` ya existía y no tenía
   `E2E=`, se lo agrega al final. Muéstraselo al usuario, señala los frontends que quedaron sin
   backend ("Sin backend deducido") y pregúntale cuál es. No lo actives tú: el humano pone `E2E=true`
   cuando tenga las herramientas, la base E2E y las cuentas (ver README).

7. **Siguiente paso**, en una línea:
   - Azure: el sprint está en `@current` (sprint actual del equipo `<Proyecto> Team`). El PAT se
     toma de `~/.config/autopilot-kit/ado-mcp.secrets.env` si existe; si no, explica dónde ponerlo
     (nunca lo pidas en el chat).
   - Luego: `/azure-sync` para importar y `/autopilot` para trabajar.

## Qué NO hace

- No toca archivos versionados de los repos ni su `.gitignore`: lo del kit se ignora solo en la
  copia local (`.git/info/exclude`) o vive en la carpeta padre del workspace.
- No crea ramas, no hace commits, no hace push.
- No sobrescribe un `autopilot.env` o `azure-sync.env` existentes (salvo las ramas base que pases).
