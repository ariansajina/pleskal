{% load static %}
/*
 * pleskal Service Worker
 *
 * Caching strategy:
 *
 * PRECACHE (install-time)
 *   Shell assets (CSS, HTMX, logo) + the offline fallback page.
 *   Versioned by DEPLOY_SHA so a new deploy busts the cache on next visit.
 *
 * RUNTIME — stale-while-revalidate
 *   Navigation to / and /events/<slug>/ pages the user has already visited,
 *   plus event images. The page is served from cache immediately while a
 *   fresh copy is fetched in the background.
 *
 * NETWORK-ONLY
 *   All mutating requests (POST/PUT/PATCH/DELETE) and all authenticated/
 *   sensitive paths (/accounts/*, /claim/*, /admin/*). These must never be
 *   served stale to avoid CSRF or session cross-contamination.
 *
 * OFFLINE FALLBACK
 *   If a navigation request fails (network down, nothing cached), the
 *   precached /offline/ page is shown instead.
 */

const CACHE_VERSION = "pleskal-{{ DEPLOY_SHA }}";
const SHELL_CACHE = CACHE_VERSION + "-shell";
const RUNTIME_CACHE = CACHE_VERSION + "-runtime";

const PRECACHE_URLS = [
  "/",
  "/offline/",
  "{% static 'css/output.css' %}",
  "{% static 'js/htmx.min.js' %}",
  "{% static 'images/logo.png' %}",
];

const NETWORK_ONLY_PATHS = ["/accounts/", "/claim/", "/admin/", "/markdownx/"];

// ── Install: precache shell assets ────────────────────────────────────────────

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: delete old caches ───────────────────────────────────────────────

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) => key !== SHELL_CACHE && key !== RUNTIME_CACHE
            )
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch: routing logic ───────────────────────────────────────────────────────

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests.
  if (url.origin !== self.location.origin) return;

  // Network-only: mutations and sensitive paths.
  if (request.method !== "GET") return;
  if (NETWORK_ONLY_PATHS.some((p) => url.pathname.startsWith(p))) return;

  // Navigation requests: stale-while-revalidate with offline fallback.
  if (request.mode === "navigate") {
    event.respondWith(navigationHandler(request));
    return;
  }

  // Static assets already in the shell cache: cache-first.
  if (
    url.pathname.startsWith("/static/") ||
    url.pathname.startsWith("/media/")
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }
});

// ── Strategy helpers ──────────────────────────────────────────────────────────

async function navigationHandler(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);

  // Always try network in the background to keep the cache fresh.
  const networkFetch = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);

  if (cached) {
    // Return the cached page immediately; background fetch updates it.
    networkFetch; // fire-and-forget
    return cached;
  }

  // No cache — wait for network; fall back to offline page on failure.
  const response = await networkFetch;
  if (response) return response;

  const offlinePage =
    (await caches.match("/offline/")) ||
    new Response("<h1>You're offline</h1>", {
      headers: { "Content-Type": "text/html" },
    });
  return offlinePage;
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  const response = await fetch(request).catch(() => null);
  if (response && response.ok) {
    const cache = await caches.open(RUNTIME_CACHE);
    cache.put(request, response.clone());
  }
  return response || new Response("Not found", { status: 404 });
}
