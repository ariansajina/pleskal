import pytest


@pytest.fixture(autouse=True)
def test_settings(settings):
    """Apply test-safe settings for every test."""
    settings.SECURE_SSL_REDIRECT = False
    # Provide a dummy pepper so tests work regardless of environment config.
    settings.PASSWORD_PEPPER = "ab" * 32
    # Use simple static storage so tests don't require a collected manifest
    settings.STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
