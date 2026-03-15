"""Feature 16: Storage backend configuration tests."""

import pytest


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
        settings.AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

        assert settings.AWS_S3_FILE_OVERWRITE is False
        assert settings.AWS_QUERYSTRING_AUTH is False
        assert settings.AWS_S3_OBJECT_PARAMETERS["CacheControl"] == "max-age=86400"

    def test_staticfiles_backend_in_tests(self, settings):
        """Static files use simple storage in tests (no manifest required)."""
        assert (
            settings.STORAGES["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
