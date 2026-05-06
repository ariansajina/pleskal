import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def test_settings(settings):
    """Apply test-safe settings for every test."""
    settings.SECURE_SSL_REDIRECT = False
    # Provide a dummy pepper so tests work regardless of environment config.
    settings.PASSWORD_PEPPER = "ab" * 32
    # Never hit Nominatim from the test suite. Tests that exercise the
    # geocoding path should patch events.geocoding.geocode directly.
    settings.GEOCODING_ENABLED = False
    # Map discovery view is off in production by default; tests assume on.
    settings.MAP_VIEW_ENABLED = True
    # Use simple static storage so tests don't require a collected manifest.
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    """Clear rate limit cache before each test to prevent cross-test pollution."""
    cache.clear()
    yield
    cache.clear()
