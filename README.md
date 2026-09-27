# dotenvs

Kit portable de un **sistema de desarrollo autónomo sobre Notion** para OpenCode.

Dos subsistemas independientes, ambos opt-in por proyecto:

| Comando | Qué hace | Consume tokens |
|---|---|---|
| `/autopilot` | Detecta tareas en un tablero de Notion y las trabaja con subagentes. Ciclo completo: `New` → `In Progress` → `QA` → `Validando` → `Done`, con `Bug Fix` hasta 3 intentos. | sí |
| `/azure-sync` | Importa Work Items de Azure DevOps al tablero como `New`. Aditivo, con dedup. | no |

---

## Qué incluye

```
dotenvs/
├── install.sh                          # instalador (mergea, no pisa)
├── config/opencode.fragment.json       # agents + commands, SIN el MCP
├── skills/
│   ├── notion-autopilot/
│   │   ├── SKILL.md                    # reglas, maquina de estados, ciclo
│   │   ├── watcher.sh                  # sensor: consulta Notion y retorna
│   │   ├── notion-set.sh               # unica via de escritura (REST API)
│   │   └── plantilla.env
│   └── azure-sync/
│       ├── SKILL.md
│       ├── azure-sync.py               # importador aditivo con dedup
│       └── plantilla.env
└── examples/proyecto/
    ├── notion-autopilot.env.example
    └── azure-sync.env.example
```

---

## Instalación

```sh
git clone <tu-repo> dotenvs
cd dotenvs
./install.sh --with-mcp-notion
```

`install.sh`:

- copia las skills a `~/.config/opencode/skills/`
- **mergea** `config/opencode.fragment.json` en tu `opencode.json` (solo claves que no existan)
- **hace backup** de `opencode.json` antes de tocarlo
- opcionalmente instala el MCP de Notion
- opcionalmente genera un `.env` de ejemplo en un proyecto

Nunca sobrescribe `mcp`, `model`, `permissions` ni nada que ya exista. Si una clave
ya está, la deja y te avisa.

### Desinstalar

```sh
./install.sh --uninstall
```

Restaura `opencode.json` desde el backup más reciente. Los `.env` de cada proyecto
quedan intactos.

---

## Configurar un proyecto

Cada proyecto decide si participa. **Sin el `.env`, el proyecto no entra.**

```sh
cd /mi/proyecto
cp dotenvs/examples/proyecto/notion-autopilot.env.example notion-autopilot.env
# o:  ./install.sh -- /mi/proyecto    (genera el .env con REPO_PATH correcto)
```

Editá el `.env`:

| Variable | Dónde obtenerla |
|---|---|
| `NOTION_TOKEN` | Crear integración en https://www.notion.so/my-integrations |
| `NOTION_DATABASE_ID` | El ID del tablero, en su URL |
| `NOTION_LOG_DB_ID` | El ID de la base de datos de log |
| `REPO_PATH` | Ruta absoluta del repo (el instalador la pone) |

Después, **compartí el tablero y el log con la integración** en Notion
(`···` → Connections). Sin eso el watcher da 404.

El PAT de Azure DevOps va aparte, para que la config se pueda versionar:

```sh
echo 'AZURE_DEVOPS_PAT=xxx' > azure-sync.secrets.env
echo '*.secrets.env' >> .gitignore
```

---

## Uso

```sh
/autopilot     # arranca el bucle: espera tareas y las trabaja
/azure-sync    # importa Work Items de Azure al tablero
```

En un proyecto sin el `.env`, ambos comandos dicen que el proyecto no participa
y no hacen nada.

### El watcher es bloqueante

`/autopilot` lanza `watcher.sh` en primer plano. Es una decisión deliberada:

- **No gasta tokens mientras espera.** No hay turnos de modelo mientras la llamada
  de shell no retorna.
- **No hay sesión duplicada.** Un demonio (`setsid`) abriría su propia sesión de
  OpenCode por detección, con tokens aparte.

**Limitación:** en primer plano, el watcher muere si el turno se cierra o el
usuario cierra OpenCode. No sobrevive a la ausencia.

`azure-sync` sí puede correr como demonio, porque no lanza agentes:

```sh
setsid nohup python3 ~/.config/opencode/skills/azure-sync/azure-sync.py \
  --config ./azure-sync.env --watch 60 &>/dev/null &
```

---

## Reglas de trabajo

Fijadas en `SKILL.md`, se aplican sin que nadie las recuerde:

- **Una sola tarea a la vez.** Máximo 1 en `In Progress`.
- **Una rama por tarea:** `task/<slug>` desde la principal.
- **El agente nunca hace `push` ni `merge`.** Bloqueado por permiso, no por instrucción.
- **QA solo lee.** No puede editar ni commitear.
- **`Bug Fix` tiene prioridad** sobre trabajo nuevo: siempre se toma primero.
- **3 intentos** de certificación. Al cuarto, `Stopped` con el historial.
- **`Stopped` es para el humano**, con motivo escrito. Nunca inventar.

---

## Seguridad

- El kit **no contiene secretos**. Solo plantillas con `REEMPLAZAR`.
- `.gitignore` bloquea `*.env`, `*.secrets.env` y los `.log`.
- Verificado que un `.env` real con token `ntn_` no llega al índice de git.
- El token y el PAT **nunca** se hardcodean: van en variables de entorno o en
  `*.secrets.env`.

---

## Cuentas

La API REST de Notion **no permite modificar las opciones de un select existente**.
Para cambiar los estados del tablero hay que usar el MCP, que soporta DDL:

```
ALTER COLUMN "Estado" SET SELECT('New':gray, 'In Progress':blue, ...)
```

Los estados que crea el kit: `New`, `In Progress`, `QA`, `Validando`,
`Bug Fix`, `Stopped`, `Done`.
