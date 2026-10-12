---
name: azure-sync
description: Importa tareas de Azure DevOps al board de workitems (carpetas + .md) como new. Usar cuando el usuario mencione azure-sync, sincronizar Azure, importar work items, Work Items de Azure, o /azure-sync. NO usar en proyectos sin azure-sync.env.
---

# Azure Sync — importador de Azure DevOps al board de workitems

Trae los Work Items de un sprint de Azure DevOps al board, como archivos en `new/`,
para que el autopilot pueda trabajar sobre ellos.

## Cuándo usar

Solo si el proyecto tiene `azure-sync.env` en la raíz. Si no existe, el proyecto
**no importa de Azure**. No lo busques en otro sitio ni lo adivines.

## Qué es y qué no es

Es **aditivo**, igual que el script original `sync_workitems.py`:

| Garantía | Cómo se cumple |
|---|---|
| Solo crea, nunca modifica | Solo escribe archivos nuevos en `new/`. Nunca mueve, edita ni borra uno existente |
| Dedup por número | Si ya hay un `*-<id>-*.md` en **cualquier** carpeta del board, lo salta |
| Ignorados | También salta los que tengan su `*-<id>*.md` en las carpetas de `IGNORE_DIRS` (ya sincronizados, fuera del board) |
| Idempotente | Correrlo N veces crea la tarea una sola vez. Las otras N-1 son `no-op` |
| Falla ruidosa | Si Azure falla o el board no existe, sale con código ≠ 0 y no toca el board |
| El PAT nunca se hardcodea | Se lee del entorno o de `azure-sync.secrets.env` |

**Nunca** mueve, borra ni sobrescribe una tarea existente. **Nunca** borra ni archiva.
El script original `/home/user/sync_workitems.py` no se modifica.

Es una integración **externa** al autopilot: solo usa la API pública del board (`workitems.py` del kit
instalado), igual que `wi.sh add-task`. El autopilot no sabe que existe Azure.

## Arranque

1. Verifica que existe `azure-sync.env` en la raíz del proyecto actual. Si no existe, para y
   dile al usuario que este proyecto no importa de Azure (se prepara copiando
   `azure-sync.env.example` de la integración; ver "Configurar un proyecto nuevo"). No lo busques en otro sitio ni lo adivines.
2. Verifica que hay un PAT: variable `AZURE_DEVOPS_PAT`, `azure-sync.secrets.env` junto al
   config, o el del MCP (`~/.config/autopilot-kit/ado-mcp.secrets.env`), en ese orden. Si no hay, explica cómo configurarlo y para. **No lo pidas en el chat** ni lo
   escribas en un archivo versionado.
3. Corre primero en `--dry-run` y muestra el resumen: cuántos hay en New en Azure, cuántos ya
   están en el board y cuáles se importarían.
4. Si el usuario pidió sincronizar de verdad, corre sin `--dry-run` y reporta el JSON: cuántos
   se agregaron, cuántos se saltaron por duplicado y si hubo errores.
5. Si se importó algo, dile que puede encadenar `/autopilot`. No lo arranques salvo que lo pida.
6. Si el script devuelve error, no reintentes a lo bruto: reporta el error.

```sh
K=~/.local/share/autopilot-kit/integraciones/azure
P=<PROYECTO>

python3 "$K/azure-sync.py" --config "$P/azure-sync.env" --dry-run   # que haria, sin escribir
python3 "$K/azure-sync.py" --config "$P/azure-sync.env"             # una pasada
python3 "$K/azure-sync.py" --config "$P/azure-sync.env" --status    # solo diagnostico
python3 "$K/azure-sync.py" --config "$P/azure-sync.env" --watch 60  # bucle continuo
python3 "$K/azure-sync.py" --config "$P/azure-sync.env" --refrescar [clave...]  # re-trae descripcion/criterio/adjuntos de tareas ya importadas (no cambia estado ni notas)
```

### azure-sync.py vs el MCP de Azure DevOps

Si el MCP `azure-devops` está configurado, sirve para **consultar** Azure o **escribir de vuelta**
(comentarios, estado del work item). La **importación** al board se hace siempre con
`azure-sync.py`: no gasta tokens, deduplica y es idempotente. No importes a mano con el MCP.

## Fuentes: un repo o un workspace

`azure-sync.env` (lo genera `/autopilot-init` a partir del remoto de cada repo):

```ini
AZURE_ORG=codikasrl

# Un repo
AZURE_PROJECT=Konectame_App_Clientes
AZURE_ITERATION=@current

# Workspace: una línea por repo -> SYNC.<carpeta>=<proyecto de Azure>|<sprint>
SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current
SYNC.Konectame_BackOffice=Konectame_BackOffice|@current
```

- En un workspace, cada tarea se crea con `repo: <carpeta>`: así el autopilot sabe en qué repo
  crear su rama. Cada `SYNC.<carpeta>` debe tener su `REPO.<carpeta>` en `autopilot.env`.
- **Sprint**: una ruta (`Proyecto\Sprint X`) o `@current`, el sprint actual del equipo
  `<Proyecto> Team` (`@current:<Equipo>` para otro). Con `@current` no hay que editar nada al
  cambiar de sprint.
- Si **cualquier** fuente falla, no se escribe nada en el board.

## Adjuntos: capturas y videos

El board destino es el de `autopilot.env`, salvo que `azure-sync.env` tenga `BOARD_DIR=<carpeta>` (relativo a ese
archivo) o se pase `--board <carpeta>` (gana el flag).

Cada work item importado trae sus adjuntos a `<board>/adjuntos/<clave>/`:

- **Imágenes** de la descripción o los pasos: se descargan y quedan referenciadas en su lugar en el
  texto como `📷 <archivo> — imagen N` (no incrustadas; la app web las abre y las muestra en *Tarea original*).
- **Adjuntos** del work item (imágenes, videos, otros), listados en la sección `## Adjuntos`.
- **Videos:** con `ffmpeg` instalado se extraen hasta 12 fotogramas (primer cuadro + cambios de
  escena, repartidos) en `<video>.frames/fNN.png`, porque ningún modelo ve video directamente.
  Sin ffmpeg se guarda el video y queda la nota; después: `azure-sync.py --config ... --fotogramas`.
- Límite de 50 MB por archivo. Un adjunto que falla no frena la importación: queda anotado.

El autopilot le pasa las imágenes y fotogramas al coder, al QA y al agente E2E (`tarea.adjuntos`).

## Criterio de filtro

Solo entra lo que está en estado **`New`** en Azure, del sprint de cada fuente,
de tipo `Task` o `Bug`.

Cuando mueves un work item a otro estado en Azure, el script deja de verlo, **pero la
tarea sigue en el board** en la carpeta donde la dejó el autopilot. No hay reconciliación
en sentido inverso: el board no refleja Azure en tiempo real, solo se alimenta de él.

## Mapeo de prioridad

| Azure `Priority` | `prioridad` |
|---|---|
| 1 | `Critical` |
| 2 | `High` |
| 3 | `Medium` |
| 4 | `Low` |
| ausente | `Medium` |

## Qué escribe en cada tarea

Un archivo `new/<tipo>-<id>-<slug>.md`:

| Campo | Valor |
|---|---|
| nombre de archivo | `bug-140123-login-falla.md` — `tipo` sale de `System.WorkItemType` (`Bug` → `bug`, `Task` → `task`) |
| `# título` | `System.Title` |
| `id` | número del Work Item |
| `tipo` | `task` o `bug` |
| `prioridad` | mapeada desde Azure |
| `rama` | `<tipo>-<id>`: la rama que el autopilot creará desde `BASE_BRANCH` |
| `origen` | `azure:<project>` |
| `## Descripción` | descripción del work item, HTML convertido a Markdown |
| `## Criterio de aceptación` | `AcceptanceCriteria`, si no `ReproSteps`, si no `_Sin criterio en Azure._` (HTML convertido a Markdown: listas, encabezados e imágenes en su lugar) |
| `## Adjuntos` | capturas, videos y fotogramas (ver arriba) |

`<tipo>-<id>` es a la vez la clave de la tarea, la base del dedup y el nombre de la rama.

## Configurar un proyecto nuevo

1. El proyecto tiene que tener el autopilot preparado (`/autopilot-init`).
2. Copia `~/.local/share/autopilot-kit/integraciones/azure/azure-sync.env.example` (o el del repo del kit,
   `integraciones/azure/`) a la raíz del proyecto como `azure-sync.env` y completa org, proyecto y sprint
   (`@current` = sprint actual del equipo). En un workspace, una línea `SYNC.<repo>=<proyecto>|<sprint>` por repo.
3. PAT: si ya configuraste el MCP, se reutiliza `~/.config/autopilot-kit/ado-mcp.secrets.env`.

`azure-sync.secrets.env` debe estar en `.gitignore`.

## Diferencia con el autopilot

| | azure-sync | autopilot |
|---|---|---|
| Qué hace | crea archivos en `new/` | trabaja las tareas |
| Consume tokens | **no** | sí |
| Puede ser demonio | **sí**, con `setsid` | no, corre en el hilo |
| Cuándo corre | 24/7 si querés | mientras haya un turno |

azure-sync no lanza agentes, así que es seguro correrlo en background. Si importó algo
y hay tareas en `new/`, puedes encadenar `/autopilot` en el mismo turno.

## Lo que NUNCA debes hacer

- Modificar, mover o borrar tareas que ya existen en el board
- Hardcodear el PAT en cualquier archivo
- Modificar `/home/user/sync_workitems.py`
- Correr sin `azure-sync.env` en el proyecto
