// The installable app (D.14), checked in the installed Edge: the manifest is
// served, the service worker takes control, and after using the app its cache
// holds only the app's own files, never anything from /api.
//   node pwa-check.mjs            (the demo running: scripts\demo-up.cmd)
import { chromium } from "playwright-core";

const BASE = process.env.AUDIT_BASE ?? "http://localhost:5173";
const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await (await browser.newContext()).newPage();
await page.goto(`${BASE}/login`);
const manifest = await page.evaluate(async () => {
  const href = document.querySelector('link[rel="manifest"]')?.getAttribute("href");
  return href ? (await fetch(href)).json() : null;
});
await page.evaluate(() => navigator.serviceWorker.ready);
await page.reload(); // now under the worker
await page.getByLabel("Email").fill("nobody@example.com"); // one API call (refused)
await page.getByLabel("Password").fill("not a real password");
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForTimeout(1500);
const kept = await page.evaluate(async () => {
  const out = [];
  for (const name of await caches.keys()) {
    for (const r of await (await caches.open(name)).keys()) out.push(new URL(r.url).pathname);
  }
  return out;
});
const controlled = await page.evaluate(() => Boolean(navigator.serviceWorker.controller));
await browser.close();

const api = kept.filter((p) => p.startsWith("/api"));
console.log(`manifest: ${manifest ? `${manifest.short_name}, ${manifest.icons.length} icons` : "MISSING"}`);
console.log(`service worker in control: ${controlled}`);
console.log(`kept: ${kept.length} files (${kept.filter((p) => p.startsWith("/assets/")).length} under /assets)`);
console.log(`kept from /api: ${api.length}`);
if (!manifest || !controlled || api.length > 0) process.exit(1);
