/*
 * The app's service worker (D.14). It keeps the app's own files (the page, its
 * scripts, styles, fonts and icons) so the app opens fast and can be installed
 * on a phone or computer. It never keeps API data: bills, amounts and anything
 * under /api always come from the server, so nothing can be out of date or
 * left behind on a shared computer.
 */
const VERSION = "v1";
const ASSETS = `assets-${VERSION}`; // files with a hash in their name: they never change
const PAGE = `page-${VERSION}`; // the app's page, for opening it without a connection
const MAX_ASSETS = 150;

/**
 * What to do with a request: "skip" (straight to the network, not kept),
 * "asset" (kept; served from the cache first) or "page" (the network first,
 * the kept page when offline).
 */
function kind(url, origin, mode, method) {
  if (method !== "GET" || url.origin !== origin) return "skip";
  if (url.pathname.startsWith("/api/") || url.pathname === "/api") return "skip";
  if (mode === "navigate") return "page";
  if (/^\/(assets|icons)\//.test(url.pathname)) return "asset";
  return "skip";
}

async function trim(cache) {
  const keys = await cache.keys();
  for (const old of keys.slice(0, Math.max(0, keys.length - MAX_ASSETS))) await cache.delete(old);
}

async function asset(request) {
  const cache = await caches.open(ASSETS);
  const kept = await cache.match(request);
  if (kept) return kept;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    await trim(cache);
  }
  return response;
}

async function page(request) {
  const cache = await caches.open(PAGE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put("/", response.clone());
    return response;
  } catch (error) {
    const kept = await cache.match("/");
    if (kept) return kept;
    throw error;
  }
}

self.addEventListener("install", () => {
  void self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name !== ASSETS && name !== PAGE) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const what = kind(new URL(request.url), self.location.origin, request.mode, request.method);
  if (what === "asset") event.respondWith(asset(request));
  else if (what === "page") event.respondWith(page(request));
});
