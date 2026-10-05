{% load static %}
// Service worker de Arca. Por ahora solo instalabilidad y un "shell" mínimo
// en caché: la app carga algo (y una pantalla de aviso) sin conexión.
// La cola offline (IndexedDB + Background Sync, heredada de la Fase 7 de
// Edumia) se conecta en la Fase 3, junto con los formularios de captura.

const CACHE_NAME = "arca-shell-v2";
const OFFLINE_URL = "{% url 'core:sin_conexion' %}";
const ARCHIVOS_SHELL = [
  "{% static 'vendor/bootstrap/bootstrap.min.css' %}",
  "{% static 'vendor/bootstrap/bootstrap.bundle.min.js' %}",
  "{% static 'vendor/bootstrap-icons/bootstrap-icons.min.css' %}",
  "{% static 'vendor/htmx/htmx.min.js' %}",
  "{% static 'css/arca.css' %}",
  "{% static 'img/isotipo-claro.png' %}",
  "{% static 'img/logo.png' %}",
  "{% static 'img/favicon-32.png' %}",
  OFFLINE_URL,
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ARCHIVOS_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((nombres) =>
        Promise.all(nombres.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  // Páginas (navegación): red primero; si no hay conexión, muestra el
  // aviso de "sin conexión" en vez de dejar el error del navegador.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  // Estáticos del shell: caché primero y red como respaldo.
  if (request.url.includes("/static/")) {
    event.respondWith(
      caches.match(request).then((cacheado) => cacheado || fetch(request))
    );
  }
});
