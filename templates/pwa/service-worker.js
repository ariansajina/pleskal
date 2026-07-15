{% load static %}/* pleskal service worker — cache token: {{ cache_token }} */
const CACHE_VERSION = "{{ cache_token }}";
const PRECACHE = `pleskal-precache-${CACHE_VERSION}`;
const RUNTIME = `pleskal-runtime-${CACHE_VERSION}`;
const OFFLINE_URL = "/offline/";

/* Site shell precached on install. Keep this list small and stable.
 * HTML pages are intentionally excluded — they carry auth state and must
 * always be fetched from the network to avoid serving a stale logged-in/out
 * view after the user signs in or out. */
const PRECACHE_URLS = [
  OFFLINE_URL,
  "{% static 'css/output.css' %}",
  "{% static 'css/fonts.css' %}",
  "{% static 'js/htmx.min.js' %}",
  "{% static 'js/nav.js' %}",
  "{% static 'js/quick-date-filters.js' %}",
  "{% static 'js/filter-panel.js' %}",
  "{% static 'js/calendar-dropdown.js' %}",
  "{% static 'js/share.js' %}",
  "{% static 'js/show-map.js' %}",
  "{% static 'js/subscribe-filters.js' %}",
  "{% static 'js/pwa.js' %}",
  "{% static 'images/logo.png' %}",
  "{% static 'images/favicon-32x32.png' %}",
  "{% static 'images/apple-touch-icon.png' %}",
  "{% static 'icons/icon-192.png' %}",
  "{% static 'icons/icon-512.png' %}",
  "{% static 'icons/icon-maskable-512.png' %}",
  "/manifest.webmanifest",
];

/* Path prefixes that must always go to the network. Authenticated, CSRF-
 * protected, or admin surfaces — never cached so we cannot leak per-user
 * state or serve stale forms. */
const NETWORK_ONLY_PREFIXES = [
  "/accounts/",
  "/claim/",
  "/admin/",
  "/markdownx/",
  "/health/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(PRECACHE).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  const allowed = new Set([PRECACHE, RUNTIME]);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !allowed.has(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isNetworkOnly(url) {
  if (url.origin !== self.location.origin) return true;
  return NETWORK_ONLY_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
}

function staleWhileRevalidate(request) {
  return caches.open(RUNTIME).then((cache) =>
    /* Search all caches (including PRECACHE) so precached assets are served
     * immediately offline, before they've been fetched into RUNTIME. */
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok && response.type === "basic") {
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; /* Let POST/PUT/DELETE pass through untouched. */

  const url = new URL(request.url);
  if (isNetworkOnly(url)) return;

  /* Navigation requests: network-first so auth state is always current.
   * Cache the response for offline fallback; serve stale only when offline. */
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok && response.type === "basic") {
            caches.open(RUNTIME).then((cache) => cache.put(request, response.clone()));
          }
          return response;
        })
        .catch(() =>
          caches.match(request).then((cached) => cached || caches.match(OFFLINE_URL)),
        ),
    );
    return;
  }

  /* Same-origin static assets and images: stale-while-revalidate.
   * Skip HTMX requests — the server returns partials for those, and caching
   * them at the same URL as full-page navigations would corrupt both. */
  if (url.origin === self.location.origin) {
    if (request.headers.get("HX-Request")) return;
    event.respondWith(staleWhileRevalidate(request));
  }
});
