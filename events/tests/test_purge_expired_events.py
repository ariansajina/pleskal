"""Tests for the purge_expired_events retention command."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from events.models import Event, expired_events_q
from events.tests.factories import EventFactory


def _days_ago(days):
    return timezone.now() - datetime.timedelta(days=days)


def _scraped(**kwargs):
    return EventFactory.create(external_source="hautscene", **kwargs)


def _surviving_ids():
    return set(Event.objects.values_list("pk", flat=True))


@pytest.fixture(autouse=True)
def _retention(settings):
    settings.SCRAPED_EVENT_RETENTION_DAYS = 90
    settings.USER_EVENT_RETENTION_DAYS = 730


@pytest.mark.django_db
class TestPurgeExpiredEvents:
    def test_scraped_events_expire_after_scraped_retention(self):
        expired = _scraped(start_datetime=_days_ago(91))
        kept = _scraped(start_datetime=_days_ago(89))

        call_command("purge_expired_events")

        assert _surviving_ids() == {kept.pk}
        assert expired.pk not in _surviving_ids()

    def test_user_events_expire_after_user_retention(self):
        expired = EventFactory.create(start_datetime=_days_ago(731))
        kept = EventFactory.create(start_datetime=_days_ago(91))

        call_command("purge_expired_events")

        assert _surviving_ids() == {kept.pk}
        assert expired.pk not in _surviving_ids()

    def test_user_drafts_expire_too(self):
        EventFactory.create(start_datetime=_days_ago(731), is_draft=True)

        call_command("purge_expired_events")

        assert not Event.objects.exists()

    def test_retention_counts_from_the_end_of_a_long_running_event(self):
        # Started long ago but still on (e.g. an exhibition): not expired.
        running = _scraped(start_datetime=_days_ago(200), end_datetime=_days_ago(-10))
        ended = _scraped(start_datetime=_days_ago(200), end_datetime=_days_ago(91))

        call_command("purge_expired_events")

        assert _surviving_ids() == {running.pk}
        assert ended.pk not in _surviving_ids()

    def test_upcoming_events_are_never_purged(self):
        upcoming = _scraped()

        call_command("purge_expired_events")

        assert _surviving_ids() == {upcoming.pk}

    def test_dry_run_deletes_nothing(self):
        _scraped(start_datetime=_days_ago(91))
        EventFactory.create(start_datetime=_days_ago(731))

        call_command("purge_expired_events", dry_run=True)

        assert Event.objects.count() == 2

    def test_retention_periods_are_configurable(self, settings):
        settings.SCRAPED_EVENT_RETENTION_DAYS = 10
        settings.USER_EVENT_RETENTION_DAYS = 20
        _scraped(start_datetime=_days_ago(11))
        user_event = EventFactory.create(start_datetime=_days_ago(11))

        call_command("purge_expired_events")

        assert _surviving_ids() == {user_event.pk}


@pytest.mark.django_db
def test_expired_events_q_exclude_keeps_events_without_end_time():
    """exclude() on the nullable end_datetime must not drop open-ended rows."""
    open_ended = EventFactory.create(start_datetime=_days_ago(5), end_datetime=None)

    assert list(Event.objects.exclude(expired_events_q())) == [open_ended]
