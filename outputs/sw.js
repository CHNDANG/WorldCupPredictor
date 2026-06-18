const CACHE_NAME = "worldcup-radar-shell-v1";
const SHELL_ASSETS = [
  "./worldcup-predictions.html",
  "./manifest.webmanifest",
  "./assets/app-icon.svg",
  "./assets/worldcup-hero.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  const isDynamicData = url.pathname.endsWith(".json") || url.pathname.startsWith("/api/");
  if (isDynamicData) {
    event.respondWith(fetch(request, { cache: "no-store" }));
    return;
  }

  const isNavigation = request.mode === "navigate";
  if (isNavigation) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("./worldcup-predictions.html", copy));
          return response;
        })
        .catch(() => caches.match("./worldcup-predictions.html"))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    }))
  );
});
