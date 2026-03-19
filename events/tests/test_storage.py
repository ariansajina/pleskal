"""Feature 16: Storage backend configuration tests."""

import pytest

from config import settings as app_settings


class TestStorageSettingsModule:
    def test_default_storage_key_always_defined(self):
        """STORAGES must always include 'default' so media uploads work locally.

        The conftest autouse fixture overrides django.conf.settings.STORAGES for
        tests, which masks a missing 'default' key in the actual settings module.
        This test reads config.settings directly to catch that misconfiguration.
        """
        assert "default" in app_settings.STORAGES, (
            "STORAGES is missing the 'default' key — file uploads raise "
            "InvalidStorageError at runtime"
        )

    def test_default_storage_backend_is_filesystem_without_r2(self):
        """Without AWS_STORAGE_BUCKET_NAME, default storage must be FileSystemStorage."""
        assert (
            app_settings.STORAGES["default"]["BACKEND"]
            == "django.core.files.storage.FileSystemStorage"
        )


@pytest.mark.django_db
class TestStorageConfiguration:
    def test_default_storage_backend_in_tests(self, settings):
        """The conftest overrides STORAGES so tests use FileSystemStorage."""
        assert (
            settings.STORAGES["default"]["BACKEND"]
            == "django.core.files.storage.FileSystemStorage"
        )

    def test_r2_storage_backend_string(self, settings):
        """When AWS bucket is set, STORAGES should point to S3Boto3Storage."""
        settings.STORAGES = {
            "default": {
                "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }
        settings.AWS_STORAGE_BUCKET_NAME = "my-r2-bucket"
        settings.AWS_S3_FILE_OVERWRITE = False
        settings.AWS_QUERYSTRING_AUTH = False

        assert (
            settings.STORAGES["default"]["BACKEND"]
            == "storages.backends.s3boto3.S3Boto3Storage"
        )

    def test_r2_settings_values(self, settings):
        """R2-specific settings are correctly configured."""
        settings.AWS_S3_FILE_OVERWRITE = False
        settings.AWS_QUERYSTRING_AUTH = False
        settings.AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=31536000"}

        assert settings.AWS_S3_FILE_OVERWRITE is False
        assert settings.AWS_QUERYSTRING_AUTH is False
        assert settings.AWS_S3_OBJECT_PARAMETERS["CacheControl"] == "max-age=31536000"

    def test_staticfiles_backend_in_tests(self, settings):
        """Static files use simple storage in tests (no manifest required)."""
        assert (
            settings.STORAGES["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
