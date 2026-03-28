"""Tests for iCal and RSS feeds."""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.models import Event, EventCategory, FeedHit
from events.tests.factories import EventFactory


def _past_event(**kwargs):
    """Create an event with a past start_datetime (bypassing model clean)."""
    e = Event(
        title=kwargs.get("title", "Past Event"),
        start_datetime=timezone.now() - timezone.timedelta(days=5),
        venue_name=kwargs.get("venue_name", "Old Hall"),
        category=kwargs.get("category", "social"),
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

    def test_rss_contains_upcoming_event(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_rss_feed"))
        assert str(event.title).encode() in resp.content

    def test_rss_excludes_past_events(self, client):
        _past_event(title="Gone Event")
        resp = client.get(reverse("event_rss_feed"))
        assert b"Gone Event" not in resp.content

    def test_rss_category_filter(self, client):
        workshop = EventFactory.create(category="workshop")
        social = EventFactory.create(category="social")
        resp = client.get(reverse("event_rss_feed") + "?category=workshop")
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() not in resp.content

    def test_rss_no_submitter_identity(self, client):
        user = UserFactory.create(email="private@example.com")
        EventFactory.create(submitted_by=user)
        resp = client.get(reverse("event_rss_feed"))
        assert b"private@example.com" not in resp.content

    def test_rss_is_valid_xml(self, client):
        EventFactory.create()
        resp = client.get(reverse("event_rss_feed"))
        import xml.etree.ElementTree as ET

        # Should not raise
        ET.fromstring(resp.content)

    def test_rss_records_hit(self, client):
        client.get(reverse("event_rss_feed"))
        assert FeedHit.objects.filter(feed_type=FeedHit.RSS).exists()

    def test_rss_hit_count_increments(self, client):
        client.get(reverse("event_rss_feed"))
        client.get(reverse("event_rss_feed"))
        total = sum(h.count for h in FeedHit.objects.filter(feed_type=FeedHit.RSS))
        assert total >= 2


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

    def test_ical_contains_upcoming_event(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_feed"))
        assert str(event.title).encode() in resp.content

    def test_ical_excludes_past_events(self, client):
        _past_event(title="Past iCal Event")
        resp = client.get(reverse("event_ical_feed"))
        assert b"Past iCal Event" not in resp.content

    def test_ical_category_filter(self, client):
        workshop = EventFactory.create(category="workshop")
        social = EventFactory.create(category="social")
        resp = client.get(reverse("event_ical_feed") + "?category=workshop")
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() not in resp.content

    def test_ical_no_submitter_identity(self, client):
        user = UserFactory.create(email="secret@example.com")
        EventFactory.create(submitted_by=user)
        resp = client.get(reverse("event_ical_feed"))
        assert b"secret@example.com" not in resp.content

    def test_ical_contains_venue(self, client):
        EventFactory.create(
            venue_name="The Grand Hall",
            venue_address="1 Dance St",
        )
        resp = client.get(reverse("event_ical_feed"))
        assert b"The Grand Hall" in resp.content

    def test_ical_contains_uid(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_feed"))
        assert str(event.id).encode() in resp.content

    def test_ical_is_valid_ical(self, client):
        EventFactory.create()
        resp = client.get(reverse("event_ical_feed"))
        from icalendar import Calendar

        # Should not raise
        cal = Calendar.from_ical(resp.content)
        assert cal is not None

    def test_ical_records_hit(self, client):
        client.get(reverse("event_ical_feed"))
        assert FeedHit.objects.filter(feed_type=FeedHit.ICAL).exists()

    def test_ical_hit_count_increments(self, client):
        client.get(reverse("event_ical_feed"))
        client.get(reverse("event_ical_feed"))
        total = sum(h.count for h in FeedHit.objects.filter(feed_type=FeedHit.ICAL))
        assert total >= 2


@pytest.mark.django_db
class TestEventICalSingleView:
    def test_returns_200(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_content_type(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert "calendar" in resp["Content-Type"]

    def test_begins_with_vcalendar(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert resp.content.startswith(b"BEGIN:VCALENDAR")

    def test_contains_event_title(self, client):
        event = EventFactory.create(title="Tango Night")
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert b"Tango Night" in resp.content

    def test_contains_uid(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert str(event.id).encode() in resp.content

    def test_contains_venue(self, client):
        event = EventFactory.create(
            venue_name="Dansehallerne", venue_address="Pasteursvej 20"
        )
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert b"Dansehallerne" in resp.content

    def test_nonexistent_slug_returns_404(self, client):
        resp = client.get(
            reverse("event_ical_single", kwargs={"slug": "no-such-event"})
        )
        assert resp.status_code == 404

    def test_content_disposition_contains_slug(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert event.slug in resp["Content-Disposition"]

    def test_is_valid_ical(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        from icalendar import Calendar

        cal = Calendar.from_ical(resp.content)
        assert cal is not None

    def test_includes_dtend_when_end_datetime_set(self, client):
        event = EventFactory.create(
            end_datetime=timezone.now() + timezone.timedelta(days=7, hours=2)
        )
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert b"DTEND" in resp.content

    def test_omits_dtend_when_no_end_datetime(self, client):
        event = EventFactory.create(end_datetime=None)
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert b"DTEND" not in resp.content

    def test_includes_source_url(self, client):
        event = EventFactory.create(source_url="https://example.com/event")
        resp = client.get(reverse("event_ical_single", kwargs={"slug": event.slug}))
        assert b"example.com/event" in resp.content


@pytest.mark.django_db
class TestRSSFeedFilters:
    def test_multi_category_filter(self, client):
        workshop = EventFactory.create(category="workshop")
        social = EventFactory.create(category="social")
        performance = EventFactory.create(category="performance")
        resp = client.get(
            reverse("event_rss_feed") + "?category=workshop&category=social"
        )
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() in resp.content
        assert str(performance.title).encode() not in resp.content

    def test_publisher_filter(self, client):
        user_a = UserFactory.create()
        user_b = UserFactory.create()
        event_a = EventFactory.create(submitted_by=user_a)
        event_b = EventFactory.create(submitted_by=user_b)
        resp = client.get(
            reverse("event_rss_feed") + f"?publisher={user_a.display_name_slug}"
        )
        assert str(event_a.title).encode() in resp.content
        assert str(event_b.title).encode() not in resp.content

    def test_multi_publisher_filter(self, client):
        user_a = UserFactory.create()
        user_b = UserFactory.create()
        user_c = UserFactory.create()
        event_a = EventFactory.create(submitted_by=user_a)
        event_b = EventFactory.create(submitted_by=user_b)
        event_c = EventFactory.create(submitted_by=user_c)
        url = (
            reverse("event_rss_feed")
            + f"?publisher={user_a.display_name_slug}&publisher={user_b.display_name_slug}"
        )
        resp = client.get(url)
        assert str(event_a.title).encode() in resp.content
        assert str(event_b.title).encode() in resp.content
        assert str(event_c.title).encode() not in resp.content

    def test_publisher_and_category_combined(self, client):
        user = UserFactory.create()
        match = EventFactory.create(submitted_by=user, category="workshop")
        wrong_category = EventFactory.create(submitted_by=user, category="social")
        wrong_publisher = EventFactory.create(category="workshop")
        url = (
            reverse("event_rss_feed")
            + f"?publisher={user.display_name_slug}&category=workshop"
        )
        resp = client.get(url)
        assert str(match.title).encode() in resp.content
        assert str(wrong_category.title).encode() not in resp.content
        assert str(wrong_publisher.title).encode() not in resp.content


@pytest.mark.django_db
class TestICalFeedFilters:
    def test_multi_category_filter(self, client):
        workshop = EventFactory.create(category="workshop")
        social = EventFactory.create(category="social")
        performance = EventFactory.create(category="performance")
        resp = client.get(
            reverse("event_ical_feed") + "?category=workshop&category=social"
        )
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() in resp.content
        assert str(performance.title).encode() not in resp.content

    def test_publisher_filter(self, client):
        user_a = UserFactory.create()
        user_b = UserFactory.create()
        event_a = EventFactory.create(submitted_by=user_a)
        event_b = EventFactory.create(submitted_by=user_b)
        resp = client.get(
            reverse("event_ical_feed") + f"?publisher={user_a.display_name_slug}"
        )
        assert str(event_a.title).encode() in resp.content
        assert str(event_b.title).encode() not in resp.content

    def test_multi_publisher_filter(self, client):
        user_a = UserFactory.create()
        user_b = UserFactory.create()
        user_c = UserFactory.create()
        event_a = EventFactory.create(submitted_by=user_a)
        event_b = EventFactory.create(submitted_by=user_b)
        event_c = EventFactory.create(submitted_by=user_c)
        url = (
            reverse("event_ical_feed")
            + f"?publisher={user_a.display_name_slug}&publisher={user_b.display_name_slug}"
        )
        resp = client.get(url)
        assert str(event_a.title).encode() in resp.content
        assert str(event_b.title).encode() in resp.content
        assert str(event_c.title).encode() not in resp.content

    def test_publisher_and_category_combined(self, client):
        user = UserFactory.create()
        match = EventFactory.create(submitted_by=user, category="workshop")
        wrong_category = EventFactory.create(submitted_by=user, category="social")
        wrong_publisher = EventFactory.create(category="workshop")
        url = (
            reverse("event_ical_feed")
            + f"?publisher={user.display_name_slug}&category=workshop"
        )
        resp = client.get(url)
        assert str(match.title).encode() in resp.content
        assert str(wrong_category.title).encode() not in resp.content
        assert str(wrong_publisher.title).encode() not in resp.content


@pytest.mark.django_db
class TestSubscribeView:
    def test_returns_200(self, client):
        resp = client.get(reverse("subscribe"))
        assert resp.status_code == 200

    def test_provides_category_choices(self, client):
        resp = client.get(reverse("subscribe"))
        assert resp.context["category_choices"] == EventCategory.choices
        assert len(resp.context["category_choices"]) == 7

    def test_provides_publishers_with_upcoming_events(self, client):
        user_a = UserFactory.create()
        user_b = UserFactory.create()
        EventFactory.create(submitted_by=user_a)
        EventFactory.create(submitted_by=user_b)
        resp = client.get(reverse("subscribe"))
        slugs = [p.display_name_slug for p in resp.context["publishers"]]
        assert user_a.display_name_slug in slugs
        assert user_b.display_name_slug in slugs

    def test_includes_system_accounts_in_publishers(self, client):
        system_user = UserFactory.create(is_system_account=True)
        EventFactory.create(submitted_by=system_user)
        resp = client.get(reverse("subscribe"))
        slugs = [p.display_name_slug for p in resp.context["publishers"]]
        assert system_user.display_name_slug in slugs

    def test_excludes_users_with_no_upcoming_events(self, client):
        user = UserFactory.create()
        past = Event(
            title="Past",
            start_datetime=timezone.now() - timezone.timedelta(days=1),
            venue_name="Somewhere",
            category="social",
            submitted_by=user,
        )
        past.save()
        resp = client.get(reverse("subscribe"))
        slugs = [p.display_name_slug for p in resp.context["publishers"]]
        assert user.display_name_slug not in slugs
