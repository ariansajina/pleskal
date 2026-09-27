"""List-card thumbnails: generation, syncing on save, backfill and cleanup."""

import datetime
import io
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.templatetags.static import static
from django.urls import reverse
from PIL import Image

from accounts.tests.factories import UserFactory
from events.images import THUMBNAIL_MIN_SIDE, make_thumbnail
from events.models import (
    DEFAULT_EVENT_IMAGE,
    DEFAULT_PUBLISHER_IMAGES,
    Event,
    default_thumbnail_path,
)
from events.tests.factories import EventFactory


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _image_bytes(size=(1200, 675), mode="RGB", fmt="WEBP", color=(200, 30, 30)):
    buffer = io.BytesIO()
    if mode == "RGBA":
        color = (*color, 0)
    Image.new(mode, size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _stored_image(name="events/photo.webp", **kwargs):
    """Save an image to storage and return its storage name."""
    return default_storage.save(name, ContentFile(_image_bytes(**kwargs)))


def _build(**kwargs):
    """An unsaved event (with a saved submitter) for tests that set its image."""
    kwargs.setdefault("submitted_by", UserFactory.create())
    return EventFactory.build(**kwargs)


def _event_with_image(**kwargs):
    event = _build(**kwargs)
    event.image.name = _stored_image()
    event.save()
    return event


def _size(storage_name):
    with default_storage.open(storage_name, "rb") as f, Image.open(f) as img:
        return img.size


class TestMakeThumbnail:
    def test_scales_shorter_side_of_landscape_image(self):
        data = make_thumbnail(io.BytesIO(_image_bytes((1200, 675))))
        assert Image.open(io.BytesIO(data)).size == (640, THUMBNAIL_MIN_SIDE)

    def test_scales_shorter_side_of_portrait_image(self):
        data = make_thumbnail(io.BytesIO(_image_bytes((900, 1200))))
        assert Image.open(io.BytesIO(data)).size == (THUMBNAIL_MIN_SIDE, 480)

    def test_small_image_keeps_its_size(self):
        data = make_thumbnail(io.BytesIO(_image_bytes((300, 200))))
        assert Image.open(io.BytesIO(data)).size == (300, 200)

    def test_output_is_webp(self):
        data = make_thumbnail(io.BytesIO(_image_bytes(fmt="PNG")))
        assert Image.open(io.BytesIO(data)).format == "WEBP"

    def test_transparency_is_flattened_onto_white(self):
        data = make_thumbnail(io.BytesIO(_image_bytes(mode="RGBA", fmt="PNG")))
        img = Image.open(io.BytesIO(data))
        assert img.mode == "RGB"
        pixel = img.getpixel((10, 10))
        assert isinstance(pixel, tuple)
        assert min(pixel) > 245

    def test_jpeg_is_decoded_downscaled(self):
        data = make_thumbnail(io.BytesIO(_image_bytes((4000, 3000), fmt="JPEG")))
        assert Image.open(io.BytesIO(data)).size == (480, THUMBNAIL_MIN_SIDE)

    def test_oversized_image_is_rejected(self, settings):
        settings.MAX_IMAGE_PIXELS = 1000
        with pytest.raises(ValueError):
            make_thumbnail(io.BytesIO(_image_bytes((100, 100))))

    def test_invalid_data_raises(self):
        with pytest.raises(OSError):
            make_thumbnail(io.BytesIO(b"not an image"))


@pytest.mark.django_db
class TestThumbnailSyncOnSave:
    def test_new_event_with_image_gets_a_thumbnail(self):
        event = _event_with_image()
        assert event.thumbnail.name.startswith("events/thumbs/")
        assert _size(event.thumbnail.name) == (640, THUMBNAIL_MIN_SIDE)
        event.refresh_from_db()
        assert event.thumbnail.name.startswith("events/thumbs/")

    def test_event_without_image_has_no_thumbnail(self):
        event = EventFactory.create()
        assert not event.thumbnail

    def test_unchanged_image_is_not_regenerated(self):
        event = _event_with_image()
        event = Event.objects.get(pk=event.pk)
        with patch("events.images.store_thumbnail") as store:
            event.title = "Renamed"
            event.save()
        store.assert_not_called()

    def test_changed_image_gets_a_new_thumbnail(self):
        event = _event_with_image()
        event = Event.objects.get(pk=event.pk)
        old = event.thumbnail.name
        event.image.name = _stored_image(
            "events/other.webp", size=(900, 1200), color=(10, 200, 10)
        )
        event.save()
        assert event.thumbnail.name != old
        assert _size(event.thumbnail.name) == (THUMBNAIL_MIN_SIDE, 480)

    def test_removed_image_clears_thumbnail(self):
        event = _event_with_image()
        event = Event.objects.get(pk=event.pk)
        event.image = None
        event.save()
        event.refresh_from_db()
        assert not event.thumbnail

    def test_update_fields_save_without_image_leaves_thumbnail_alone(self):
        event = _event_with_image()
        event = Event.objects.get(pk=event.pk)
        with patch("events.images.store_thumbnail") as store:
            event.is_draft = True
            event.save(update_fields=["is_draft", "updated_at"])
        store.assert_not_called()

    def test_update_fields_with_image_also_saves_thumbnail(self):
        event = EventFactory.create()
        event = Event.objects.get(pk=event.pk)
        event.image.name = _stored_image()
        event.save(update_fields=["image"])
        event.refresh_from_db()
        assert event.thumbnail.name.startswith("events/thumbs/")

    def test_events_sharing_an_image_share_one_thumbnail(self):
        image_name = _stored_image()
        first = _build()
        first.image.name = image_name
        first.save()
        second = _build()
        second.image.name = image_name
        with patch("events.images.store_thumbnail") as store:
            second.save()
        store.assert_not_called()
        assert second.thumbnail.name == first.thumbnail.name

    def test_identical_pictures_are_stored_once(self):
        a = _event_with_image()
        b = _event_with_image()
        assert a.image.name != b.image.name
        assert a.thumbnail.name == b.thumbnail.name

    def test_generation_failure_saves_event_without_thumbnail(self):
        event = _build()
        event.image.name = "events/missing.webp"  # not in storage
        event.save()
        event.refresh_from_db()
        assert not event.thumbnail

    def test_missing_thumbnail_is_retried_on_next_save(self):
        event = _build()
        event.image.name = _stored_image()
        with patch("events.images.store_thumbnail", side_effect=OSError("down")):
            event.save()
        assert not event.thumbnail
        event = Event.objects.get(pk=event.pk)
        event.save()
        assert event.thumbnail.name.startswith("events/thumbs/")

    def test_uncommitted_upload_is_stored_then_thumbnailed(self):
        """An upload assigned straight to the field (as the admin does)."""
        event = _build()
        event.image = SimpleUploadedFile("upload.png", _image_bytes(fmt="PNG"))
        event.save()
        assert default_storage.exists(event.image.name)
        assert event.thumbnail.name.startswith("events/thumbs/")


@pytest.mark.django_db
class TestDisplayThumbnailUrl:
    def test_uses_thumbnail(self):
        event = _event_with_image()
        assert event.display_thumbnail_url == event.thumbnail.url

    def test_falls_back_to_full_image_without_thumbnail(self):
        event = _event_with_image()
        Event.objects.filter(pk=event.pk).update(thumbnail=None)
        event.refresh_from_db()
        assert event.display_thumbnail_url == event.image.url

    def test_user_event_without_image_uses_logo_thumbnail(self):
        event = EventFactory.create()
        expected = static(default_thumbnail_path(DEFAULT_EVENT_IMAGE))
        assert event.display_thumbnail_url == expected
        assert expected.endswith("images/thumbs/logo.png")

    def test_scraped_event_without_image_uses_publisher_thumbnail(self):
        event = EventFactory.create(external_source="hautscene")
        assert event.display_thumbnail_url == static(
            "images/defaults/thumbs/hautscene.webp"
        )

    def test_default_thumbnails_exist(self):
        from django.contrib.staticfiles import finders

        for path in [DEFAULT_EVENT_IMAGE, *DEFAULT_PUBLISHER_IMAGES.values()]:
            assert finders.find(default_thumbnail_path(path)), path

    def test_list_card_renders_thumbnail(self, client):
        event = _event_with_image()
        resp = client.get(reverse("event_list"))
        assert event.thumbnail.url.encode() in resp.content
        assert event.image.url.encode() not in resp.content


@pytest.mark.django_db
class TestThumbnailDeletion:
    def test_thumbnail_deleted_with_event(self):
        event = _event_with_image()
        name = event.thumbnail.name
        event.delete()
        assert not default_storage.exists(name)

    def test_shared_thumbnail_kept_while_referenced(self):
        a = _event_with_image()
        b = _event_with_image()
        a.delete()
        assert default_storage.exists(b.thumbnail.name)


@pytest.mark.django_db
class TestBackfillThumbnails:
    def _without_thumbnail(self, image_name=None):
        event = _build()
        event.image.name = image_name or _stored_image()
        with patch("events.images.store_thumbnail", side_effect=OSError("x")):
            event.save()
        assert not event.thumbnail
        return event

    def test_generates_missing_thumbnails(self):
        event = self._without_thumbnail()
        call_command("backfill_thumbnails")
        event.refresh_from_db()
        assert event.thumbnail.name.startswith("events/thumbs/")

    def test_generates_once_per_shared_image(self):
        image_name = _stored_image()
        a = self._without_thumbnail(image_name)
        b = self._without_thumbnail(image_name)
        with patch(
            "events.images.store_thumbnail", return_value="events/thumbs/x.webp"
        ) as store:
            call_command("backfill_thumbnails")
        assert store.call_count == 1
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.thumbnail.name == b.thumbnail.name == "events/thumbs/x.webp"

    def test_does_not_bump_updated_at(self):
        event = self._without_thumbnail()
        long_ago = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        Event.objects.filter(pk=event.pk).update(updated_at=long_ago)
        call_command("backfill_thumbnails")
        event.refresh_from_db()
        assert event.updated_at == long_ago
        assert event.thumbnail

    def test_dry_run_writes_nothing(self):
        event = self._without_thumbnail()
        out = io.StringIO()
        call_command("backfill_thumbnails", dry_run=True, stdout=out)
        event.refresh_from_db()
        assert not event.thumbnail
        assert "Would generate 1" in out.getvalue()

    def test_limit_caps_distinct_images(self):
        self._without_thumbnail()
        self._without_thumbnail(_stored_image("events/b.webp", color=(1, 2, 3)))
        call_command("backfill_thumbnails", limit=1)
        assert Event.objects.filter(thumbnail__startswith="events/thumbs/").count() == 1

    def test_failure_is_reported_and_left_for_next_run(self):
        event = _build()
        event.image.name = "events/missing.webp"
        event.save()
        err = io.StringIO()
        out = io.StringIO()
        call_command("backfill_thumbnails", stdout=out, stderr=err)
        assert "[failed] events/missing.webp" in err.getvalue()
        assert "1 failed" in out.getvalue()
        event.refresh_from_db()
        assert not event.thumbnail

    def test_events_without_images_are_ignored(self):
        EventFactory.create()
        out = io.StringIO()
        call_command("backfill_thumbnails", stdout=out)
        assert "Generated 0 thumbnail(s); 0 failed." in out.getvalue()
