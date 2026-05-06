"""Template context processors for the events app."""

from django.conf import settings


def feature_flags(_request):
    """Expose user-facing feature flags to all templates."""
    return {
        "map_view_enabled": getattr(settings, "MAP_VIEW_ENABLED", False),
    }
