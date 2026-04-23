"""Tests for the venue index, detail page, and canonicalization helpers."""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.models import Event
from events.tests.factories import EventFactory
from events.venues import (
    canonical_name,
    canonical_slug,
    events_for_venue,
    find_venue,
    list_venues,
)


def _past_event(**kwargs):
    """Create an event with a past start_datetime (bypassing clean())."""
    defaults = {
        "title": kwargs.pop("title", "Past Event"),
        "venue_name": kwargs.pop("venue_name", "Past Hall"),
        "category": kwargs.pop("category", "social"),
        "start_datetime": timezone.now() - timezone.timedelta(days=5),
    }
    defaults.update(kwargs)
    e = Event(**defaults)
    e.save()
    return e


class TestCanonicalName:
    def test_trims_whitespace(self):
        assert canonical_name("  Dansehallerne  ") == "dansehallerne"

    def test_casefolds(self):
        assert canonical_name("DANSEHALLERNE") == "dansehallerne"
        assert canonical_name("Dansehallerne") == "dansehallerne"

    def test_collapses_internal_whitespace(self):
        assert canonical_name("Dance  \t  Hall") == "dance hall"

    def test_unicode_normalization(self):
        # NFKC normalizes compatibility characters (e.g. full-width -> ASCII).
        assert canonical_name("Café") == canonical_name("Café")

    def test_empty_string(self):
        assert canonical_name("") == ""


class TestCanonicalSlug:
    def test_produces_slug_with_suffix(self):
        slug = canonical_slug("Dansehallerne")
        assert slug.startswith("dansehallerne-")

    def test_stable_across_calls(self):
        assert canonical_slug("Dansehallerne") == canonical_slug("Dansehallerne")

    def test_same_for_variants_of_same_canonical_name(self):
        # Whitespace, case, unicode variants must all share one slug.
        assert canonical_slug("Dansehallerne") == canonical_slug(" dansehallerne ")
        assert canonical_slug("Dansehallerne") == canonical_slug("DANSEHALLERNE")
        assert canonical_slug("Dance  Hall") == canonical_slug(" dance hall ")

    def test_different_names_get_different_slugs(self):
        assert canonical_slug("Dansehallerne") != canonical_slug("HAUT Scene")

    def test_empty_name_still_produces_slug(self):
        # Fallback prefix keeps URL routable rather than erroring.
        slug = canonical_slug("")
        assert slug.startswith("venue-")

    def test_slug_only_contains_url_safe_chars(self):
        import string

        allowed = set(string.ascii_lowercase + string.digits + "-")
        for name in [
            "Dansehallerne",
            "Café Étoile",
            "a weird   name!!! with *** symbols",
            "",
        ]:
            slug = canonical_slug(name)
            assert set(slug) <= allowed, f"bad slug for {name!r}: {slug}"


@pytest.mark.django_db
class TestListVenues:
    def test_groups_by_canonical_name(self):
        EventFactory.create(venue_name="Dansehallerne")
        EventFactory.create(venue_name="dansehallerne")
        EventFactory.create(venue_name="DANSEHALLERNE ")

        venues = list_venues()
        assert len(venues) == 1
        assert venues[0].count == 3

    def test_excludes_venues_with_no_upcoming_events(self):
        _past_event(venue_name="Ghost Hall")
        EventFactory.create(venue_name="Live Hall")

        slugs = [v.display_name for v in list_venues()]
        assert "Ghost Hall" not in slugs
        assert "Live Hall" in slugs

    def test_excludes_draft_events(self):
        EventFactory.create(venue_name="Public Hall")
        EventFactory.create(venue_name="Drafts Only", is_draft=True)

        slugs = [v.display_name for v in list_venues()]
        assert "Public Hall" in slugs
        assert "Drafts Only" not in slugs

    def test_sorted_alphabetically_case_insensitive(self):
        EventFactory.create(venue_name="banana")
        EventFactory.create(venue_name="Apple")
        EventFactory.create(venue_name="cherry")

        names = [v.display_name for v in list_venues()]
        assert names == sorted(names, key=str.casefold)

    def test_display_name_is_most_common_spelling(self):
        # Three "Dansehallerne" vs one "dansehallerne" — majority wins.
        EventFactory.create_batch(3, venue_name="Dansehallerne")
        EventFactory.create(venue_name="dansehallerne")

        venues = list_venues()
        assert len(venues) == 1
        assert venues[0].display_name == "Dansehallerne"
        assert venues[0].count == 4


@pytest.mark.django_db
class TestFindVenue:
    def test_returns_none_for_unknown_slug(self):
        assert find_venue("no-such-venue") is None

    def test_finds_by_canonical_slug(self):
        event = EventFactory.create(venue_name="Dansehallerne")
        slug = canonical_slug(str(event.venue_name))

        venue = find_venue(slug)
        assert venue is not None
        assert venue.display_name == "Dansehallerne"

    def test_collects_addresses_across_group(self):
        EventFactory.create(
            venue_name="Dansehallerne", venue_address="Pasteursvej 20"
        )
        EventFactory.create(
            venue_name="dansehallerne", venue_address="Pasteursvej 20, Copenhagen"
        )

        slug = canonical_slug("Dansehallerne")
        venue = find_venue(slug)
        assert venue is not None
        assert "Pasteursvej 20" in venue.addresses
        assert "Pasteursvej 20, Copenhagen" in venue.addresses

    def test_finds_venue_even_when_only_past_events_exist(self):
        _past_event(venue_name="Retired Hall")

        slug = canonical_slug("Retired Hall")
        venue = find_venue(slug)
        assert venue is not None
        assert venue.display_name == "Retired Hall"


@pytest.mark.django_db
class TestEventsForVenue:
    def test_returns_events_matching_canonical(self):
        match_a = EventFactory.create(venue_name="Dansehallerne")
        match_b = EventFactory.create(venue_name="dansehallerne")
        other = EventFactory.create(venue_name="HAUT Scene")

        canonical = canonical_name("Dansehallerne")
        ids = set(events_for_venue(canonical).values_list("id", flat=True))
        assert match_a.id in ids
        assert match_b.id in ids
        assert other.id not in ids

    def test_excludes_drafts(self):
        EventFactory.create(venue_name="Public")
        EventFactory.create(venue_name="public", is_draft=True)

        canonical = canonical_name("Public")
        ids = list(events_for_venue(canonical).values_list("id", flat=True))
        assert len(ids) == 1

    def test_excludes_past_by_default(self):
        EventFactory.create(venue_name="Hall")
        _past_event(venue_name="Hall")

        canonical = canonical_name("Hall")
        assert events_for_venue(canonical).count() == 1
        assert events_for_venue(canonical, include_past=True).count() == 2


@pytest.mark.django_db
class TestVenueIndexView:
    def test_returns_200(self, client):
        resp = client.get(reverse("venue_list"))
        assert resp.status_code == 200

    def test_lists_venues_with_upcoming_events(self, client):
        EventFactory.create(venue_name="Dansehallerne")
        EventFactory.create(venue_name="HAUT Scene")

        resp = client.get(reverse("venue_list"))
        assert b"Dansehallerne" in resp.content
        assert b"HAUT Scene" in resp.content

    def test_hides_venues_without_upcoming_events(self, client):
        _past_event(venue_name="Ghost Hall")

        resp = client.get(reverse("venue_list"))
        assert b"Ghost Hall" not in resp.content

    def test_hides_draft_only_venues(self, client):
        EventFactory.create(venue_name="Drafts Only", is_draft=True)

        resp = client.get(reverse("venue_list"))
        assert b"Drafts Only" not in resp.content

    def test_empty_state_when_no_venues(self, client):
        resp = client.get(reverse("venue_list"))
        assert resp.status_code == 200
        assert b"No venues" in resp.content


@pytest.mark.django_db
class TestVenueDetailView:
    def test_returns_200_for_valid_slug(self, client):
        event = EventFactory.create(venue_name="Dansehallerne")
        slug = canonical_slug(str(event.venue_name))

        resp = client.get(reverse("venue_detail", kwargs={"slug": slug}))
        assert resp.status_code == 200

    def test_returns_404_for_unknown_slug(self, client):
        resp = client.get(reverse("venue_detail", kwargs={"slug": "no-such-place"}))
        assert resp.status_code == 404

    def test_lists_events_at_venue(self, client):
        here = EventFactory.create(
            title="Tango at Dansehallerne", venue_name="Dansehallerne"
        )
        elsewhere = EventFactory.create(
            title="Salsa at HAUT Scene", venue_name="HAUT Scene"
        )
        slug = canonical_slug(str(here.venue_name))

        resp = client.get(reverse("venue_detail", kwargs={"slug": slug}))
        assert str(here.title).encode() in resp.content
        assert str(elsewhere.title).encode() not in resp.content

    def test_groups_events_across_canonical_variants(self, client):
        upper = EventFactory.create(title="Upper Event", venue_name="Dansehallerne")
        lower = EventFactory.create(title="Lower Event", venue_name="dansehallerne")

        slug = canonical_slug("Dansehallerne")
        resp = client.get(reverse("venue_detail", kwargs={"slug": slug}))
        assert b"Upper Event" in resp.content
        assert b"Lower Event" in resp.content
        _ = upper, lower  # silence factoryboy lint

    def test_excludes_draft_events(self, client):
        live = EventFactory.create(title="Live", venue_name="Dansehallerne")
        draft = EventFactory.create(
            title="SecretDraft", venue_name="Dansehallerne", is_draft=True
        )
        slug = canonical_slug(str(live.venue_name))

        resp = client.get(reverse("venue_detail", kwargs={"slug": slug}))
        assert b"Live" in resp.content
        assert b"SecretDraft" not in resp.content
        _ = draft

    def test_category_filter_applies(self, client):
        workshop = EventFactory.create(
            title="Workshop Night", venue_name="Dansehallerne", category="workshop"
        )
        social = EventFactory.create(
            title="Social Night", venue_name="Dansehallerne", category="social"
        )
        slug = canonical_slug("Dansehallerne")

        resp = client.get(
            reverse("venue_detail", kwargs={"slug": slug}) + "?category=workshop"
        )
        assert str(workshop.title).encode() in resp.content
        assert str(social.title).encode() not in resp.content

    def test_htmx_returns_partial(self, client):
        EventFactory.create(venue_name="Dansehallerne")
        slug = canonical_slug("Dansehallerne")

        resp = client.get(
            reverse("venue_detail", kwargs={"slug": slug}),
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        # Partial does not include the <html>/<body> shell.
        assert b"<html" not in resp.content

    def test_renders_address_from_event_data(self, client):
        EventFactory.create(
            venue_name="Dansehallerne", venue_address="Pasteursvej 20"
        )
        slug = canonical_slug("Dansehallerne")

        resp = client.get(reverse("venue_detail", kwargs={"slug": slug}))
        assert b"Pasteursvej 20" in resp.content


@pytest.mark.django_db
class TestEventDetailVenueLink:
    """Venue name on the event detail page should link to the venue page."""

    def test_venue_name_links_to_venue_page(self, client):
        event = EventFactory.create(venue_name="Dansehallerne")
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))

        slug = canonical_slug(str(event.venue_name))
        expected_href = reverse("venue_detail", kwargs={"slug": slug})
        assert expected_href.encode() in resp.content


@pytest.mark.django_db
class TestRateLimitParity:
    """Venue views share the event-list rate limit bucket."""

    def test_venue_list_uses_event_list_bucket(self):
        from events.views import EventListView, VenueIndexView

        assert VenueIndexView.rate_limit_key == EventListView.rate_limit_key
        assert VenueIndexView.rate_limit_limit == EventListView.rate_limit_limit
        assert VenueIndexView.rate_limit_window == EventListView.rate_limit_window

    def test_venue_detail_uses_event_list_bucket(self):
        from events.views import EventListView, VenueDetailView

        assert VenueDetailView.rate_limit_key == EventListView.rate_limit_key
        assert VenueDetailView.rate_limit_limit == EventListView.rate_limit_limit
        assert VenueDetailView.rate_limit_window == EventListView.rate_limit_window


@pytest.mark.django_db
class TestPublisherIsStillRespected:
    """Regression: publisher filter still works from the venue detail page."""

    def test_publisher_filter_on_venue_detail(self, client):
        user_a = UserFactory.create(is_system_account=True)
        user_b = UserFactory.create(is_system_account=True)

        mine = EventFactory.create(
            title="Event By A", venue_name="Dansehallerne", submitted_by=user_a
        )
        theirs = EventFactory.create(
            title="Event By B", venue_name="Dansehallerne", submitted_by=user_b
        )
        slug = canonical_slug("Dansehallerne")

        resp = client.get(
            reverse("venue_detail", kwargs={"slug": slug})
            + f"?publisher={user_a.display_name_slug}"
        )
        assert str(mine.title).encode() in resp.content
        assert str(theirs.title).encode() not in resp.content
