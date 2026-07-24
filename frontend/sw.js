// ─── VERSION ──────────────────────────────────────────────────────────────────
// ⚠️  IMPORTANT: Change this version string on EVERY redeploy.
// The browser detects any byte-change in sw.js and installs the new worker.
// You can just increment the number, e.g. v3 → v4 → v5, each time you deploy.
const CACHE_VERSION = "attendance-v20260723-1050";
const CACHE_NAME = CACHE_VERSION;

const PRECACHE_URLS = [
  "./",
  "./index.html",
  "./page1.html",
  "./page2.html",
  "./page3.html",
  "./page4.html",
  "./manage.html",
  "./promotion.html",
  "./registeration.html",
  "./teachpage1.html",
  "./teachpage2.html",
  "./teachpage3.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];

// ─── INSTALL ──────────────────────────────────────────────────────────────────
// skipWaiting() makes the new SW take control immediately instead of waiting
// for all tabs to close first.
self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
});

// ─── ACTIVATE ─────────────────────────────────────────────────────────────────
// Delete all old caches, claim all open clients, then notify every open tab
// so the UI can show an "App updated — reload" banner.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((cacheNames) =>
        Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
      .then(() => {
        // Tell every open tab there is a new version available
        return self.clients.matchAll({ type: "window" }).then((clients) => {
          clients.forEach((client) =>
            client.postMessage({ type: "SW_UPDATED", version: CACHE_VERSION })
          );
        });
      })
  );
});

// ─── FETCH ────────────────────────────────────────────────────────────────────
// Network-First for HTML pages so users always get the freshest markup.
// Cache-First for static assets (images, icons) for speed.
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests; let API calls pass through normally
  if (url.origin !== self.location.origin) {
    return; // don't intercept external API calls
  }

  const isHTML = request.destination === "document" ||
                 url.pathname.endsWith(".html") ||
                 url.pathname === "/" ||
                 url.pathname === "";

  if (isHTML) {
    // Network-First: always try to fetch fresh HTML; fall back to cache if offline
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          // Update the cache with the fresh response
          const cloned = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
          return networkResponse;
        })
        .catch(() => caches.match(request))
    );
  } else {
    // Cache-First: serve assets from cache, update cache in background
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request).then((networkResponse) => {
          caches.open(CACHE_NAME).then((cache) => cache.put(request, networkResponse.clone()));
          return networkResponse;
        });
        return cached || networkFetch;
      })
    );
  }
});