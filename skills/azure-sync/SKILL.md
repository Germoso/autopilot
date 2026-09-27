---
name: Azure Sync
description: Importa tareas de Azure DevOps al tablero de Notion como New. Usar cuando el usuario mencione azure-sync, sincronizar Azure, importar work items, Work Items de Azure, o /azure-sync. NO usar en proyectos sin azure-sync.env.
slash: true
---

# Azure Sync — importador de Azure DevOps al tablero de Notion

Trae los Work Items de un sprint de Azure DevOps al tablero, en estado `New`,
para que el autopilot pueda trabajar sobre ellos.

## Cuándo usar

Solo si el proyecto tiene `azure-sync.env` en la raíz. Si no existe, el proyecto
**no importa de Azure**. No lo busques en otro sitio ni lo adivines.

## Qué es y qué no es

Es **aditivo**, igual que el script original `sync_workitems.py`:

| Garantía | Cómo se cumple |
|---|---|
| Solo crea, nunca modifica | Un solo endpoint `POST /v1/pages`. Nunca PATCH ni DELETE sobre el tablero |
| Dedup por idempotency | Busca `azure-<id>` en el título de cada tarea del tablero. Si ya está, la salta |
| Idempotente | Correrlo N veces crea la tarea una sola vez. Las otras N-1 son `no-op` |
| Falla ruidosa | Si Azure o Notion fallan, sale con código ≠ 0 y no toca el tablero |
| El PAT nunca se hardcodea | Se lee del entorno o de `azure-sync.secrets.env` |

**Nunca** mueve, borra ni sobrescribe una tarea existente. **Nunca** borra ni archiva.
El script original `/home/user/sync_workitems.py` no se modifica.

## activating

```sh
S=~/.config/opencode/skills/azure-sync
P=<PROYECTO>

# una pasada
python3 "$S/azure-sync.py" --config "$P/azure-sync.env"

# ver que haria, sin escribir nada
python3 "$S/azure-sync.py" --config "$P/azure-sync.env" --dry-run

# solo diagnostico
python3 "$S/azure-sync.py" --config "$P/azure-sync.env" --status

# bucle continuo
python3 "$S/azure-sync.py" --config "$P/azure-sync.env" --watch 60
```

## Criterio de filtro

Solo entra lo que está en estado **`New`** en Azure, del sprint configurado en
`AZURE_ITERATION`, de tipo `Task` o `Bug`.

Cuando mueves un work item a otro estado en Azure, el script deja de verlo, **pero la
tarea sigue en el tablero** con el estado que le puso el autopilot. No hay reconciliación
en sentido inverso: el tablero no refleja Azure en tiempo real, solo se alimenta de él.

## Mapeo de prioridad

| Azure `Priority` | Notion |
|---|---|
| 1 | `Critical` |
| 2 | `High` |
| 3 | `Medium` |
| 4 | `Low` |
| ausente | `Medium` |

## Qué escribe en cada tarea

| Propiedad | Valor |
|---|---|
| `Name` | `[azure-<id>] <título del work item>` |
| `Estado` | `New` |
| `Prioridad` | mapeada desde Azure |
| `Descripción` | descripción del work item, HTML limpiado a texto |
| `Criterio de aceptación` | `ReproSteps` si existe, si no `_Sin criterio en Azure._` |
| `Repo` | `_azure:_` |
| `Resultado` | marca de sincronización y project de origen |

El prefijo `[azure-<id>]` es lo que hace funcionar el dedup **y** te deja localizar
el work item de un vistazo en el kanban.

## Configurar un proyecto nuevo

```sh
cp ~/.config/opencode/skills/azure-sync/plantilla.env /mi-proyecto/azure-sync.env
# editar AZURE_ORG, AZURE_PROJECT, AZURE_ITERATION, NOTION_*
echo 'AZURE_DEVOPS_PAT=xxx' > /mi-proyecto/azure-sync.secrets.env
```

`azure-sync.secrets.env` debe estar en `.gitignore`.

## Diferencia con el autopilot

| | azure-sync | autopilot |
|---|---|---|
| Qué hace | crea filas en `New` | trabaja las tareas |
| Consume tokens | **no** | sí |
| Puede ser demonio | **sí**, con `setsid` | no, corre en el hilo |
| Cuándo corre | 24/7 si querés | mientras haya un turno |

azure-sync no lanza agentes, así que es seguro correrlo en background. Si importó algo
y hay tareas en `New`, puedes encadenar `/autopilot` en el mismo turno.

## Lo que NUNCA debes hacer

- Modificar o borrar tareas que ya existen en el tablero
- Hardcodear el PAT en cualquier archivo
- Usar el MCP de Notion para escribir: azure-sync escribe por REST
- Modificar `/home/user/sync_workitems.py` ni el kanban de Hermes
- Correr sin `azure-sync.env` en el proyecto
