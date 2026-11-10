"""Project-wide middleware."""

from django.conf import settings
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


class AuthenticatedCSPMiddleware:
    """Give logged-in users' responses the stricter SECURE_CSP_AUTHENTICATED.

    Their pages don't load the Ko-fi widget, so the Ko-fi sources the public
    policy allows are dropped. Uses the per-response override that Django's
    ContentSecurityPolicyMiddleware reads (``response._csp_config``, as set by
    ``csp_override``); a view's own override is left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not hasattr(response, "_csp_config")
        ):
            response._csp_config = settings.SECURE_CSP_AUTHENTICATED
        return response
