// Ayudas para las pruebas web del agente e2e-tester. En la prueba:
//   const { test, expect, paso, semantica } = require(process.env.E2E_PASOS);
//   test("c1 login", async ({ page }) => {
//     await page.goto(URL); await semantica(page);          // apps Flutter web
//     await paso(page, "c1", "pantalla inicial");            // captura en cada paso
//     ...
//   });
// Las capturas quedan en <copia-e2e>/.e2e-capturas/web/capturas/<criterio>-web-<nn>-<paso>.png.
// Cada host que la app intento y el navegador bloqueo queda en red-bloqueada.txt.
const fs = require("fs");
const path = require("path");
const base = require(path.join(process.env.E2E_NODE_MODULES, "@playwright/test"));

const SALIDA = process.env.E2E_SALIDA;
const CAPTURAS = path.join(SALIDA, "capturas");
fs.mkdirSync(CAPTURAS, { recursive: true });
const contador = {};

const slug = (t) =>
  String(t).normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").toLowerCase().slice(0, 60) || "paso";

const test = base.test.extend({
  page: async ({ page }, use) => {
    page.on("requestfailed", (req) => {
      const err = (req.failure() || {}).errorText || "";
      if (err.includes("ERR_NAME_NOT_RESOLVED")) {
        fs.appendFileSync(path.join(SALIDA, "red-bloqueada.txt"), `${new Date().toISOString()} ${req.url()}\n`);
      }
    });
    await use(page);
  },
});

// Captura de pantalla de un paso: antes y despues de cada accion relevante.
async function paso(page, criterio, descripcion) {
  const c = slug(criterio);
  contador[c] = (contador[c] || 0) + 1;
  const archivo = path.join(CAPTURAS, `${c}-web-${String(contador[c]).padStart(2, "0")}-${slug(descripcion)}.png`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: archivo, fullPage: false });
  const info = base.test.info();
  await info.attach(`${c} ${descripcion}`, { path: archivo, contentType: "image/png" });
  console.log(`CAPTURA ${archivo}`);
  return archivo;
}

// Flutter web dibuja en un canvas: activa su arbol de accesibilidad para poder usar
// getByRole / getByText / getByLabel y escribir en los campos.
async function semantica(page, timeout = 60000) {
  await page.waitForSelector("flt-semantics-placeholder, flutter-view, flt-glass-pane", { state: "attached", timeout });
  await page.evaluate(() => {
    const b = document.querySelector("flt-semantics-placeholder");
    if (b) b.click();
  });
  await page.waitForSelector("flt-semantics, flt-semantics-host", { state: "attached", timeout: 15000 }).catch(() => {});
}

module.exports = { test, expect: base.expect, paso, semantica };
