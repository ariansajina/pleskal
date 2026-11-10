"""Project-wide middleware."""

from django.conf import settings
from django.utils.cache import (
    add_never_cache_headers,
    patch_cache_control,
    patch_vary_headers,
)


class NoStoreForAuthenticatedMiddleware:
    """Mark responses to logged-in users as uncacheable (``no-store``).

    Their pages carry per-user state (owner controls, draft events, edit forms
    with a CSRF token). ``no-store`` keeps them out of the browser cache and out
    of the service worker's offline cache (``templates/pwa/service-worker.js``
    skips ``no-store`` responses), so nothing of theirs outlives the session on
    a shared device. Responses that already set Cache-Control are left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not response.has_header("Cache-Control")
        ):
            add_never_cache_headers(response)
        return response


# Paths whose pages are per-visitor even when anonymous (forms with a CSRF
# token, the claim flow's session state) or private; never marked cacheable.
_EDGE_CACHE_EXCLUDED_PREFIXES = (
    "/accounts/",
    "/admin/",
    "/claim/",
    "/events/submit/",
    "/markdownx/",
    "/stats/",
)


class EdgeCacheAnonymousMiddleware:
    """Let a CDN cache anonymous HTML for ``EDGE_CACHE_SECONDS`` (0 = off).

    Adds ``Cache-Control: public, max-age=0, s-maxage=N`` (browsers revalidate,
    shared caches may keep it N seconds) to a GET/HEAD 200 HTML response when
    the request carries no session cookie, isn't an HTMX request, and the
    response sets no cookie and no Cache-Control of its own. Pages that
    render a CSRF token or flash messages set a cookie and so stay uncached;
    logged-in responses are already ``no-store``.

    It sits above the session, CSRF and messages middleware so it sees the
    cookies they set. Cloudflare only caches HTML through a cache rule, which
    must bypass requests with a session cookie or an ``HX-Request`` header
    (see deployment-notes.md "Edge caching").
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        seconds = getattr(settings, "EDGE_CACHE_SECONDS", 0)
        if seconds > 0 and self._cacheable(request, response):
            patch_cache_control(response, public=True, max_age=0, s_maxage=seconds)
            patch_vary_headers(response, ("HX-Request",))
        return response

    @staticmethod
    def _cacheable(request, response) -> bool:
        return (
            request.method in ("GET", "HEAD")
            and response.status_code == 200
            and response.get("Content-Type", "").startswith("text/html")
            and not response.has_header("Cache-Control")
            and not response.cookies
            and settings.SESSION_COOKIE_NAME not in request.COOKIES
            and request.headers.get("HX-Request") != "true"
            and not request.path.startswith(_EDGE_CACHE_EXCLUDED_PREFIXES)
        )
