"""Tests for the import_dansehallerne management command."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from events.management.commands.import_dansehallerne import (
    _download_image,
    _parse_dt,
)
from events.models import Event

SAMPLE_EVENT = {
    "source_url": "https://dansehallerne.dk/event/1",
    "start_datetime": "2030-06-01T18:00:00+02:00",
    "end_datetime": "2030-06-01T20:00:00+02:00",
    "title": "Test Dance Event",
    "description": "A test event",
    "venue_name": "Test Venue",
    "venue_address": "Test Street 1",
    "category": "workshop",
    "is_free": True,
    "is_wheelchair_accessible": True,
    "price_note": "",
    "image_url": "",
}


def _write_json(data, path: Path) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


def test_parse_dt():
    dt = _parse_dt("2030-06-01T18:00:00+02:00")
    assert dt.year == 2030
    assert dt.month == 6


def test_download_image_empty_url():
    assert _download_image("") is None


def test_download_image_non_https_url():
    assert _download_image("http://example.com/img.jpg") is None


def test_download_image_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"imagedata"
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = _download_image("https://example.com/photo.jpg")
    assert result == ("photo.jpg", b"imagedata")


def test_download_image_network_error():
    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert _download_image("https://example.com/img.jpg") is None


# ---------------------------------------------------------------------------
# Command: error cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportDansehallerneErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CommandError, match="File not found"):
            call_command("import_dansehallerne", str(tmp_path / "missing.json"))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json", encoding="utf-8")
        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command("import_dansehallerne", str(f))

    def test_non_list_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"key": "val"}', encoding="utf-8")
        with pytest.raises(CommandError, match="top-level list"):
            call_command("import_dansehallerne", str(f))


# ---------------------------------------------------------------------------
# Command: create / update / delete / skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportDansehallerneCRUD:
    def test_creates_new_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 1
        event = Event.objects.get(external_source="dansehallerne")
        assert event.title == "Test Dance Event"
        assert event.venue_name == "Test Venue"

    def test_updates_changed_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))

        updated = {**SAMPLE_EVENT, "title": "Updated Dance Event"}
        _write_json([updated], f)
        call_command("import_dansehallerne", str(f))

        assert Event.objects.filter(external_source="dansehallerne").count() == 1
        assert (
            Event.objects.get(external_source="dansehallerne").title
            == "Updated Dance Event"
        )

    def test_unchanged_event_is_skipped(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        # Second import with identical data: nothing updated
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 1

    def test_deletes_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 1

        _write_json([], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 0

    def test_no_delete_preserves_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))

        _write_json([], f)
        call_command("import_dansehallerne", str(f), no_delete=True)
        assert Event.objects.filter(external_source="dansehallerne").count() == 1

    def test_skips_record_with_bad_datetime(self, tmp_path):
        f = tmp_path / "events.json"
        bad = {**SAMPLE_EVENT, "start_datetime": "not-a-date"}
        _write_json([bad], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 0

    def test_category_mapping(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**SAMPLE_EVENT, "category": "performance"}], f)
        call_command("import_dansehallerne", str(f))
        event = Event.objects.get(external_source="dansehallerne")
        assert event.category == "performance"

    def test_unknown_category_defaults_to_other(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**SAMPLE_EVENT, "category": "unknown_type"}], f)
        call_command("import_dansehallerne", str(f))
        event = Event.objects.get(external_source="dansehallerne")
        assert event.category == "other"


# ---------------------------------------------------------------------------
# Command: dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportDansehallernesDryRun:
    def test_dry_run_does_not_create(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f), dry_run=True)
        assert Event.objects.filter(external_source="dansehallerne").count() == 0

    def test_dry_run_does_not_update(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))

        updated = {**SAMPLE_EVENT, "title": "Dry Run Title"}
        _write_json([updated], f)
        call_command("import_dansehallerne", str(f), dry_run=True)
        assert (
            Event.objects.get(external_source="dansehallerne").title
            == "Test Dance Event"
        )

    def test_dry_run_does_not_delete(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))

        _write_json([], f)
        call_command("import_dansehallerne", str(f), dry_run=True)
        assert Event.objects.filter(external_source="dansehallerne").count() == 1


# ---------------------------------------------------------------------------
# Command: image handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportDansehallerneImages:
    def test_skip_images_creates_event_without_image(self, tmp_path):
        event_rec = {**SAMPLE_EVENT, "image_url": "https://example.com/img.jpg"}
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        call_command("import_dansehallerne", str(f), skip_images=True)
        event = Event.objects.get(external_source="dansehallerne")
        assert not event.image.name

    def test_image_download_failure_is_handled(self, tmp_path):
        event_rec = {**SAMPLE_EVENT, "image_url": "https://example.com/img.jpg"}
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        with patch(
            "events.management.commands.import_dansehallerne._download_image",
            return_value=None,
        ):
            call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 1
