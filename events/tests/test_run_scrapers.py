"""Tests for the run_scrapers management command's retired-source cleanup.

A source listed in ``SCRAPER_DISABLED_AFTER`` past its cutoff date is not only
skipped — its previously imported events are purged and its system account is
deactivated, so neither lingers in the database / UI.  These tests cover that
cleanup path without hitting the network (disabled sources never invoke their
scrape function).
"""

import datetime
from dataclasses import replace
from unittest.mock import patch

import pytest
from django.core.management import call_command

from accounts.tests.factories import UserFactory
from events.management.commands import run_scrapers
from events.models import Event
from events.tests.factories import EventFactory
from scrapers.registry import SOURCES

PAST = datetime.date(2020, 1, 1)


def _patched_sources(monkeypatch, scrape_fn, name="hautscene"):
    """Replace the registry seen by run_scrapers with one stubbed source."""
    fake = replace(SOURCES[name], scrape=scrape_fn, scrape_kwargs={})
    monkeypatch.setattr(run_scrapers, "SOURCES", {name: fake})


@pytest.fixture
def retired_toaster(monkeypatch):
    """Force toastercph to be a retired source regardless of the real config."""
    monkeypatch.setitem(run_scrapers.SCRAPER_DISABLED_AFTER, "toastercph", PAST)


@pytest.fixture
def toaster_account():
    """A system account whose slug matches the toastercph external_source."""
    return UserFactory.create(
        is_system_account=True,
        display_name="Toaster",
        display_name_slug="toastercph",
    )


@pytest.mark.django_db
class TestRunScrapersCleanup:
    def test_purges_events_from_retired_source(self, retired_toaster):
        EventFactory.create_batch(3, external_source="toastercph")
        EventFactory.create_batch(2, external_source="hautscene")

        call_command("run_scrapers", only=["toastercph"])

        assert Event.objects.filter(external_source="toastercph").count() == 0
        # Other sources are untouched.
        assert Event.objects.filter(external_source="hautscene").count() == 2

    def test_deactivates_retired_source_account(self, retired_toaster, toaster_account):
        call_command("run_scrapers", only=["toastercph"])

        toaster_account.refresh_from_db()
        assert toaster_account.is_active is False

    def test_dry_run_keeps_events_and_account(self, retired_toaster, toaster_account):
        EventFactory.create_batch(3, external_source="toastercph")

        call_command("run_scrapers", only=["toastercph"], dry_run=True)

        assert Event.objects.filter(external_source="toastercph").count() == 3
        toaster_account.refresh_from_db()
        assert toaster_account.is_active is True

    def test_cleanup_is_idempotent_when_no_events(self, retired_toaster):
        # No toastercph events exist; cleanup should be a harmless no-op.
        call_command("run_scrapers", only=["toastercph"])

        assert Event.objects.filter(external_source="toastercph").count() == 0


@pytest.mark.django_db
class TestRunScrapersSentryReporting:
    def test_scraper_failure_is_captured_with_tag(self, monkeypatch):
        boom = RuntimeError("site layout changed")

        def failing_scrape(**kwargs):
            raise boom

        _patched_sources(monkeypatch, failing_scrape)
        captured = []
        monkeypatch.setattr(
            run_scrapers.sentry_sdk, "capture_exception", captured.append
        )

        with pytest.raises(SystemExit):
            call_command("run_scrapers", only=["hautscene"])

        assert captured == [boom]

    def test_successful_run_captures_nothing(self, monkeypatch):
        _patched_sources(monkeypatch, lambda **kwargs: [])
        captured = []
        monkeypatch.setattr(
            run_scrapers.sentry_sdk, "capture_exception", captured.append
        )

        call_command("run_scrapers", only=["hautscene"])

        assert captured == []


@pytest.mark.django_db
class TestRunScrapersGeocodingBackfill:
    """run_scrapers is the scrape-cron entry point, so it's the recovery path
    for events that saved without coordinates (H2/H3): it must re-run
    backfill_geocoding on every pass."""

    def test_backfill_runs_after_scrapers(self, monkeypatch):
        _patched_sources(monkeypatch, lambda **kwargs: [])
        event = EventFactory.create(
            venue_name="Dansehallerne", latitude=None, longitude=None
        )
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(55.6761, 12.5683),
        ):
            call_command("run_scrapers", only=["hautscene"])
        event.refresh_from_db()
        assert event.latitude == pytest.approx(55.6761)
        assert event.longitude == pytest.approx(12.5683)

    def test_dry_run_passed_through_to_backfill(self, monkeypatch):
        _patched_sources(monkeypatch, lambda **kwargs: [])
        event = EventFactory.create(
            venue_name="Dansehallerne", latitude=None, longitude=None
        )
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(55.6761, 12.5683),
        ):
            call_command("run_scrapers", only=["hautscene"], dry_run=True)
        event.refresh_from_db()
        assert event.latitude is None

    def test_backfill_failure_is_captured_and_does_not_abort_run(self, monkeypatch):
        _patched_sources(monkeypatch, lambda **kwargs: [])
        captured = []
        monkeypatch.setattr(
            run_scrapers.sentry_sdk, "capture_exception", captured.append
        )
        boom = RuntimeError("backfill boom")

        with patch(
            "events.management.commands.run_scrapers.call_command", side_effect=boom
        ):
            call_command("run_scrapers", only=["hautscene"])  # must not raise

        assert captured == [boom]


@pytest.mark.django_db
class TestImportEventsSourceArg:
    def test_unknown_source_raises(self, tmp_path):
        from django.core.management.base import CommandError

        f = tmp_path / "events.json"
        f.write_text("[]", encoding="utf-8")
        with pytest.raises(CommandError):
            call_command("import_events", "not_a_source", str(f))
