// The first page's download size: every script and stylesheet web/dist/index.html
// loads or preloads, gzipped (level 9), in KB. Build the web app first.
//   node first-load.mjs [web/dist folder]     (from tools/design-audit)
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const dist = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../web/dist");
const html = readFileSync(path.join(dist, "index.html"), "utf8");
const files = [...new Set([...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]))];
let total = 0;
for (const f of files) {
  const kb = gzipSync(readFileSync(path.join(dist, f)), { level: 9 }).length / 1000;
  total += kb;
  console.log(`${f}: ${kb.toFixed(1)} KB`);
}
console.log(`first load: ${total.toFixed(1)} KB gzip`);
