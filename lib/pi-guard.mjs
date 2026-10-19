/**
 * pi-guard.mjs — guarda de comandos y de escritura para pi.
 *
 * pi no tiene hooks PreToolUse (Claude Code) ni permisos de bash por patron (OpenCode):
 * los bloqueos se hacen con una extension que intercepta `tool_call` y cancela la llamada.
 *
 * `guard(pi, role)` registra la extension para un rol (coder | qa | e2e | todos).
 * Reusa la MISMA logica probada del kit:
 *   - lib/git-guard.sh  <rol>   -> bloquea push/merge/pull, lo que toque un ambiente sin
 *                                  aenv.sh/e2e.sh, la escritura de .env* y (modo e2e) apps
 *                                  y navegador fuera de e2e.sh. Lee el JSON del hook por stdin.
 *   - lib/escritura.sh  <rol>   -> bloquea escrituras fuera de lo permitido (coder: nada de
 *                                  .env* y reserva de archivos; qa/e2e: solo sus worktrees).
 *                                  Lee el JSON del hook por stdin.
 *
 * Los wrappers pi-guard-<rol>.mjs fijan el rol y exponen la extension: cada agente generado
 * (agents/*.md -> front_pi) la referencia con `subagentOnlyExtensions` para que se cargue
 * SOLO en las sesiones hijas (coder/qa/e2e), nunca en la sesion principal. project() instala
 * pi-guard-todos.mjs en .pi/extensions/ del proyecto para proteger tambien al agente principal.
 *
 * Un guard que falla (error interno) NO bloquea (fail-open): el prompt del agente ya trae
 * las reglas; la extension es la red real por si el modelo intenta saltarselas.
 */
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
const TIMEOUT = 10_000; // ms; un guard que se cuelga cancela la llamada como fallo

function correr(script, role, payload) {
  try {
    execFileSync("bash", [join(AQUI, script), role], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
      timeout: TIMEOUT,
      env: { ...process.env, KIT: AQUI },
    });
    return null;
  } catch (e) {
    // git-guard.sh / escritura.sh salen con codigo 2 cuando la operacion esta prohibida.
    if (e && e.status === 2) {
      const motivo = String(e.stderr || e.stdout || "").trim() || "operacion bloqueada por el autopilot";
      return motivo;
    }
    // Cualquier otro fallo del guard (no encontro python, timeout...): no bloqueamos.
    return null;
  }
}

export function guard(pi, role) {
  pi.on("tool_call", async (event) => {
    try {
      if (event.toolName === "bash") {
        const command = String((event.input && event.input.command) || "").trim();
        if (!command) return;
        const motivo = correr("git-guard.sh", role, { tool_input: { command } });
        if (motivo) return { block: true, reason: motivo };
      } else if (event.toolName === "edit" || event.toolName === "write") {
        // pi usa `path`; aceptamos tambien `file_path`/`notebook_path` (Claude) por si acaso.
        const input = event.input || {};
        const path = String(input.path || input.file_path || input.notebook_path || "").trim();
        if (!path) return;
        const motivo = correr("escritura.sh", role, { tool_input: { file_path: path, notebook_path: "" } });
        if (motivo) return { block: true, reason: motivo };
      }
    } catch (e) {
      console.error("[autopilot-pi-guard]", role, e);
    }
  });
}

/** Fabrica de extensiones estilo default-export: `export default makeGuard("coder")`. */
export function makeGuard(role) {
  return function autopilotGuard(pi) {
    guard(pi, role);
  };
}

export default guard;
