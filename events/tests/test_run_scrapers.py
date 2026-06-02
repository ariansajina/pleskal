"""Tests for the run_scrapers management command's retired-source cleanup.

A source listed in ``SCRAPER_DISABLED_AFTER`` past its cutoff date is not only
skipped — its previously imported events are purged so they don't linger in the
database.  These tests cover that cleanup path without hitting the network
(disabled sources never invoke their scrape function).
"""

import datetime

import pytest
from django.core.management import call_command

from events.management.commands import run_scrapers
from events.tests.factories import EventFactory

PAST = datetime.date(2020, 1, 1)


@pytest.fixture
def retired_toaster(monkeypatch):
    """Force toastercph to be a retired source regardless of the real config."""
    monkeypatch.setitem(run_scrapers.SCRAPER_DISABLED_AFTER, "toastercph", PAST)


@pytest.mark.django_db
class TestRunScrapersCleanup:
    def test_purges_events_from_retired_source(self, retired_toaster):
        EventFactory.create_batch(3, external_source="toastercph")
        EventFactory.create_batch(2, external_source="hautscene")

        call_command("run_scrapers", only=["toastercph"])

        from events.models import Event

        assert Event.objects.filter(external_source="toastercph").count() == 0
        # Other sources are untouched.
        assert Event.objects.filter(external_source="hautscene").count() == 2

    def test_dry_run_keeps_events(self, retired_toaster):
        EventFactory.create_batch(3, external_source="toastercph")

        call_command("run_scrapers", only=["toastercph"], dry_run=True)

        from events.models import Event

        assert Event.objects.filter(external_source="toastercph").count() == 3

    def test_cleanup_is_idempotent_when_no_events(self, retired_toaster):
        # No toastercph events exist; cleanup should be a harmless no-op.
        call_command("run_scrapers", only=["toastercph"])

        from events.models import Event

        assert Event.objects.filter(external_source="toastercph").count() == 0
