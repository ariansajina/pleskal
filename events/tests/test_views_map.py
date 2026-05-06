"""Tests for the /map/ event discovery view."""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.tests.factories import EventFactory


def _with_coords(**kwargs):
    kwargs.setdefault("latitude", 55.6761)
    kwargs.setdefault("longitude", 12.5683)
    return EventFactory.create(**kwargs)


def _without_coords(**kwargs):
    kwargs.setdefault("latitude", None)
    kwargs.setdefault("longitude", None)
    return EventFactory.create(**kwargs)


def _pin_slugs(response):
    return {
        event["slug"]
        for group in response.context["pin_data"]
        for event in group["events"]
    }


@pytest.mark.django_db
class TestEventMapView:
    def test_page_loads(self, client):
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.content

    def test_htmx_request_returns_partial(self, client):
        resp = client.get(reverse("event_map"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" not in resp.content

    def test_event_with_coords_appears_as_pin(self, client):
        event = _with_coords(title="Map-enabled Show")
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 200
        groups = resp.context["pin_data"]
        assert len(groups) == 1
        assert groups[0]["lat"] == pytest.approx(55.6761)
        assert groups[0]["lng"] == pytest.approx(12.5683)
        events = groups[0]["events"]
        assert len(events) == 1
        assert events[0]["slug"] == event.slug
        assert events[0]["title"] == event.title
        assert events[0]["url"] == reverse("event_detail", args=[event.slug])

    def test_events_at_same_location_share_one_pin(self, client):
        a = _with_coords(title="Show A", venue_name="Dansehallerne")
        b = _with_coords(title="Show B", venue_name="Dansehallerne")
        c = _with_coords(
            title="Show C",
            venue_name="Other Venue",
            latitude=55.7000,
            longitude=12.6000,
        )
        resp = client.get(reverse("event_map"))
        groups = resp.context["pin_data"]
        assert len(groups) == 2

        by_venue = {g["venue_name"]: g for g in groups}
        shared = by_venue["Dansehallerne"]
        assert {e["slug"] for e in shared["events"]} == {a.slug, b.slug}
        solo = by_venue["Other Venue"]
        assert {e["slug"] for e in solo["events"]} == {c.slug}

    def test_events_within_one_metre_collapse_to_one_pin(self, client):
        # 6th-decimal differences (~10cm) should not split a pin.
        a = _with_coords(title="A", latitude=55.676100, longitude=12.568300)
        b = _with_coords(title="B", latitude=55.676101, longitude=12.568301)
        resp = client.get(reverse("event_map"))
        groups = resp.context["pin_data"]
        assert len(groups) == 1
        assert {e["slug"] for e in groups[0]["events"]} == {a.slug, b.slug}

    def test_event_without_coords_goes_to_fallback_section(self, client):
        mapped = _with_coords(title="On The Map")
        unmapped = _without_coords(title="Missing Coords")
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 200
        pin_slugs = _pin_slugs(resp)
        assert mapped.slug in pin_slugs
        assert unmapped.slug not in pin_slugs
        fallback_slugs = {e.slug for e in resp.context["events_without_coords"]}
        assert unmapped.slug in fallback_slugs
        assert b"No map location" in resp.content

    def test_draft_events_hidden(self, client):
        owner = UserFactory.create()
        draft = _with_coords(title="Secret Draft", submitted_by=owner, is_draft=True)
        published = _with_coords(title="Published Show")
        client.force_login(owner)
        resp = client.get(reverse("event_map"))
        pin_slugs = _pin_slugs(resp)
        assert draft.slug not in pin_slugs
        assert published.slug in pin_slugs
        fallback_slugs = {e.slug for e in resp.context["events_without_coords"]}
        assert draft.slug not in fallback_slugs

    def test_past_events_hidden(self, client):
        from events.models import Event as EventModel

        past = EventModel(
            title="Old Mapped Show",
            start_datetime=timezone.now() - timezone.timedelta(days=5),
            venue_name="Venue",
            category="social",
            latitude=55.6761,
            longitude=12.5683,
        )
        past.save()
        upcoming = _with_coords(title="Upcoming Show")
        resp = client.get(reverse("event_map"))
        pin_slugs = _pin_slugs(resp)
        assert past.slug not in pin_slugs
        assert upcoming.slug in pin_slugs
        fallback_slugs = {e.slug for e in resp.context["events_without_coords"]}
        assert past.slug not in fallback_slugs

    def test_category_filter_respected(self, client):
        match = _with_coords(title="Workshop Pin", category="workshop")
        miss = _with_coords(title="Social Pin", category="social")
        resp = client.get(reverse("event_map") + "?category=workshop")
        pin_slugs = _pin_slugs(resp)
        assert match.slug in pin_slugs
        assert miss.slug not in pin_slugs

    def test_free_filter_respected(self, client):
        free = _with_coords(title="Free Event", is_free=True)
        paid = _with_coords(title="Paid Event", is_free=False)
        resp = client.get(reverse("event_map") + "?is_free=1")
        pin_slugs = _pin_slugs(resp)
        assert free.slug in pin_slugs
        assert paid.slug not in pin_slugs

    def test_wheelchair_filter_respected(self, client):
        accessible = _with_coords(
            title="Accessible Event", is_wheelchair_accessible=True
        )
        not_accessible = _with_coords(
            title="Inaccessible Event", is_wheelchair_accessible=False
        )
        resp = client.get(reverse("event_map") + "?is_wheelchair_accessible=1")
        pin_slugs = _pin_slugs(resp)
        assert accessible.slug in pin_slugs
        assert not_accessible.slug not in pin_slugs

    def test_search_filter_respected(self, client):
        match = _with_coords(title="Flamenco Night")
        miss = _with_coords(title="Tango Evening")
        resp = client.get(reverse("event_map") + "?q=flamenco")
        pin_slugs = _pin_slugs(resp)
        assert match.slug in pin_slugs
        assert miss.slug not in pin_slugs

    def test_date_range_filter_respected(self, client):
        near = _with_coords(
            title="Near Future",
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        far = _with_coords(
            title="Far Future",
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        date_to = (timezone.now() + timezone.timedelta(days=10)).strftime("%Y-%m-%d")
        resp = client.get(reverse("event_map") + f"?date_to={date_to}")
        pin_slugs = _pin_slugs(resp)
        assert near.slug in pin_slugs
        assert far.slug not in pin_slugs

    def test_publisher_filter_respected(self, client):
        system_user = UserFactory.create(
            is_system_account=True, display_name="Dansehallerne"
        )
        system_event = _with_coords(submitted_by=system_user, title="System Event")
        other_event = _with_coords(title="Other Event")
        resp = client.get(
            reverse("event_map") + f"?publisher={system_user.display_name_slug}"
        )
        pin_slugs = _pin_slugs(resp)
        assert system_event.slug in pin_slugs
        assert other_event.slug not in pin_slugs

    def test_rate_limit_applied(self, client):
        from config.ratelimit import check_rate_limit
        from events.views import EventMapView

        limit = EventMapView.rate_limit_limit
        window = EventMapView.rate_limit_window
        key = "rl:event_map:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.get(reverse("event_map"))
        assert resp.status_code == 429

    def test_leaflet_assets_referenced(self, client):
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "vendor/leaflet/leaflet.css" in content
        assert "vendor/leaflet/leaflet.js" in content

    def test_nav_link_rendered(self, client):
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert reverse("event_map") in content


@pytest.mark.django_db
class TestMapViewFeatureFlag:
    def test_view_returns_404_when_disabled(self, client, settings):
        settings.MAP_VIEW_ENABLED = False
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 404

    def test_view_returns_200_when_enabled(self, client, settings):
        settings.MAP_VIEW_ENABLED = True
        resp = client.get(reverse("event_map"))
        assert resp.status_code == 200

    def test_nav_link_hidden_when_disabled(self, client, settings):
        settings.MAP_VIEW_ENABLED = False
        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        # Nav link should not appear; we look for the map URL on the list page.
        assert reverse("event_map").encode() not in resp.content

    def test_htmx_partial_also_404s_when_disabled(self, client, settings):
        settings.MAP_VIEW_ENABLED = False
        resp = client.get(reverse("event_map"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 404
