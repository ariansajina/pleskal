"""Regression tests for the security review fixes on the events side."""

import io
import json

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory
from PIL import Image

from events.feeds import EventRSSFeed
from events.images import make_thumbnail, validate_and_process
from events.models import Event
from events.tests.factories import EventFactory


def _image_bytes(fmt: str) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color=(10, 20, 30)).save(buf, format=fmt)
    buf.seek(0)
    return buf


class TestImageFormatAllowlist:
    @pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF", "ICO"])
    def test_unsupported_format_upload_rejected(self, fmt):
        with pytest.raises(ValidationError):
            validate_and_process(_image_bytes(fmt))

    @pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
    def test_supported_format_upload_accepted(self, fmt):
        assert validate_and_process(_image_bytes(fmt)).name == "photo.webp"

    def test_unsupported_format_thumbnail_raises(self):
        with pytest.raises(Exception):  # noqa: B017 - PIL's UnidentifiedImageError
            make_thumbnail(_image_bytes("GIF"))


@pytest.mark.django_db
class TestRSSFeedFiltersArePerRequest:
    def test_filters_not_stored_on_shared_instance(self):
        feed = EventRSSFeed()
        request = RequestFactory().get("/feed/events.rss?category=workshop")
        obj = feed.get_object(request)
        assert obj == {"categories": ["workshop"], "publisher_slugs": []}
        assert not hasattr(feed, "_request")

    def test_shared_instance_serves_each_request_its_own_filter(self):
        EventFactory.create(title="Workshop One", category="workshop")
        EventFactory.create(title="Show One", category="performance")
        feed = EventRSSFeed()
        rf = RequestFactory()
        workshop = feed(rf.get("/feed/events.rss?category=workshop")).content
        unfiltered = feed(rf.get("/feed/events.rss")).content
        assert b"Workshop One" in workshop
        assert b"Show One" not in workshop
        assert b"Workshop One" in unfiltered
        assert b"Show One" in unfiltered


@pytest.mark.django_db
class TestReservedSlug:
    def test_event_titled_submit_gets_suffixed_slug(self, client):
        event = EventFactory.create(title="Submit")
        assert event.slug != "submit"
        assert str(event.slug).startswith("submit-")
        assert client.get(event.get_absolute_url()).status_code == 200


@pytest.mark.django_db
class TestImportSourceUrlScheme:
    @pytest.mark.parametrize(
        "url", ["javascript:alert(1)", "data:text/html,hi", "ftp://x.dk/e"]
    )
    def test_non_http_source_url_is_skipped(self, tmp_path, url):
        record = {
            "source_url": url,
            "start_datetime": "2030-06-01T18:00:00+02:00",
            "end_datetime": "2030-06-01T20:00:00+02:00",
            "title": "Scheme Test Event",
            "description": "A test event",
            "venue_name": "Test Venue",
            "venue_address": "",
            "category": "performance",
            "is_free": True,
            "is_wheelchair_accessible": False,
            "price_note": "",
            "image_url": "",
        }
        f = tmp_path / "events.json"
        f.write_text(json.dumps([record]), encoding="utf-8")
        call_command("import_events", "dansehallerne", str(f))
        assert not Event.objects.filter(title="Scheme Test Event").exists()
