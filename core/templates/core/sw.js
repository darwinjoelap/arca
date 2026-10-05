{% load static %}
// Service worker de Arca: instalabilidad, un "shell" mínimo en caché y el
// envío en segundo plano de la cola offline (Background Sync, donde exista).
// offline-sync-core.js se carga con importScripts porque este archivo corre
// en el hilo del service worker, no en el de la página.

importScripts("{% static 'js/offline-sync-core.js' %}");

const CACHE_NAME = "arca-shell-v5";
const OFFLINE_URL = "{% url 'core:sin_conexion' %}";
const ARCHIVOS_SHELL = [
  "{% static 'vendor/bootstrap/bootstrap.min.css' %}",
  "{% static 'vendor/bootstrap/bootstrap.bundle.min.js' %}",
  "{% static 'vendor/bootstrap-icons/bootstrap-icons.min.css' %}",
  "{% static 'vendor/htmx/htmx.min.js' %}",
  "{% static 'css/arca.css' %}",
  "{% static 'js/offline-sync-core.js' %}",
  "{% static 'js/offline-status.js' %}",
  "{% static 'js/offline-forms.js' %}",
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

// Background Sync: offline-forms.js registra el tag al guardar algo en la
// cola. El navegador dispara este evento solo (incluso con la app cerrada,
// en Android/Chrome) cuando detecta que volvió la señal. iPhone no lo tiene:
// ahí la cola se envía al volver a abrir la app (offline-status.js).
self.addEventListener("sync", (event) => {
  if (event.tag === self.ArcaOffline.TAG_SYNC) {
    event.waitUntil(self.ArcaOffline.sincronizarCola().then(avisarClientes));
  }
});

function avisarClientes() {
  return self.clients.matchAll().then((clientes) => {
    clientes.forEach((cliente) => cliente.postMessage({ tipo: "arca-offline-sync" }));
  });
}
