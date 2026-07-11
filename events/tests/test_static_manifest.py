"""Production-parity static storage check.

Tests run under a simple FileSystemStorage/StaticFilesStorage backend
(conftest.py's autouse `test_settings` fixture), which is why the
DEFAULT_EVENT_IMAGE case mismatch (images/logo.PNG vs the actual
images/logo.png on disk) went undetected: WhiteNoise's manifest storage in
production does a case-sensitive, strict lookup that a plain StaticFilesStorage
never performs. This test opts out of that fixture override and runs
`collectstatic` with the real production storage backend, then resolves every
statically-referenced default image path through it.
"""

import pytest
from django.core.management import call_command
from django.templatetags.static import static

from events.models import DEFAULT_EVENT_IMAGE, DEFAULT_PUBLISHER_IMAGES


@pytest.mark.django_db
def test_default_images_resolve_under_manifest_storage(settings, tmp_path):
    settings.STATIC_ROOT = tmp_path
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    call_command("collectstatic", interactive=False, verbosity=0)

    # static() raises ValueError under the manifest's strict, case-sensitive
    # lookup if the path wasn't actually collected — this is what would have
    # caught the logo.PNG/logo.png mismatch.
    static(DEFAULT_EVENT_IMAGE)
    for path in DEFAULT_PUBLISHER_IMAGES.values():
        static(path)
