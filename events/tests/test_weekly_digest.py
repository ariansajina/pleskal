"""Tests for the weekly_digest management command."""

from io import StringIO
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.models import Event, FeedHit
from events.tests.factories import EventFactory

User = get_user_model()


def _digest_email():
    """Return the weekly digest email from the outbox (not signup notifications)."""
    return next(m for m in mail.outbox if "weekly digest" in m.subject)


@pytest.mark.django_db
class TestWeeklyDigestDryRun:
    def test_dry_run_prints_to_stdout(self):
        stdout = StringIO()
        call_command("weekly_digest", dry_run=True, stdout=stdout)
        output = stdout.getvalue()
        assert "Weekly digest for pleskal" in output
        assert "This week" in output
        assert "All time" in output

    def test_dry_run_sends_no_email(self, settings):
        settings.ADMINS = ["admin@example.com"]
        call_command("weekly_digest", dry_run=True, stdout=StringIO())
        assert not any("weekly digest" in m.subject for m in mail.outbox)

    def test_dry_run_shows_correct_counts(self, settings):
        settings.ADMINS = []
        UserFactory.create_batch(3)
        # submitted_by=None avoids creating extra users via SubFactory
        EventFactory.create_batch(2, submitted_by=None)
        stdout = StringIO()
        call_command("weekly_digest", dry_run=True, stdout=stdout)
        output = stdout.getvalue()
        assert "New signups:   3" in output
        assert "New events:    2" in output


@pytest.mark.django_db
class TestWeeklyDigestEmail:
    def test_sends_to_admins(self, settings):
        settings.ADMINS = ["admin@example.com", "other@example.com"]
        call_command("weekly_digest", stdout=StringIO())
        digest = _digest_email()
        assert set(digest.to) == {"admin@example.com", "other@example.com"}

    def test_subject_contains_date(self, settings):
        settings.ADMINS = ["admin@example.com"]
        call_command("weekly_digest", stdout=StringIO())
        today = timezone.now().strftime("%Y-%m-%d")
        assert today in _digest_email().subject

    def test_email_body_contains_stats(self, settings):
        settings.ADMINS = ["admin@example.com"]
        UserFactory.create_batch(2)
        EventFactory.create_batch(4, submitted_by=None)
        call_command("weekly_digest", stdout=StringIO())
        body = _digest_email().body
        assert "New signups:   2" in body
        assert "New events:    4" in body
        assert "Total users:" in body
        assert "Total events:" in body

    def test_no_admins_sends_no_email(self, settings):
        settings.ADMINS = []
        call_command("weekly_digest", stdout=StringIO())
        assert not any("weekly digest" in m.subject for m in mail.outbox)

    def test_old_events_not_counted_as_new(self, settings):
        settings.ADMINS = ["admin@example.com"]
        old_time = timezone.now() - timezone.timedelta(days=10)
        event = cast(Event, EventFactory(submitted_by=None))
        # Backdating via queryset update bypasses auto_now_add
        Event.objects.filter(pk=event.pk).update(created_at=old_time)
        call_command("weekly_digest", stdout=StringIO())
        assert "New events:    0" in _digest_email().body

    def test_old_users_not_counted_as_new(self, settings):
        settings.ADMINS = ["admin@example.com"]
        old_time = timezone.now() - timezone.timedelta(days=10)
        user = cast(User, UserFactory())
        User.objects.filter(pk=user.pk).update(date_joined=old_time)
        call_command("weekly_digest", stdout=StringIO())
        assert "New signups:   0" in _digest_email().body

    def test_feed_hits_appear_in_digest(self, settings):
        settings.ADMINS = ["admin@example.com"]
        FeedHit.objects.create(
            feed_type=FeedHit.RSS, date=timezone.localdate(), count=5
        )
        FeedHit.objects.create(
            feed_type=FeedHit.ICAL, date=timezone.localdate(), count=3
        )
        call_command("weekly_digest", stdout=StringIO())
        body = _digest_email().body
        assert "RSS feed hits: 5 (0.7/day avg)" in body
        assert "iCal hits:     3 (0.4/day avg)" in body

    def test_old_feed_hits_not_counted(self, settings):
        settings.ADMINS = ["admin@example.com"]
        old_date = timezone.localdate() - timezone.timedelta(days=10)
        FeedHit.objects.create(feed_type=FeedHit.RSS, date=old_date, count=99)
        call_command("weekly_digest", stdout=StringIO())
        assert "RSS feed hits: 0 (0.0/day avg)" in _digest_email().body
