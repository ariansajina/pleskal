"""Progressive Web App views: manifest, service worker, offline fallback.

The manifest and service worker are served as Django views (not flat static
files) so the cache-bust token (``APP_VERSION`` or a stable fallback) is
templated into them. A new deploy changes the token, the cache name in the
service worker changes, and clients pick up fresh shell assets on the next
visit.

Caching strategy implemented in ``service-worker.js``:

* **Precache** (cache-first): the site shell — ``/``, the offline fallback
  page, compiled Tailwind CSS, vendored HTMX and small UI scripts, the logo
  and PWA icons.
* **Stale-while-revalidate**: GET navigations (e.g. event detail pages) and
  same-origin images. The cached copy is served immediately and revalidated
  in the background.
* **Network-only**: anything authenticated or state-changing — POST/PUT/
  DELETE, ``/accounts/*``, ``/claim/*``, ``/admin/*``, ``/markdownx/*``,
  ``/health/`` — never cached, so we cannot serve stale HTML to a logged-in
  user or cross-leak cached state between users.
* **Offline fallback**: if a navigation request fails entirely (no network,
  no cache), the precached ``/offline/`` page is returned.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


def _cache_token() -> str:
    """Return a token that changes on each deploy.

    Falls back to ``"dev"`` so local development still produces a valid SW.
    """

    return getattr(settings, "APP_VERSION", "") or "dev"


@require_GET
def manifest_view(request: HttpRequest) -> HttpResponse:
    body = render_to_string(
        "pwa/manifest.webmanifest",
        {"cache_token": _cache_token()},
        request=request,
    )
    return HttpResponse(body, content_type="application/manifest+json")


@require_GET
@cache_control(no_cache=True, max_age=0)
def service_worker_view(request: HttpRequest) -> HttpResponse:
    """Serve the service worker.

    ``Cache-Control: no-cache`` ensures the browser always revalidates the
    SW script itself, so a new deploy is picked up promptly even though the
    SW byte-compares the response to decide whether to update.
    """

    body = render_to_string(
        "pwa/service-worker.js",
        {"cache_token": _cache_token()},
        request=request,
    )
    response = HttpResponse(body, content_type="application/javascript")
    # Allow the SW to control the whole origin even if served from a deeper path.
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse(render_to_string("pwa/offline.html", request=request))
