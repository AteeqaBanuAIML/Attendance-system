const CACHE_NAME = "attendance-system-v2";

const urlsToCache = [
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

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});