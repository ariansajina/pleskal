"""Tests for event views."""

import io

import pytest
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.tests.factories import UserFactory
from events.models import Event
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

    def test_event_submission_creates_event(self, client):
        user = UserFactory.create()
        client.force_login(user)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Great Dance Night",
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": _future_dt(7).strftime("%H:%M"),
                "venue_name": "Dance Hall",
                "category": "social",
                "is_free": True,
            },
        )
        assert resp.status_code == 302
        event = Event.objects.get(title="Great Dance Night")
        assert event.submitted_by == user

    def test_past_start_datetime_rejected(self, client):
        user = UserFactory.create()
        client.force_login(user)
        past = timezone.now() - timezone.timedelta(days=1)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Past Event",
                "date": past.strftime("%Y-%m-%d"),
                "start_time": past.strftime("%H:%M"),
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
                "date": _future_dt(3).strftime("%Y-%m-%d"),
                "start_time": _future_dt(3).strftime("%H:%M"),
                "venue_name": "Gallery",
                "category": "performance",
                "is_free": True,
                "image": img,
            },
        )
        assert resp.status_code == 302
        event = Event.objects.get(title="Event With Image")
        assert event.image  # saved

    def test_image_url_rendered_on_detail_page(self, client, settings, tmp_path):
        """Uploaded event images must appear in the detail page HTML."""
        settings.MEDIA_ROOT = tmp_path
        user = UserFactory.create()
        client.force_login(user)
        img = _make_image_upload()
        client.post(
            reverse("event_create"),
            {
                "title": "Image URL Test",
                "date": _future_dt(3).strftime("%Y-%m-%d"),
                "start_time": _future_dt(3).strftime("%H:%M"),
                "venue_name": "Gallery",
                "category": "performance",
                "is_free": True,
                "image": img,
            },
        )
        event = Event.objects.get(title="Image URL Test")
        assert event.image
        # The image file must exist on disk — confirms storage saved it correctly.
        assert event.image.storage.exists(event.image.name)

        # The detail page must render the <img> tag with the correct src.
        detail_resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert detail_resp.status_code == 200
        assert event.image.url.encode() in detail_resp.content

    def test_oversized_image_rejected(self, client, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 100  # tiny limit
        user = UserFactory.create()
        client.force_login(user)
        img = _make_image_upload()
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Oversized Image Event",
                "date": _future_dt(3).strftime("%Y-%m-%d"),
                "start_time": _future_dt(3).strftime("%H:%M"),
                "venue_name": "Gallery",
                "category": "performance",
                "is_free": True,
                "image": img,
            },
        )
        assert resp.status_code == 200  # form re-rendered with error
        assert b"10 MB" in resp.content
        assert not Event.objects.filter(title="Oversized Image Event").exists()

    def test_end_before_start_rejected(self, client):
        user = UserFactory.create()
        client.force_login(user)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Bad Dates",
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": "20:00",
                "end_time": "19:00",  # before start_time
                "venue_name": "Somewhere",
                "category": "social",
            },
        )
        assert resp.status_code == 200
        assert not Event.objects.filter(title="Bad Dates").exists()

    def test_past_event_error_message(self, client):
        user = UserFactory.create()
        client.force_login(user)
        past = timezone.now() - timezone.timedelta(days=1)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "Past Event Message",
                "date": past.strftime("%Y-%m-%d"),
                "start_time": past.strftime("%H:%M"),
                "venue_name": "Nowhere",
                "category": "other",
            },
        )
        assert resp.status_code == 200
        assert b"cannot be created in the past" in resp.content

    def test_upcoming_events_limit_blocks_get(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.get(reverse("event_create"))
        assert resp.status_code == 302
        assert resp["Location"].endswith(reverse("my_events"))

    def test_upcoming_events_limit_blocks_post(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.post(
            reverse("event_create"),
            {
                "title": "One Too Many",
                "date": _future_dt(5).strftime("%Y-%m-%d"),
                "start_time": _future_dt(5).strftime("%H:%M"),
                "venue_name": "Club",
                "category": "social",
            },
        )
        assert resp.status_code == 302
        assert not Event.objects.filter(title="One Too Many").exists()

    def test_upcoming_events_limit_message_shown(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.get(reverse("event_create"), follow=True)
        messages_list = list(resp.context["messages"])
        assert any("limit" in str(m).lower() for m in messages_list)

    def test_past_events_not_counted_toward_limit(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        client.force_login(user)
        # Create MAX past events — should NOT trigger the limit
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=timezone.now() - timezone.timedelta(days=1),
        )
        resp = client.get(reverse("event_create"))
        assert resp.status_code == 200

    def test_below_limit_allows_creation(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER - 1,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.get(reverse("event_create"))
        assert resp.status_code == 200


@pytest.mark.django_db
class TestEventListView:
    def test_events_shown(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        assert str(event.title).encode() in resp.content

    def test_category_filter(self, client):
        e1 = EventFactory.create(category="workshop")
        e2 = EventFactory.create(category="social")
        resp = client.get(reverse("event_list") + "?category=workshop")
        assert str(e1.title).encode() in resp.content
        assert str(e2.title).encode() not in resp.content

    def test_free_events_filter(self, client):
        free = EventFactory.create(is_free=True)
        paid = EventFactory.create(is_free=False)
        resp = client.get(reverse("event_list") + "?is_free=1")
        assert str(free.title).encode() in resp.content
        assert str(paid.title).encode() not in resp.content

    def test_upcoming_default(self, client):
        upcoming = EventFactory.create(
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
        )
        e.save()
        resp = client.get(reverse("event_list") + "?past=1")
        assert b"Old Dance Night" in resp.content

    def test_htmx_request_returns_partial(self, client):
        EventFactory.create()
        resp = client.get(reverse("event_list"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        # Partial should not contain the full <html> tag
        assert b"<!DOCTYPE html>" not in resp.content

    def test_non_htmx_returns_full_page(self, client):
        EventFactory.create()
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.content

    def test_date_from_filter(self, client):
        near = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        far = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        date_from = (timezone.now() + timezone.timedelta(days=20)).strftime("%Y-%m-%d")
        resp = client.get(reverse("event_list") + f"?date_from={date_from}")
        assert str(far.title).encode() in resp.content
        assert str(near.title).encode() not in resp.content

    def test_date_to_filter(self, client):
        near = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        far = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        date_to = (timezone.now() + timezone.timedelta(days=10)).strftime("%Y-%m-%d")
        resp = client.get(reverse("event_list") + f"?date_to={date_to}")
        assert str(near.title).encode() in resp.content
        assert str(far.title).encode() not in resp.content

    def test_date_range_overrides_past_toggle(self, client):
        """When a date range is set, past=1 is ignored — all events in the
        range are shown regardless of whether they are upcoming or past."""
        from events.models import Event as EventModel

        past_event = EventModel(
            title="Past Event In Range",
            start_datetime=timezone.now() - timezone.timedelta(days=3),
            end_datetime=None,
            venue_name="Venue",
            category="social",
        )
        past_event.save()
        future_event = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=3),
        )
        date_from = (timezone.now() - timezone.timedelta(days=5)).strftime("%Y-%m-%d")
        date_to = (timezone.now() + timezone.timedelta(days=5)).strftime("%Y-%m-%d")
        # past=0 (upcoming) with a date range that includes past events — past
        # events should still appear because the date range takes priority.
        resp = client.get(
            reverse("event_list") + f"?date_from={date_from}&date_to={date_to}&past=0"
        )
        assert b"Past Event In Range" in resp.content
        assert str(future_event.title).encode() in resp.content

    def test_search_matches_title(self, client):
        match = EventFactory(title="Tango Evening Special")
        no_match = EventFactory(title="Ballet Workshop")
        resp = client.get(reverse("event_list") + "?q=Tango")
        assert str(match.title).encode() in resp.content
        assert str(no_match.title).encode() not in resp.content

    def test_search_matches_venue(self, client):
        match = EventFactory(venue_name="Vega Concert Hall")
        no_match = EventFactory(venue_name="City Dance Studio")
        resp = client.get(reverse("event_list") + "?q=Vega")
        assert str(match.title).encode() in resp.content
        assert str(no_match.title).encode() not in resp.content

    def test_search_matches_description(self, client):
        match = EventFactory(description="An evening of flamenco dance.")
        no_match = EventFactory(description="Hip-hop jam session.")
        resp = client.get(reverse("event_list") + "?q=flamenco")
        assert str(match.title).encode() in resp.content
        assert str(no_match.title).encode() not in resp.content

    def test_search_matches_publisher_display_name(self, client):
        user = UserFactory.create(display_name="DJ Mambo")
        match = EventFactory(submitted_by=user)
        no_match = EventFactory()
        resp = client.get(reverse("event_list") + "?q=mambo")
        assert str(match.title).encode() in resp.content
        assert str(no_match.title).encode() not in resp.content

    def test_empty_search_returns_all(self, client):
        e1 = EventFactory()
        e2 = EventFactory()
        resp = client.get(reverse("event_list") + "?q=")
        assert str(e1.title).encode() in resp.content
        assert str(e2.title).encode() in resp.content


@pytest.mark.django_db
class TestEventDetailView:
    def test_event_accessible_by_anyone(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200
        assert str(event.title).encode() in resp.content

    def test_nonexistent_slug_returns_404(self, client):
        resp = client.get(reverse("event_detail", kwargs={"slug": "does-not-exist"}))
        assert resp.status_code == 404

    def test_context_contains_google_calendar_url(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        from urllib.parse import urlparse

        assert "google_calendar_url" in resp.context
        parsed = urlparse(resp.context["google_calendar_url"])
        assert parsed.netloc == "calendar.google.com"

    def test_google_calendar_url_contains_event_title(self, client):
        event = EventFactory.create(title="Salsa Workshop")
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        url = resp.context["google_calendar_url"]
        assert "Salsa" in url

    def test_google_calendar_url_contains_dates(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert "dates=" in resp.context["google_calendar_url"]

    def test_google_calendar_url_contains_venue(self, client):
        event = EventFactory.create(venue_name="Dansehallerne")
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert "Dansehallerne" in resp.context["google_calendar_url"]

    def test_page_renders_add_to_calendar_link(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert b"Add to calendar" in resp.content

    def test_page_renders_copy_link_button(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert b"copy-link-btn" in resp.content


@pytest.mark.django_db
class TestMyEventsView:
    def test_unauthenticated_redirects(self, client):
        resp = client.get("/my-events/")
        assert resp.status_code == 302

    def test_owner_sees_their_events(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        other = EventFactory.create()
        client.force_login(user)
        resp = client.get(
            reverse("publisher_profile", kwargs={"slug": user.display_name_slug})
        )
        assert resp.status_code == 200
        assert str(event.title).encode() in resp.content
        assert str(other.title).encode() not in resp.content


@pytest.mark.django_db
class TestEventUpdateView:
    def test_unauthenticated_redirects(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 302

    def test_owner_can_edit(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_non_owner_gets_403(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(submitted_by=owner)
        client.force_login(other)
        resp = client.get(reverse("event_edit", kwargs={"slug": event.slug}))
        assert resp.status_code == 403

    def test_editing_does_not_change_slug(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        original_slug = event.slug
        client.force_login(user)
        local_start = timezone.localtime(event.start_datetime)
        client.post(
            reverse("event_edit", kwargs={"slug": event.slug}),
            {
                "title": "Completely Different Title",
                "date": local_start.strftime("%Y-%m-%d"),
                "start_time": local_start.strftime("%H:%M"),
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
        event = EventFactory.create()
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


@pytest.mark.django_db
class TestEventDuplicateView:
    def test_unauthenticated_redirects(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_duplicate", kwargs={"slug": event.slug}))
        assert resp.status_code == 302

    def test_owner_sees_prepopulated_form(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, title="Salsa Night")
        client.force_login(user)
        resp = client.get(reverse("event_duplicate", kwargs={"slug": event.slug}))
        assert resp.status_code == 200
        assert b"Salsa Night" in resp.content
        assert b"Duplicate Event" in resp.content

    def test_non_owner_gets_403(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(submitted_by=owner)
        client.force_login(other)
        resp = client.get(reverse("event_duplicate", kwargs={"slug": event.slug}))
        assert resp.status_code == 403

    def test_submitting_form_creates_new_event(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, title="Tango Night")
        client.force_login(user)
        new_start = _future_dt(days=14)
        resp = client.post(
            reverse("event_duplicate", kwargs={"slug": event.slug}),
            {
                "title": "Tango Night II",
                "date": new_start.strftime("%Y-%m-%d"),
                "start_time": new_start.strftime("%H:%M"),
                "venue_name": event.venue_name,
                "category": event.category,
                "is_free": event.is_free,
            },
        )
        assert resp.status_code == 302
        assert Event.objects.filter(title="Tango Night II").exists()
        assert Event.objects.filter(title="Tango Night").exists()  # original unchanged

    def test_duplicate_blocked_when_at_limit(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        source = EventFactory.create(submitted_by=user)
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.get(reverse("event_duplicate", kwargs={"slug": source.slug}))
        assert resp.status_code == 302
        assert resp["Location"].endswith(reverse("my_events"))

    def test_duplicate_post_blocked_when_at_limit(self, client):
        from events.views import MAX_UPCOMING_EVENTS_PER_USER

        user = UserFactory.create()
        source = EventFactory.create(submitted_by=user, title="Original")
        client.force_login(user)
        EventFactory.create_batch(
            MAX_UPCOMING_EVENTS_PER_USER,
            submitted_by=user,
            start_datetime=_future_dt(10),
        )
        resp = client.post(
            reverse("event_duplicate", kwargs={"slug": source.slug}),
            {
                "title": "Blocked Duplicate",
                "date": _future_dt(5).strftime("%Y-%m-%d"),
                "start_time": _future_dt(5).strftime("%H:%M"),
                "venue_name": "Club",
                "category": "social",
            },
        )
        assert resp.status_code == 302
        assert not Event.objects.filter(title="Blocked Duplicate").exists()


# ---------------------------------------------------------------------------
# Draft tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventDrafts:
    """Tests for the is_draft functionality across views."""

    def _post_create(
        self, client, user, submit_action="publish", title="Draft Test Event"
    ):
        client.force_login(user)
        return client.post(
            reverse("event_create"),
            {
                "title": title,
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": _future_dt(7).strftime("%H:%M"),
                "venue_name": "Test Venue",
                "category": "social",
                "submit_action": submit_action,
            },
        )

    # --- Create ---

    def test_submit_action_publish_creates_published_event(self, client):
        user = UserFactory.create()
        resp = self._post_create(client, user, "publish", "Published Event")
        assert resp.status_code == 302
        event = Event.objects.get(title="Published Event")
        assert not event.is_draft

    def test_submit_action_draft_creates_draft_event(self, client):
        user = UserFactory.create()
        resp = self._post_create(client, user, "draft", "My Draft Event")
        assert resp.status_code == 302
        event = Event.objects.get(title="My Draft Event")
        assert event.is_draft

    def test_default_no_action_creates_published_event(self, client):
        """If submit_action is absent (e.g. JS disabled), event is published."""
        user = UserFactory.create()
        client.force_login(user)
        resp = client.post(
            reverse("event_create"),
            {
                "title": "No Action Event",
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": _future_dt(7).strftime("%H:%M"),
                "venue_name": "Test Venue",
                "category": "social",
            },
        )
        assert resp.status_code == 302
        event = Event.objects.get(title="No Action Event")
        assert not event.is_draft

    # --- Event list ---

    def test_draft_excluded_from_public_event_list(self, client):
        EventFactory.create(title="Public Event", is_draft=False)
        EventFactory.create(title="Hidden Draft", is_draft=True)
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        assert b"Public Event" in resp.content
        assert b"Hidden Draft" not in resp.content

    # --- Detail view ---

    def test_owner_can_view_draft_detail(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, is_draft=True)
        client.force_login(user)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 200

    def test_non_owner_cannot_view_draft_detail(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        event = EventFactory.create(submitted_by=owner, is_draft=True)
        client.force_login(other)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 404

    def test_anonymous_cannot_view_draft_detail(self, client):
        owner = UserFactory.create()
        event = EventFactory.create(submitted_by=owner, is_draft=True)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert resp.status_code == 404

    def test_detail_shows_draft_banner_for_owner(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, is_draft=True)
        client.force_login(user)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert b"only visible to you" in resp.content

    def test_detail_no_draft_banner_for_published_event(self, client):
        event = EventFactory.create(is_draft=False)
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert b"only visible to you" not in resp.content

    # --- Update ---

    def test_owner_can_publish_draft(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, is_draft=True)
        client.force_login(user)
        resp = client.post(
            reverse("event_edit", kwargs={"slug": event.slug}),
            {
                "title": event.title,
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": _future_dt(7).strftime("%H:%M"),
                "venue_name": event.venue_name,
                "category": event.category,
                "submit_action": "publish",
            },
        )
        assert resp.status_code == 302
        event.refresh_from_db()
        assert not event.is_draft

    def test_owner_can_unpublish_event(self, client):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user, is_draft=False)
        client.force_login(user)
        resp = client.post(
            reverse("event_edit", kwargs={"slug": event.slug}),
            {
                "title": event.title,
                "date": _future_dt(7).strftime("%Y-%m-%d"),
                "start_time": _future_dt(7).strftime("%H:%M"),
                "venue_name": event.venue_name,
                "category": event.category,
                "submit_action": "draft",
            },
        )
        assert resp.status_code == 302
        event.refresh_from_db()
        assert event.is_draft

    # --- Publisher profile ---

    def test_drafts_not_shown_on_other_user_profile(self, client):
        owner = UserFactory.create()
        other = UserFactory.create()
        EventFactory.create(submitted_by=owner, is_draft=True, title="Secret Draft")
        client.force_login(other)
        resp = client.get(
            reverse("publisher_profile", kwargs={"slug": owner.display_name_slug})
        )
        assert b"Secret Draft" not in resp.content

    def test_drafts_shown_on_own_profile(self, client):
        user = UserFactory.create()
        EventFactory.create(submitted_by=user, is_draft=True, title="My Draft")
        client.force_login(user)
        resp = client.get(
            reverse("publisher_profile", kwargs={"slug": user.display_name_slug})
        )
        assert b"My Draft" in resp.content

    def test_published_events_not_in_drafts_section_on_own_profile(self, client):
        user = UserFactory.create()
        EventFactory.create(submitted_by=user, is_draft=False, title="Published One")
        EventFactory.create(submitted_by=user, is_draft=True, title="Draft One")
        client.force_login(user)
        resp = client.get(
            reverse("publisher_profile", kwargs={"slug": user.display_name_slug})
        )
        assert b"Published One" in resp.content
        assert b"Draft One" in resp.content
