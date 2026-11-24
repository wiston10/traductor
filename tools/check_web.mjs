// Comprueba que el JavaScript de las páginas no tiene errores de sintaxis (sin navegador).
// Uso: node tools/check_web.mjs
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dir = new URL("../apps/web/", import.meta.url).pathname;
let bad = 0;
for (const file of readdirSync(dir).filter((f) => f.endsWith(".html"))) {
  const html = readFileSync(join(dir, file), "utf8");
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  scripts.forEach((code, i) => {
    try { new Function(code); }
    catch (e) { bad++; console.error(`FALLA ${file} (script ${i + 1}): ${e.message}`); }
  });
  // Lección de Barnaba: una política de seguridad bloquea onclick="…" en el HTML (botones muertos)
  const inline = html.match(/\son(click|change|input|submit)=/gi);
  if (inline) { bad++; console.error(`FALLA ${file}: ${inline.length} manejadores en el HTML (usar addEventListener)`); }
  if (!bad) console.log(`OK    ${file} (${scripts.length} script)`);
}
process.exit(bad ? 1 : 0);
