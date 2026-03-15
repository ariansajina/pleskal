"""Tests for Feature 12: iCal and RSS feeds."""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.models import Event, EventStatus
from events.tests.factories import EventFactory


def _past_event(**kwargs):
    """Create an approved event with a past start_datetime (bypassing model clean)."""
    e = Event(
        title=kwargs.get("title", "Past Event"),
        start_datetime=timezone.now() - timezone.timedelta(days=5),
        venue_name=kwargs.get("venue_name", "Old Hall"),
        category=kwargs.get("category", "social"),
        status=EventStatus.APPROVED,
    )
    e.save()
    return e


@pytest.mark.django_db
class TestRSSFeed:
    def test_rss_returns_200(self, client):
        resp = client.get(reverse("event_rss_feed"))
        assert resp.status_code == 200

    def test_rss_content_type(self, client):
        resp = client.get(reverse("event_rss_feed"))
        assert "xml" in resp["Content-Type"]

    def test_rss_contains_approved_upcoming_event(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_rss_feed"))
        assert str(event.title).encode() in resp.content

    def test_rss_excludes_pending_events(self, client):
        event = EventFactory.create(status=EventStatus.PENDING)
        resp = client.get(reverse("event_rss_feed"))
        assert str(event.title).encode() not in resp.content

    def test_rss_excludes_rejected_events(self, client):
        event = EventFactory.create(status=EventStatus.REJECTED, rejection_note="No.")
        resp = client.get(reverse("event_rss_feed"))
        assert str(event.title).encode() not in resp.content

    def test_rss_excludes_past_events(self, client):
        _past_event(title="Gone Event")
        resp = client.get(reverse("event_rss_feed"))
        assert b"Gone Event" not in resp.content

    def test_rss_category_filter(self, client):
        workshop = EventFactory.create(status=EventStatus.APPROVED, category="workshop")
        social = EventFactory.create(status=EventStatus.APPROVED, category="social")
        resp = client.get(reverse("event_rss_feed") + "?category=workshop")
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() not in resp.content

    def test_rss_no_submitter_identity(self, client):
        user = UserFactory.create(email="private@example.com", username="privateuser")
        EventFactory.create(status=EventStatus.APPROVED, submitted_by=user)
        resp = client.get(reverse("event_rss_feed"))
        assert b"private@example.com" not in resp.content
        assert b"privateuser" not in resp.content

    def test_rss_is_valid_xml(self, client):
        EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_rss_feed"))
        import xml.etree.ElementTree as ET

        # Should not raise
        ET.fromstring(resp.content)


@pytest.mark.django_db
class TestICalFeed:
    def test_ical_returns_200(self, client):
        resp = client.get(reverse("event_ical_feed"))
        assert resp.status_code == 200

    def test_ical_content_type(self, client):
        resp = client.get(reverse("event_ical_feed"))
        assert "calendar" in resp["Content-Type"]

    def test_ical_begins_with_vcalendar(self, client):
        resp = client.get(reverse("event_ical_feed"))
        assert resp.content.startswith(b"BEGIN:VCALENDAR")

    def test_ical_contains_approved_upcoming_event(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_ical_feed"))
        assert str(event.title).encode() in resp.content

    def test_ical_excludes_pending_events(self, client):
        event = EventFactory.create(status=EventStatus.PENDING)
        resp = client.get(reverse("event_ical_feed"))
        assert str(event.title).encode() not in resp.content

    def test_ical_excludes_past_events(self, client):
        _past_event(title="Past iCal Event")
        resp = client.get(reverse("event_ical_feed"))
        assert b"Past iCal Event" not in resp.content

    def test_ical_category_filter(self, client):
        workshop = EventFactory.create(status=EventStatus.APPROVED, category="workshop")
        social = EventFactory.create(status=EventStatus.APPROVED, category="social")
        resp = client.get(reverse("event_ical_feed") + "?category=workshop")
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() not in resp.content

    def test_ical_no_submitter_identity(self, client):
        user = UserFactory.create(email="secret@example.com", username="secretuser")
        EventFactory.create(status=EventStatus.APPROVED, submitted_by=user)
        resp = client.get(reverse("event_ical_feed"))
        assert b"secret@example.com" not in resp.content
        assert b"secretuser" not in resp.content

    def test_ical_contains_venue(self, client):
        EventFactory.create(
            status=EventStatus.APPROVED,
            venue_name="The Grand Hall",
            venue_address="1 Dance St",
        )
        resp = client.get(reverse("event_ical_feed"))
        assert b"The Grand Hall" in resp.content

    def test_ical_contains_uid(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_ical_feed"))
        assert str(event.id).encode() in resp.content

    def test_ical_is_valid_ical(self, client):
        EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_ical_feed"))
        from icalendar import Calendar

        # Should not raise
        cal = Calendar.from_ical(resp.content)
        assert cal is not None
