// Config de Playwright del agente e2e-tester (la aplica e2e.sh web; no se usa otra).
// - Capturas, video y traza siempre, en <copia-e2e>/.e2e-capturas/web.
// - Nunca contra produccion: Chromium NO resuelve ningun host salvo localhost y los CDN estaticos de
//   fuentes/recursos de Google. Cualquier otra llamada (p. ej. a una API real) falla con
//   ERR_NAME_NOT_RESOLVED y queda anotada en red-bloqueada.txt (ver e2e-pasos.cjs).
const path = require("path");
const { defineConfig, devices } = require(path.join(process.env.E2E_NODE_MODULES, "@playwright/test"));

const spec = process.env.E2E_SPEC;
const salida = process.env.E2E_SALIDA;
const esArchivo = /\.(c|m)?(j|t)s$/.test(spec);
const REGLAS = [
  "MAP * ~NOTFOUND",
  "EXCLUDE localhost",
  "EXCLUDE 127.0.0.1",
  "EXCLUDE fonts.gstatic.com",
  "EXCLUDE fonts.googleapis.com",
  "EXCLUDE www.gstatic.com",
].join(", ");
const navegador = { launchOptions: { args: ["--host-resolver-rules=" + REGLAS] } };

module.exports = defineConfig({
  testDir: esArchivo ? path.dirname(spec) : spec,
  testMatch: esArchivo ? path.basename(spec) : /.*\.(spec|test)\.(c|m)?(j|t)s$/,
  outputDir: path.join(salida, "resultados"),
  timeout: 180000,
  expect: { timeout: 20000 },
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: path.join(salida, "resultado.json") }]],
  use: {
    screenshot: "on",
    video: "on",
    trace: "retain-on-failure",
    actionTimeout: 20000,
    navigationTimeout: 60000,
  },
  projects: [
    { name: "web-movil", use: { ...devices["Pixel 7"], ...navegador } },
    { name: "web-escritorio", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, ...navegador } },
  ],
});
