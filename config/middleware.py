"""Project-wide middleware."""

from django.utils.cache import add_never_cache_headers


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
