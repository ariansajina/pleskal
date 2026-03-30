"""Tests for events/signals.py — image file cleanup on Event delete."""

import io
from typing import cast

import pytest
from django.core.files.base import ContentFile
from django.db.models.fields.files import ImageFieldFile
from PIL import Image

from events.tests.factories import EventFactory


def _make_webp_content(color=(100, 150, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=color).save(buf, format="WEBP")
    return buf.getvalue()


@pytest.mark.django_db
class TestDeleteEventImageSignal:
    def test_deleting_event_removes_image_from_storage(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        event = EventFactory.create()
        image_field = cast(ImageFieldFile, event.image)
        image_field.save("photo.webp", ContentFile(_make_webp_content()), save=True)
        image_name = image_field.name
        assert image_field.storage.exists(image_name)

        event.delete()

        assert not image_field.storage.exists(image_name)

    def test_deleting_event_without_image_does_not_raise(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        event = EventFactory.create()
        assert not event.image  # no image set
        event.delete()  # must not raise

    def test_shared_image_not_deleted_when_one_event_removed(self, settings, tmp_path):
        """If two events reference the same image path, deleting one must not
        remove the file — the other event still needs it."""
        settings.MEDIA_ROOT = tmp_path
        event_a = EventFactory.create()
        image_a = cast(ImageFieldFile, event_a.image)
        image_a.save("photo.webp", ContentFile(_make_webp_content()), save=True)
        image_name = image_a.name

        # Point event_b at the same file without uploading a second copy
        event_b = EventFactory.create()
        cast(ImageFieldFile, event_b.image).name = image_name
        event_b.save(update_fields=["image"])

        assert image_a.storage.exists(image_name)

        event_a.delete()

        # File must still exist because event_b references it
        assert image_a.storage.exists(image_name)

    def test_shared_image_deleted_when_last_referencing_event_removed(
        self, settings, tmp_path
    ):
        """After the last event referencing a shared image is deleted, the
        file should be removed from storage."""
        settings.MEDIA_ROOT = tmp_path
        event_a = EventFactory.create()
        image_a = cast(ImageFieldFile, event_a.image)
        image_a.save("photo.webp", ContentFile(_make_webp_content()), save=True)
        image_name = image_a.name

        event_b = EventFactory.create()
        cast(ImageFieldFile, event_b.image).name = image_name
        event_b.save(update_fields=["image"])

        event_a.delete()
        # File still exists after first delete (event_b still references it)
        assert image_a.storage.exists(image_name)

        event_b.delete()
        # Now the last reference is gone — file must be deleted
        assert not image_a.storage.exists(image_name)
