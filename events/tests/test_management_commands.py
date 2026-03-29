"""Tests for the import_dansehallerne, import_hautscene, and import_sydhavnteater management commands."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from events.management.commands.base_import import _download_image, _parse_dt
from events.models import Event

UserModel = get_user_model()

SAMPLE_EVENT = {
    "source_url": "https://dansehallerne.dk/event/1",
    "start_datetime": "2030-06-01T18:00:00+02:00",
    "end_datetime": "2030-06-01T20:00:00+02:00",
    "title": "Test Dance Event",
    "description": "A test event",
    "venue_name": "Test Venue",
    "venue_address": "Test Street 1",
    "category": "performance",
    "is_free": True,
    "is_wheelchair_accessible": True,
    "price_note": "",
    "image_url": "",
}

SAMPLE_WORKSHOP_EVENT = {
    **SAMPLE_EVENT,
    "source_url": "https://dansehallerne.dk/workshop/1",
    "title": "Test Workshop Event",
    "category": "workshop",
}


def _write_json(data, path: Path) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Standalone helpers (shared across all import commands)
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
            "events.management.commands.base_import._download_image",
            return_value=None,
        ):
            call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 1


# ===========================================================================
# import_hautscene tests
# ===========================================================================

HAUTSCENE_SAMPLE_EVENT = {
    "source_url": "https://www.hautscene.dk/en/events/test-event",
    "start_datetime": "2030-06-01T15:00:00+02:00",
    "end_datetime": "2030-06-01T18:00:00+02:00",
    "title": "Test Haut Scene Event",
    "description": "A test hautscene event",
    "venue_name": "Haut Scene",
    "venue_address": "Test Street 1",
    "category": "other",
    "is_free": False,
    "is_wheelchair_accessible": False,
    "price_note": "",
    "image_url": "",
}


# ---------------------------------------------------------------------------
# Command: error cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportHautsceneErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CommandError, match="File not found"):
            call_command("import_hautscene", str(tmp_path / "missing.json"))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json", encoding="utf-8")
        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command("import_hautscene", str(f))

    def test_non_list_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"key": "val"}', encoding="utf-8")
        with pytest.raises(CommandError, match="top-level list"):
            call_command("import_hautscene", str(f))


# ---------------------------------------------------------------------------
# Command: create / update / delete / skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportHautsceneCRUD:
    def test_creates_new_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 1
        event = Event.objects.get(external_source="hautscene")
        assert event.title == "Test Haut Scene Event"
        assert event.venue_name == "Haut Scene"

    def test_updates_changed_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))

        updated = {**HAUTSCENE_SAMPLE_EVENT, "title": "Updated Haut Scene Event"}
        _write_json([updated], f)
        call_command("import_hautscene", str(f))

        assert Event.objects.filter(external_source="hautscene").count() == 1
        assert (
            Event.objects.get(external_source="hautscene").title
            == "Updated Haut Scene Event"
        )

    def test_unchanged_event_is_skipped(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))
        call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 1

    def test_deletes_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 1

        _write_json([], f)
        call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 0

    def test_no_delete_preserves_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))

        _write_json([], f)
        call_command("import_hautscene", str(f), no_delete=True)
        assert Event.objects.filter(external_source="hautscene").count() == 1

    def test_skips_record_with_bad_datetime(self, tmp_path):
        f = tmp_path / "events.json"
        bad = {**HAUTSCENE_SAMPLE_EVENT, "start_datetime": "not-a-date"}
        _write_json([bad], f)
        call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 0

    def test_category_mapping(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**HAUTSCENE_SAMPLE_EVENT, "category": "talk"}], f)
        call_command("import_hautscene", str(f))
        event = Event.objects.get(external_source="hautscene")
        assert event.category == "talk"

    def test_unknown_category_defaults_to_other(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**HAUTSCENE_SAMPLE_EVENT, "category": "unknown_type"}], f)
        call_command("import_hautscene", str(f))
        event = Event.objects.get(external_source="hautscene")
        assert event.category == "other"


# ---------------------------------------------------------------------------
# Command: dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportHautsceneDryRun:
    def test_dry_run_does_not_create(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f), dry_run=True)
        assert Event.objects.filter(external_source="hautscene").count() == 0

    def test_dry_run_does_not_update(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))

        updated = {**HAUTSCENE_SAMPLE_EVENT, "title": "Dry Run Title"}
        _write_json([updated], f)
        call_command("import_hautscene", str(f), dry_run=True)
        assert (
            Event.objects.get(external_source="hautscene").title
            == "Test Haut Scene Event"
        )

    def test_dry_run_does_not_delete(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([HAUTSCENE_SAMPLE_EVENT], f)
        call_command("import_hautscene", str(f))

        _write_json([], f)
        call_command("import_hautscene", str(f), dry_run=True)
        assert Event.objects.filter(external_source="hautscene").count() == 1


# ---------------------------------------------------------------------------
# Command: image handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportHautsceneImages:
    def test_skip_images_creates_event_without_image(self, tmp_path):
        event_rec = {
            **HAUTSCENE_SAMPLE_EVENT,
            "image_url": "https://example.com/img.jpg",
        }
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        call_command("import_hautscene", str(f), skip_images=True)
        event = Event.objects.get(external_source="hautscene")
        assert not event.image.name

    def test_image_download_failure_is_handled(self, tmp_path):
        event_rec = {
            **HAUTSCENE_SAMPLE_EVENT,
            "image_url": "https://example.com/img.jpg",
        }
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        with patch(
            "events.management.commands.base_import._download_image",
            return_value=None,
        ):
            call_command("import_hautscene", str(f))
        assert Event.objects.filter(external_source="hautscene").count() == 1


# ===========================================================================
# import_sydhavnteater tests
# ===========================================================================

SYDHAVN_SAMPLE_EVENT = {
    "source_url": "https://sydhavnteater.dk/event/test-event",
    "start_datetime": "2030-06-01T00:00:00+02:00",
    "end_datetime": None,
    "title": "Test Sydhavn Event",
    "description": "A test sydhavnteater event",
    "venue_name": "Kapelscenen",
    "venue_address": "",
    "category": "performance",
    "is_free": True,
    "is_wheelchair_accessible": False,
    "price_note": "",
    "image_url": "",
}


# ---------------------------------------------------------------------------
# Command: error cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportSydhavnteaterErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CommandError, match="File not found"):
            call_command("import_sydhavnteater", str(tmp_path / "missing.json"))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json", encoding="utf-8")
        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command("import_sydhavnteater", str(f))

    def test_non_list_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"key": "val"}', encoding="utf-8")
        with pytest.raises(CommandError, match="top-level list"):
            call_command("import_sydhavnteater", str(f))


# ---------------------------------------------------------------------------
# Command: create / update / delete / skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportSydhavnteaterCRUD:
    def test_creates_new_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1
        event = Event.objects.get(external_source="sydhavnteater")
        assert event.title == "Test Sydhavn Event"
        assert event.venue_name == "Kapelscenen"

    def test_updates_changed_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))

        updated = {**SYDHAVN_SAMPLE_EVENT, "title": "Updated Sydhavn Event"}
        _write_json([updated], f)
        call_command("import_sydhavnteater", str(f))

        assert Event.objects.filter(external_source="sydhavnteater").count() == 1
        assert (
            Event.objects.get(external_source="sydhavnteater").title
            == "Updated Sydhavn Event"
        )

    def test_unchanged_event_is_skipped(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))
        call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1

    def test_deletes_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1

        _write_json([], f)
        call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 0

    def test_no_delete_preserves_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))

        _write_json([], f)
        call_command("import_sydhavnteater", str(f), no_delete=True)
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1

    def test_skips_record_with_bad_datetime(self, tmp_path):
        f = tmp_path / "events.json"
        bad = {**SYDHAVN_SAMPLE_EVENT, "start_datetime": "not-a-date"}
        _write_json([bad], f)
        call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 0

    def test_category_mapping(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**SYDHAVN_SAMPLE_EVENT, "category": "workshop"}], f)
        call_command("import_sydhavnteater", str(f))
        event = Event.objects.get(external_source="sydhavnteater")
        assert event.category == "workshop"

    def test_unknown_category_defaults_to_other(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([{**SYDHAVN_SAMPLE_EVENT, "category": "unknown_type"}], f)
        call_command("import_sydhavnteater", str(f))
        event = Event.objects.get(external_source="sydhavnteater")
        assert event.category == "other"


# ---------------------------------------------------------------------------
# Command: dry-run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportSydhavnteaterDryRun:
    def test_dry_run_does_not_create(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f), dry_run=True)
        assert Event.objects.filter(external_source="sydhavnteater").count() == 0

    def test_dry_run_does_not_update(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))

        updated = {**SYDHAVN_SAMPLE_EVENT, "title": "Dry Run Title"}
        _write_json([updated], f)
        call_command("import_sydhavnteater", str(f), dry_run=True)
        assert (
            Event.objects.get(external_source="sydhavnteater").title
            == "Test Sydhavn Event"
        )

    def test_dry_run_does_not_delete(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([SYDHAVN_SAMPLE_EVENT], f)
        call_command("import_sydhavnteater", str(f))

        _write_json([], f)
        call_command("import_sydhavnteater", str(f), dry_run=True)
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1


# ---------------------------------------------------------------------------
# Command: image handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportSydhavnteaterImages:
    def test_skip_images_creates_event_without_image(self, tmp_path):
        event_rec = {**SYDHAVN_SAMPLE_EVENT, "image_url": "https://example.com/img.jpg"}
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        call_command("import_sydhavnteater", str(f), skip_images=True)
        event = Event.objects.get(external_source="sydhavnteater")
        assert not event.image.name

    def test_image_download_failure_is_handled(self, tmp_path):
        event_rec = {**SYDHAVN_SAMPLE_EVENT, "image_url": "https://example.com/img.jpg"}
        f = tmp_path / "events.json"
        _write_json([event_rec], f)
        with patch(
            "events.management.commands.base_import._download_image",
            return_value=None,
        ):
            call_command("import_sydhavnteater", str(f))
        assert Event.objects.filter(external_source="sydhavnteater").count() == 1


# ===========================================================================
# System user attribution (base_import shared behaviour)
# ===========================================================================


@pytest.mark.django_db
class TestSystemUserAttribution:
    """The import sets submitted_by to the matching system account when one exists."""

    def _make_system_user(self, slug):
        user = UserModel(
            email=f"system.{slug}@pleskal.internal",
            display_name=slug.capitalize(),
            display_name_slug=slug,
            is_system_account=True,
        )
        user.set_unusable_password()
        user.save()
        return user

    def test_submitted_by_set_to_system_user_on_create(self, tmp_path):
        system_user = self._make_system_user("dansehallerne")
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        event = Event.objects.get(external_source="dansehallerne")
        assert event.submitted_by == system_user

    def test_submitted_by_none_when_no_system_user(self, tmp_path):
        # No system user created — should fall back to None gracefully.
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        event = Event.objects.get(external_source="dansehallerne")
        assert event.submitted_by is None

    def test_system_user_not_shared_across_sources(self, tmp_path):
        # A system user for hautscene must not be picked up by import_dansehallerne.
        self._make_system_user("hautscene")
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        event = Event.objects.get(external_source="dansehallerne")
        assert event.submitted_by is None

    def test_submitted_by_updated_when_system_user_created_later(self, tmp_path):
        # First import without system user → submitted_by=None.
        f = tmp_path / "events.json"
        _write_json([SAMPLE_EVENT], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.get(external_source="dansehallerne").submitted_by is None

        # Create system user, re-import — existing event is updated.
        system_user = self._make_system_user("dansehallerne")
        call_command("import_dansehallerne", str(f))
        assert (
            Event.objects.get(external_source="dansehallerne").submitted_by
            == system_user
        )


# ===========================================================================
# Stale-deletion: category_scope isolates workshops from regular events
# ===========================================================================


@pytest.mark.django_db
class TestCategoryScope:
    """import_dansehallerne_workshops must not delete non-workshop dansehallerne events."""

    FUTURE_PERFORMANCE = {
        **SAMPLE_EVENT,
        "source_url": "https://dansehallerne.dk/event/perf1",
        "title": "Future Performance",
        "category": "performance",
    }
    FUTURE_WORKSHOP = {
        **SAMPLE_EVENT,
        "source_url": "https://dansehallerne.dk/workshop/1",
        "title": "Future Workshop",
        "category": "workshop",
    }

    def test_workshops_importer_does_not_delete_performance_events(self, tmp_path):
        # Import a performance and a workshop via the regular importer.
        f = tmp_path / "events.json"
        _write_json([self.FUTURE_PERFORMANCE, self.FUTURE_WORKSHOP], f)
        call_command("import_dansehallerne", str(f))
        assert Event.objects.filter(external_source="dansehallerne").count() == 2

        # Run workshops importer with an empty file — only the workshop should be deleted.
        wf = tmp_path / "workshops.json"
        _write_json([], wf)
        call_command("import_dansehallerne_workshops", str(wf))

        assert Event.objects.filter(
            source_url=self.FUTURE_PERFORMANCE["source_url"]
        ).exists(), "Performance event must not be deleted by workshops importer"
        assert not Event.objects.filter(
            source_url=self.FUTURE_WORKSHOP["source_url"]
        ).exists(), "Stale workshop event should be deleted"

    def test_regular_importer_does_not_delete_workshop_events(self, tmp_path):
        # Import both via the workshops importer first.
        wf = tmp_path / "workshops.json"
        _write_json([self.FUTURE_WORKSHOP], wf)
        call_command("import_dansehallerne_workshops", str(wf))
        assert Event.objects.filter(
            source_url=self.FUTURE_WORKSHOP["source_url"]
        ).exists()

        # Run the regular importer with only the performance — workshop must survive.
        f = tmp_path / "events.json"
        _write_json([self.FUTURE_PERFORMANCE], f)
        call_command("import_dansehallerne", str(f))

        assert Event.objects.filter(
            source_url=self.FUTURE_WORKSHOP["source_url"]
        ).exists(), "Workshop event must not be deleted by regular importer"


# ===========================================================================
# import_kbhdanser tests
# ===========================================================================

KBHDANSER_SAMPLE_EVENT = {
    "source_url": "https://kbhdanser.dk/en/chroniques/",
    "start_datetime": "2030-05-21T17:30:00+00:00",
    "end_datetime": None,
    "title": "Chroniques",
    "description": "A captivating performance by Peeping Tom.",
    "venue_name": "Østre Gasværk Teater",
    "venue_address": "Nyborggade 17, 2100 København Ø",
    "category": "performance",
    "is_free": False,
    "is_wheelchair_accessible": False,
    "price_note": "See ticket link for pricing",
    "image_url": "",
}


@pytest.mark.django_db
class TestImportKbhdanserErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CommandError, match="File not found"):
            call_command("import_kbhdanser", str(tmp_path / "missing.json"))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json", encoding="utf-8")
        with pytest.raises(CommandError, match="Invalid JSON"):
            call_command("import_kbhdanser", str(f))

    def test_non_list_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"key": "val"}', encoding="utf-8")
        with pytest.raises(CommandError, match="top-level list"):
            call_command("import_kbhdanser", str(f))


@pytest.mark.django_db
class TestImportKbhdanserCRUD:
    def test_creates_new_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f))
        assert Event.objects.filter(external_source="kbhdanser").count() == 1
        event = Event.objects.get(external_source="kbhdanser")
        assert event.title == "Chroniques"
        assert event.venue_name == "Østre Gasværk Teater"

    def test_updates_changed_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f))

        updated = {**KBHDANSER_SAMPLE_EVENT, "title": "Chroniques Updated"}
        _write_json([updated], f)
        call_command("import_kbhdanser", str(f))

        assert Event.objects.filter(external_source="kbhdanser").count() == 1
        assert (
            Event.objects.get(external_source="kbhdanser").title == "Chroniques Updated"
        )

    def test_unchanged_event_is_skipped(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f))
        call_command("import_kbhdanser", str(f))
        assert Event.objects.filter(external_source="kbhdanser").count() == 1

    def test_deletes_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f))
        assert Event.objects.filter(external_source="kbhdanser").count() == 1

        _write_json([], f)
        call_command("import_kbhdanser", str(f))
        assert Event.objects.filter(external_source="kbhdanser").count() == 0

    def test_no_delete_preserves_stale_events(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f))

        _write_json([], f)
        call_command("import_kbhdanser", str(f), no_delete=True)
        assert Event.objects.filter(external_source="kbhdanser").count() == 1

    def test_dry_run_does_not_create(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT], f)
        call_command("import_kbhdanser", str(f), dry_run=True)
        assert Event.objects.filter(external_source="kbhdanser").count() == 0

    def test_multiple_performances_same_event_url(self, tmp_path):
        """Multiple performances (same source_url, different start_datetime) are all created."""
        perf2 = {
            **KBHDANSER_SAMPLE_EVENT,
            "start_datetime": "2030-05-22T17:30:00+00:00",
        }
        f = tmp_path / "events.json"
        _write_json([KBHDANSER_SAMPLE_EVENT, perf2], f)
        call_command("import_kbhdanser", str(f))
        assert Event.objects.filter(external_source="kbhdanser").count() == 2


# ===========================================================================
# import_toastercph tests
# ===========================================================================

TOASTERCPH_SAMPLE_EVENT = {
    "source_url": "https://toastercph.dk/event/test-event",
    "start_datetime": "2030-06-01T18:00:00+02:00",
    "end_datetime": None,
    "title": "Test Toaster Event",
    "description": "A test toastercph event",
    "venue_name": "Toaster CPH",
    "venue_address": "",
    "category": "performance",
    "is_free": False,
    "is_wheelchair_accessible": False,
    "price_note": "",
    "image_url": "",
}


@pytest.mark.django_db
class TestImportToastercphCRUD:
    def test_creates_new_event(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([TOASTERCPH_SAMPLE_EVENT], f)
        call_command("import_toastercph", str(f))
        assert Event.objects.filter(external_source="toastercph").count() == 1
        event = Event.objects.get(external_source="toastercph")
        assert event.title == "Test Toaster Event"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CommandError, match="File not found"):
            call_command("import_toastercph", str(tmp_path / "missing.json"))

    def test_dry_run_does_not_create(self, tmp_path):
        f = tmp_path / "events.json"
        _write_json([TOASTERCPH_SAMPLE_EVENT], f)
        call_command("import_toastercph", str(f), dry_run=True)
        assert Event.objects.filter(external_source="toastercph").count() == 0
