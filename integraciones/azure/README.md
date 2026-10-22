# Integración: Azure DevOps → board del autopilot

El autopilot **no depende de Azure**: trabaja lo que hay en su board. Esta carpeta es una integración
**opcional y externa** que trae Work Items de Azure DevOps al board escribiendo directamente los `.md`
(crea tareas en `new/` y guarda sus adjuntos), sin depender del kit. Sirve también de
ejemplo para escribir una integración con otro tracker.

| Archivo | Qué es |
|---|---|
| `azure-sync.py` | importador aditivo de Work Items (uno o varios proyectos) |
| `skill/` | skill `/azure-sync` para OpenCode y Claude Code |
| `ado-mcp.sh` | lanza el MCP local de Azure DevOps con tu PAT (opcional) |
| `azure-sync.env.example` | config por proyecto |
| `instalar.sh` | instala todo lo anterior (requiere el kit ya instalado) |

## Instalar

```sh
./install.sh --local <proyecto>                  # primero el kit local del autopilot
./install.sh --azure --local <proyecto>           # o SOLO Azure, sin el kit del autopilot
integraciones/azure/instalar.sh --local <proyecto>     # skill /azure-sync + scripts
integraciones/azure/instalar.sh --local <proyecto> --with-mcp <org>  # además registra el MCP
integraciones/azure/instalar.sh --uninstall --local <proyecto>
```

La instalación es **local al proyecto** (no toca tu config global). Con `--azure` no hace falta el kit:
`azure-sync.py` es autocontenido (escribe directo los `.md` del board), así que se instala solo
`/azure-sync` enrutado en la carpeta del proyecto.

Los scripts quedan en `<proyecto>/.autopilot/integraciones/azure/`. El MCP de Azure DevOps se registra
solo en el proyecto: `.opencode/opencode.json` (OpenCode) o `.mcp.json` (Claude Code). Nada se commitea
(bloque del kit en tu `.gitignore`). `./install.sh --uninstall` quita la copia GLOBAL de la versión
vieja; `--uninstall --local <proyecto>` quita la de esa carpeta.

## Configurar un proyecto

Con el proyecto ya preparado (`/autopilot-init`), copia `azure-sync.env.example` a la raíz del proyecto
(junto a `autopilot.env`) como `azure-sync.env`:

```ini
AZURE_ORG=codikasrl

# Un repo
AZURE_PROJECT=Konectame_App_Clientes
AZURE_ITERATION=@current

# Workspace: una fuente por repo -> SYNC.<carpeta>=<proyecto de Azure>|<sprint>
SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current
SYNC.Konectame_BackOffice=Konectame_BackOffice|@current
```

- **Sprint:** `@current` = sprint actual del equipo `<Proyecto> Team` (se actualiza solo al
  cambiar de sprint); `@current:<Equipo>` para otro equipo; o una ruta fija `Proyecto\Sprint X`.
- En un workspace cada tarea se crea con su `repo:`. Cada `SYNC.<repo>` necesita su `REPO.<repo>` en `autopilot.env`.
- En modo un repo, agrega `azure-sync.env` a `.git/info/exclude` para no commitearlo.
- **Destino:** por defecto importa al board de `autopilot.env` (`WORKITEMS_DIR`, o `.workitems/`).
  `BOARD_DIR=<carpeta>` en `azure-sync.env` (relativo a ese archivo) o `--board <carpeta>` lo cambian;
  el flag gana. Los adjuntos van a `<carpeta>/adjuntos/`. El autopilot solo trabaja las tareas de su
  propio board.
- **Ignorar:** `IGNORE_DIRS=<carpeta>[,<carpeta>...]` (relativo a `azure-sync.env`) salta los work items
  que tengan su `<tipo>-<numero>*.md` en esas carpetas o sus subcarpetas: los ya sincronizados que
  sacaste del board. Si una carpeta no existe, el sync no corre (para no re-importarlos).
- **PAT:** se busca en la variable `AZURE_DEVOPS_PAT`, en el propio `azure-sync.env`
  (`AZURE_DEVOPS_PAT=`), en `azure-sync.secrets.env` (junto al config) y, si no, en el del MCP
  (`~/.config/autopilot-kit/ado-mcp.secrets.env`). Prioridad: variable > `azure-sync.env` >
  `azure-sync.secrets.env` > MCP. Cuanto más cerca del repo esté el PAT, peor: si lo ponés en
  `azure-sync.env` no lo commitees (modo un repo: `.git/info/exclude`). Nunca en el chat.

## Uso

```sh
/azure-sync       # desde el agente: dry-run, confirma e importa
```

```sh
cd /ruta/al/proyecto           # donde está azure-sync.env
azure-sync --dry-run           # qué importaría
azure-sync                     # importa
azure-sync --config otra/azure-sync.env --board /otro/board
```

**Crear la config desde la terminal** (no esperes a `/azure-sync` ni edites a mano):

```sh
azure-sync --init            # copia azure-sync.env.example a azure-sync.env para completarla
azure-sync --set AZURE_ORG=codikasrl \
           --set AZURE_PROJECT=Konectame_App_Clientes \
           --set AZURE_ITERATION=@current
# workspace: una --set por repo, estilo SYNC.<carpeta>=<proyecto>|<sprint o @current>
azure-sync --set 'SYNC.Konectame_BackOffice=Konectame_BackOffice|@current'
```

`--init` copia el ejemplo (no pisa si ya existe). Si `azure-sync.env` no existe, `--set` lo crea a
partir del ejemplo (comentarios incluidos) y activa la línea `SYNC.` correspondiente en vez de
duplicarla. El PAT también podés ponerlo acá con `--set AZURE_DEVOPS_PAT=...` (prioridades y
advertencias: ver la sección Configurar un proyecto).

Importa a `new/` los work items **Task/Bug en estado New** del sprint, con clave `<tipo>-<id del work
item>` (p. ej. `bug-140123`) y `origen: azure:<proyecto>`. Solo crea, nunca modifica; no gasta tokens;
deduplica por id (los IDs son únicos en la organización).

- Si **cualquier** fuente falla, no se escribe nada en el board.
- `--refrescar [clave…]` vuelve a traer de Azure la descripción, el criterio y los adjuntos de tareas
  **ya importadas** (sin claves: todas). No cambia su estado ni toca notas, reportes ni feedback.
- `--dry-run` muestra qué importaría (con cuántas imágenes/videos); `--status` cuenta por fuente;
  `--watch 60` en bucle; `--fotogramas` procesa videos ya descargados (tras instalar ffmpeg).

Puede correr como demonio, porque no lanza agentes:

```sh
setsid nohup azure-sync --config ./azure-sync.env --watch 60 &>/dev/null &
```

### Adjuntos: capturas y videos

Cada work item importado trae sus adjuntos a `.workitems/adjuntos/<clave>/` (en el board aparecen como
*Tarea original*):

- **Imágenes** de la descripción o los pasos: se descargan y quedan referenciadas en su lugar en el
  texto como `📷 <archivo> — imagen N`.
- **Adjuntos** del work item (imágenes, videos, otros), listados en la sección `## Adjuntos`.
- **Videos:** con `ffmpeg` instalado se extraen hasta 12 fotogramas (primer cuadro + cambios de
  escena, repartidos) en `<video>.frames/fNN.png`, porque ningún modelo ve video directamente.
  Sin ffmpeg se guarda el video y queda la nota; después: `azure-sync.py --config ... --fotogramas`.
  **Requisito:** `sudo apt install ffmpeg`.
- Límite de 50 MB por archivo. Un adjunto que falla no frena la importación: queda anotado.

## MCP de Azure DevOps (opcional)

Usa el [servidor local oficial de Microsoft](https://github.com/microsoft/azure-devops-mcp)
(`@azure-devops/mcp`) con **autenticación por PAT**:

- **No requiere admin** de la organización ni del tenant. El servidor *remoto*
  (`mcp.dev.azure.com`) sí lo requiere para clientes como OpenCode y Claude Code (app registration +
  admin consent en Entra ID), por eso no se usa.
- Requisitos: Node 20+, organización respaldada por Entra ID, y un PAT personal con
  **Work Items (Read & Write)**.
- El PAT **nunca** va en la config del cliente: `ado-mcp.sh` lo lee de
  `~/.config/autopilot-kit/ado-mcp.secrets.env` (o de `AZURE_DEVOPS_PAT`) y lo pasa al MCP.
- Dominios cargados: `core work work-items`.

Guardar el PAT (en tu terminal, no en el chat del agente):

```sh
(umask 077; read -rsp 'PAT: ' p; echo; printf 'AZURE_DEVOPS_PAT=%s\n' "$p" > ~/.config/autopilot-kit/ado-mcp.secrets.env)
```

La importación la hace `azure-sync.py` (sin tokens, con dedup). El MCP sirve para consultar Azure
desde el agente; el autopilot no lo usa ni escribe de vuelta en Azure.
