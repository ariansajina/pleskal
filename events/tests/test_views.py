"""Tests for event views: submission (F6), listing (F8), detail (F9), management (F10)."""  # noqa: E501

import io

import pytest
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.tests.factories import UserFactory
from events.models import Event, EventStatus
from events.tests.factories import EventFactory


def _make_image_upload(width=100, height=100, fmt="JPEG", name="test.jpg"):
    """Return a Django-compatible SimpleUploadedFile with image data."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(buf, format=fmt)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


def _future_dt(days=7):
    return timezone.now() + timezone.timedelta(days=days)


# ---------------------------------------------------------------------------
# Feature 6: Event submission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventCreateView:
    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse("event_create")
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]

    def test_authenticated_can_see_form(self, client):
        user = UserFactory.create()
        client.force_login(user)
        resp = client.get(reverse("event_create"))
        assert resp.status_code == 200
        assert b"Submit" in resp.content

    def test_unapproved_user_event_is_pending(self, client):
        user = UserFactory.create(is_approved=False)
        client.force_login(user)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Great Dance Night",
                "start_datetime": (_future_dt(7)).strftime("%Y-%m-%dT%H:%M"),
                "venue_name": "Dance Hall",
                "category": "social",
                "is_free": True,
            },
        )
        assert resp.status_code == 302
        event = Event.objects.get(title="Great Dance Night")
        assert event.status == EventStatus.PENDING
        assert event.submitted_by == user

    def test_approved_user_event_is_auto_approved(self, client):
        user = UserFactory.create(is_approved=True)
        client.force_login(user)
        client.post(
            reverse("event_create"),
            {
                "title": "Auto Approved Jam",
                "start_datetime": (_future_dt(5)).strftime("%Y-%m-%dT%H:%M"),
                "venue_name": "Studio A",
                "category": "workshop",
                "is_free": False,
            },
        )
        event = Event.objects.get(title="Auto Approved Jam")
        assert event.status == EventStatus.APPROVED

    def test_past_start_datetime_rejected(self, client):
        user = UserFactory.create()
        client.force_login(user)
        past = timezone.now() - timezone.timedelta(days=1)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Past Event",
                "start_datetime": past.strftime("%Y-%m-%dT%H:%M"),
                "venue_name": "Nowhere",
                "category": "other",
            },
        )
        assert resp.status_code == 200  # form re-rendered
        assert not Event.objects.filter(title="Past Event").exists()

    def test_valid_image_accepted(self, client):
        user = UserFactory.create()
        client.force_login(user)
        img = _make_image_upload()
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Event With Image",
                "start_datetime": (_future_dt(3)).strftime("%Y-%m-%dT%H:%M"),
                "venue_name": "Gallery",
                "category": "performance",
                "is_free": True,
                "image": img,
            },
        )
        assert resp.status_code == 302
        event = Event.objects.get(title="Event With Image")
        assert event.image  # saved
        assert event.image_thumbnail  # thumbnail generated

    def test_end_before_start_rejected(self, client):
        user = UserFactory.create()
        client.force_login(user)
        start = _future_dt(7)
        end = _future_dt(3)  # before start
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Bad Dates",
                "start_datetime": start.strftime("%Y-%m-%dT%H:%M"),
                "end_datetime": end.strftime("%Y-%m-%dT%H:%M"),
                "venue_name": "Somewhere",
                "category": "social",
            },
        )
        assert resp.status_code == 200
        assert not Event.objects.filter(title="Bad Dates").exists()


# ---------------------------------------------------------------------------
# Feature 8: Public event listings
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventListView:
    def test_only_approved_events_shown(self, client):
        approved = EventFactory.create(status=EventStatus.APPROVED)
        pending = EventFactory.create(status=EventStatus.PENDING)
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        assert str(approved.title).encode() in resp.content
        assert str(pending.title).encode() not in resp.content

    def test_category_filter(self, client):
        e1 = EventFactory.create(status=EventStatus.APPROVED, category="workshop")
        e2 = EventFactory.create(status=EventStatus.APPROVED, category="social")
        resp = client.get(reverse("event_list") + "?category=workshop")
        assert str(e1.title).encode() in resp.content
        assert str(e2.title).encode() not in resp.content

    def test_free_events_filter(self, client):
        free = EventFactory.create(status=EventStatus.APPROVED, is_free=True)
        paid = EventFactory.create(status=EventStatus.APPROVED, is_free=False)
        resp = client.get(reverse("event_list") + "?is_free=1")
        assert str(free.title).encode() in resp.content
        assert str(paid.title).encode() not in resp.content

    def test_upcoming_default(self, client):
        upcoming = EventFactory.create(
            status=EventStatus.APPROVED,
            start_datetime=timezone.now() + timezone.timedelta(days=3),
        )
        resp = client.get(reverse("event_list"))
        assert str(upcoming.title).encode() in resp.content

    def test_past_toggle(self, client):
        """past=1 shows events with start_datetime in the past."""
        # Bypass model clean() by saving directly with past date
        from events.models import Event as EventModel

        e = EventModel(
            title="Old Dance Night",
            start_datetime=timezone.now() - timezone.timedelta(days=10),
            venue_name="Old Hall",
            category="social",
            status=EventStatus.APPROVED,
        )
        e.save()
        resp = client.get(reverse("event_list") + "?past=1")
        assert b"Old Dance Night" in resp.content

    def test_htmx_request_returns_partial(self, client):
        EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_list"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        # Partial should not contain the full <html> tag
        assert b"<!DOCTYPE html>" not in resp.content

    def test_non_htmx_returns_full_page(self, client):
        EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.content

    def test_date_from_filter(self, client):
        near = EventFactory.create(
            status=EventStatus.APPROVED,
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        far = EventFactory.create(
            status=EventStatus.APPROVED,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        date_from = (timezone.now() + timezone.timedelta(days=20)).strftime("%Y-%m-%d")
        resp = client.get(reverse("event_list") + f"?date_from={date_from}")
        assert str(far.title).encode() in resp.content
        assert str(near.title).encode() not in resp.content

    def test_date_to_filter(self, client):
        near = EventFactory.create(
            status=EventStatus.APPROVED,
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        far = EventFactory.create(
            status=EventStatus.APPROVED,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        date_to = (timezone.now() + timezone.timedelta(days=10)).strftime("%Y-%m-%d")
        resp = client.get(reverse("event_list") + f"?date_to={date_to}")
        assert str(near.title).encode() in resp.content
        assert str(far.title).encode() not in resp.content

    def test_search_matches_title(self, client):
        match = EventFactory(status=EventStatus.APPROVED, title="Tango Evening Special")
        no_match = EventFactory(status=EventStatus.APPROVED, title="Ballet Workshop")
        resp = client.get(reverse("event_list") + "?q=Tango")
        assert match.title.encode() in resp.content
        assert no_match.title.encode() not in resp.content

    def test_search_matches_venue(self, client):
        match = EventFactory(
            status=EventStatus.APPROVED, venue_name="Vega Concert Hall"
        )
        no_match = EventFactory(
            status=EventStatus.APPROVED, venue_name="City Dance Studio"
        )
        resp = client.get(reverse("event_list") + "?q=Vega")
        assert match.title.encode() in resp.content
        assert no_match.title.encode() not in resp.content

    def test_search_matches_description(self, client):
        match = EventFactory(
            status=EventStatus.APPROVED,
            description="An evening of flamenco dance.",
        )
        no_match = EventFactory(
            status=EventStatus.APPROVED,
            description="Hip-hop jam session.",
        )
        resp = client.get(reverse("event_list") + "?q=flamenco")
        assert match.title.encode() in resp.content
        assert no_match.title.encode() not in resp.content

    def test_empty_search_returns_all_approved(self, client):
        e1 = EventFactory(status=EventStatus.APPROVED)
        e2 = EventFactory(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_list") + "?q=")
        assert e1.title.encode() in resp.content
        assert e2.title.encode() in resp.content

    def test_search_does_not_return_unapproved(self, client):
        pending = EventFactory(status=EventStatus.PENDING, title="Unique Salsa Night")
        resp = client.get(reverse("event_list") + "?q=Salsa")
        assert pending.title.encode() not in resp.content

    def test_search_fuzzy_typo_in_title(self, client):
        match = EventFactory(status=EventStatus.APPROVED, title="Tango Evening")
        resp = client.get(reverse("event_list") + "?q=Tnago")
        assert match.title.encode() in resp.content


# ---------------------------------------------------------------------------
# Feature 9: Event detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventDetailView:
    def test_approved_event_accessible_by_anyone(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200
        assert str(event.title).encode() in resp.content

    def test_pending_event_visible_to_owner(self, client):
        user = UserFactory.create()
        event = EventFactory.create(status=EventStatus.PENDING, submitted_by=user)
        client.force_login(user)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_pending_event_not_visible_to_others(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(status=EventStatus.PENDING, submitted_by=owner)
        client.force_login(other)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 404

    def test_pending_event_not_visible_to_anonymous(self, client):
        event = EventFactory.create(status=EventStatus.PENDING)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 404

    def test_rejected_event_visible_to_owner_with_note(self, client):
        user = UserFactory.create()
        event = EventFactory.create(
            status=EventStatus.REJECTED,
            submitted_by=user,
            rejection_note="Too vague",
        )
        client.force_login(user)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200
        assert b"Too vague" in resp.content

    def test_nonexistent_slug_returns_404(self, client):
        resp = client.get(reverse("event_detail", kwargs={"slug": "does-not-exist"}))
        assert resp.status_code == 404

    def test_moderator_can_see_pending(self, client):
        mod = UserFactory.create(is_moderator=True)
        event = EventFactory.create(status=EventStatus.PENDING)
        client.force_login(mod)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Feature 10: Event management (edit, delete, my-events)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMyEventsView:
    def test_unauthenticated_redirects(self, client):
        resp = client.get(reverse("my_events"))
        assert resp.status_code == 302

    def test_owner_sees_their_events(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        other = EventFactory.create()
        client.force_login(user)
        resp = client.get(reverse("my_events"))
        assert resp.status_code == 200
        assert str(event.title).encode() in resp.content
        assert str(other.title).encode() not in resp.content


@pytest.mark.django_db
class TestEventUpdateView:
    def test_unauthenticated_redirects(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 302

    def test_owner_can_edit(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, status=EventStatus.APPROVED)
        client.force_login(user)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_non_owner_gets_403(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(submitted_by=owner, status=EventStatus.APPROVED)
        client.force_login(other)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 403

    def test_moderator_can_edit_any_event(self, client):
        mod = UserFactory.create(is_moderator=True)
        event = EventFactory.create(status=EventStatus.APPROVED)
        client.force_login(mod)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_editing_rejected_event_resets_to_pending(self, client):
        user = UserFactory.create()
        event = EventFactory.create(
            submitted_by=user,
            status=EventStatus.REJECTED,
            rejection_note="Not detailed enough",
        )
        client.force_login(user)
        client.post(
            reverse("event_edit", kwargs={"slug": event.slug}),
            {
                "title": event.title,
                "start_datetime": event.start_datetime.strftime("%Y-%m-%dT%H:%M"),  # type: ignore[union-attr]
                "venue_name": event.venue_name,
                "category": event.category,
                "is_free": event.is_free,
            },
        )
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING
        assert event.rejection_note == ""

    def test_editing_does_not_change_slug(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, status=EventStatus.APPROVED)
        original_slug = event.slug
        client.force_login(user)
        client.post(
            reverse("event_edit", kwargs={"slug": event.slug}),
            {
                "title": "Completely Different Title",
                "start_datetime": event.start_datetime.strftime("%Y-%m-%dT%H:%M"),  # type: ignore[union-attr]
                "venue_name": event.venue_name,
                "category": event.category,
                "is_free": event.is_free,
            },
        )
        event.refresh_from_db()
        assert event.slug == original_slug


@pytest.mark.django_db
class TestEventDeleteView:
    def test_unauthenticated_redirects(self, client):
        event = EventFactory.create(status=EventStatus.APPROVED)
        resp = client.post(reverse("event_delete", kwargs={"slug": event.slug}))
        assert resp.status_code == 302
        assert Event.objects.filter(pk=event.pk).exists()

    def test_owner_can_delete(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)
        resp = client.post(reverse("event_delete", kwargs={"slug": event.slug}))
        assert resp.status_code == 302
        assert not Event.objects.filter(pk=event.pk).exists()

    def test_non_owner_gets_403(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(submitted_by=owner)
        client.force_login(other)
        resp = client.post(reverse("event_delete", kwargs={"slug": event.slug}))
        assert resp.status_code == 403
        assert Event.objects.filter(pk=event.pk).exists()

    def test_moderator_can_delete_any(self, client):
        mod = UserFactory.create(is_moderator=True)
        event = EventFactory.create()
        client.force_login(mod)
        resp = client.post(reverse("event_delete", kwargs={"slug": event.slug}))
        assert resp.status_code == 302
        assert not Event.objects.filter(pk=event.pk).exists()
