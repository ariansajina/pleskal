"""Tests for the run_scrapers management command's retired-source cleanup.

A source listed in ``SCRAPER_DISABLED_AFTER`` past its cutoff date is not only
skipped — its previously imported events are purged and its system account is
deactivated, so neither lingers in the database / UI.  These tests cover that
cleanup path without hitting the network (disabled sources never invoke their
scrape function).
"""

import datetime

import pytest
from django.core.management import call_command

from accounts.tests.factories import UserFactory
from events.management.commands import run_scrapers
from events.models import Event
from events.tests.factories import EventFactory

PAST = datetime.date(2020, 1, 1)


@pytest.fixture
def retired_toaster(monkeypatch):
    """Force toastercph to be a retired source regardless of the real config."""
    monkeypatch.setitem(run_scrapers.SCRAPER_DISABLED_AFTER, "toastercph", PAST)


@pytest.fixture
def toaster_account():
    """A system account whose slug matches import_toastercph.external_source."""
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
