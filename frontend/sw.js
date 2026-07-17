const CACHE_NAME = "attendance-system-v1";

const urlsToCache = [
  "/",
  "/index.html",
  "/page1.html",
  "/page2.html",
  "/page3.html",
  "/page4.html",
  "/manage.html",
  "/promotion.html",
  "/registeration.html",
  "/teachpage1.html",
  "/teachpage2.html",
  "/teachpage3.html"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});