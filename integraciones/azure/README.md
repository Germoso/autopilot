# Integración: Azure DevOps → board del autopilot

El autopilot **no depende de Azure**: trabaja lo que hay en su board. Esta carpeta es una integración
**opcional y externa** que trae Work Items de Azure DevOps al board, usando la misma API que usarías
a mano (`workitems.py` del kit: crear tareas en `new/` y guardar sus adjuntos). Sirve también de
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
./install.sh                                   # primero el kit del autopilot (raíz del repo)
./install.sh --azure                           # o SOLO Azure, sin el kit del autopilot
integraciones/azure/instalar.sh                # skill /azure-sync + scripts
integraciones/azure/instalar.sh --with-mcp <org>   # además registra el MCP de Azure DevOps
integraciones/azure/instalar.sh --uninstall
```

Con `./install.sh --azure` no hace falta el kit: se instala solo `/azure-sync` y una copia de lo mínimo del board
(`workitems.py` y `almacen.py` en `integraciones/azure/lib/`), sin skills ni agentes del autopilot. Si
después instalás el kit, volvé a correr `integraciones/azure/instalar.sh` y se usa el del kit.

Las dos formas instalan además el comando `azure-sync` en `~/.local/bin`, para usarlo desde la terminal.

Los scripts quedan en `~/.local/share/autopilot-kit/integraciones/azure/`. `./install.sh --uninstall`
del kit también desinstala la integración.

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
- **PAT:** se busca en `AZURE_DEVOPS_PAT`, `azure-sync.secrets.env` (junto al config) y, si no, en el
  del MCP (`~/.config/autopilot-kit/ado-mcp.secrets.env`). Nunca en un archivo versionado ni en el chat.

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
