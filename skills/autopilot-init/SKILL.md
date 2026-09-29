---
name: autopilot-init
description: Prepara la carpeta actual para el autopilot. Detecta si es un repo o un workspace con varios repos, propone la rama base de cada uno, pregunta, y crea autopilot.env, azure-sync.env y el board. Usar cuando el usuario diga /autopilot-init, "inicializa el autopilot", "prepara este proyecto" o similar, o cuando /autopilot o /azure-sync digan que el proyecto no participa y el usuario quiera sumarlo.
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
   Si hay avisos, explica qué hacer con cada uno (rama inexistente, cambios sin commitear, falta
   ffmpeg para ver los videos de los bugs, **faltan herramientas de un repo** — p. ej. `fvm` con la
   versión de `.fvmrc`, `flutter`, `node` —: sin ellas el QA no puede certificar las tareas de ese
   repo y quedarán en `stopped`; di qué instalar).

6. **Siguiente paso**, en una línea:
   - Azure: el sprint está en `@current` (sprint actual del equipo `<Proyecto> Team`). El PAT se
     toma de `~/.config/autopilot-kit/ado-mcp.secrets.env` si existe; si no, explica dónde ponerlo
     (nunca lo pidas en el chat).
   - Luego: `/azure-sync` para importar y `/autopilot` para trabajar.

## Qué NO hace

- No toca archivos versionados de los repos ni su `.gitignore`: lo del kit se ignora solo en la
  copia local (`.git/info/exclude`) o vive en la carpeta padre del workspace.
- No crea ramas, no hace commits, no hace push.
- No sobrescribe un `autopilot.env` o `azure-sync.env` existentes (salvo las ramas base que pases).
