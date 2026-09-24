"""Template context processors for the events app."""

from django.conf import settings


def feature_flags(_request):
    """Expose user-facing feature flags to all templates."""
    return {
        "map_view_enabled": getattr(settings, "MAP_VIEW_ENABLED", False),
    }


def site_origin(_request):
    """Expose the production origin (e.g. ``https://pleskal.dk``) to templates.

    Canonical links and ``og:url`` use it instead of the request host, so copies
    of a page served from another host (the Railway domain, www., http://) all
    point search engines at the one address to index.
    """
    return {"site_origin": f"https://{settings.SITE_DOMAIN}"}
