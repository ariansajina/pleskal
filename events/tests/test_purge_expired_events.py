"""Tests for the purge_expired_events retention command and its Q helpers."""

import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from events.models import Event, hidden_events_q
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
    settings.USER_EVENT_HIDE_AFTER_DAYS = 730


@pytest.mark.django_db
class TestPurgeExpiredEvents:
    def test_scraped_events_expire_after_scraped_retention(self):
        expired = _scraped(start_datetime=_days_ago(91))
        kept = _scraped(start_datetime=_days_ago(89))

        call_command("purge_expired_events")

        assert _surviving_ids() == {kept.pk}
        assert expired.pk not in _surviving_ids()

    def test_user_events_are_never_deleted(self):
        ancient = EventFactory.create(start_datetime=_days_ago(10 * 365))
        ancient_draft = EventFactory.create(
            start_datetime=_days_ago(10 * 365), is_draft=True
        )

        call_command("purge_expired_events")

        assert _surviving_ids() == {ancient.pk, ancient_draft.pk}

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

        call_command("purge_expired_events", dry_run=True)

        assert Event.objects.count() == 1

    def test_scraped_retention_is_configurable(self, settings):
        settings.SCRAPED_EVENT_RETENTION_DAYS = 10
        _scraped(start_datetime=_days_ago(11))
        kept = _scraped(start_datetime=_days_ago(9))

        call_command("purge_expired_events")

        assert _surviving_ids() == {kept.pk}


@pytest.mark.django_db
class TestHiddenEventsQ:
    def _visible_ids(self):
        return set(
            Event.objects.exclude(hidden_events_q()).values_list("pk", flat=True)
        )

    def test_user_events_hidden_after_hide_after_days(self):
        recent = EventFactory.create(start_datetime=_days_ago(729))
        EventFactory.create(start_datetime=_days_ago(731))

        assert self._visible_ids() == {recent.pk}

    def test_expired_scraped_events_hidden_before_purge(self):
        recent = _scraped(start_datetime=_days_ago(89))
        _scraped(start_datetime=_days_ago(91))

        assert self._visible_ids() == {recent.pk}

    def test_hide_after_is_configurable(self, settings):
        settings.USER_EVENT_HIDE_AFTER_DAYS = 30
        recent = EventFactory.create(start_datetime=_days_ago(29))
        EventFactory.create(start_datetime=_days_ago(31))

        assert self._visible_ids() == {recent.pk}

    def test_exclude_keeps_events_without_end_time(self):
        """exclude() on the nullable end_datetime must not drop open-ended rows."""
        open_ended = EventFactory.create(start_datetime=_days_ago(5), end_datetime=None)

        assert self._visible_ids() == {open_ended.pk}
