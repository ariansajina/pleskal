"""Tests for the EventSeries grouping feature."""

import datetime
import json
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from events.models import Event, EventSeries
from events.tests.factories import EventFactory, EventSeriesFactory


def _future_dt(days=7):
    return timezone.now() + timezone.timedelta(days=days)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventSeriesModel:
    def test_slug_is_generated_from_title(self):
        series = EventSeriesFactory.create(title="Contact Improv Weekly")
        assert str(series.slug).startswith("contact-improv-weekly")

    def test_slug_collision_appends_suffix(self):
        first = EventSeriesFactory.create(title="Same Name Series")
        second = EventSeriesFactory.create(title="Same Name Series")
        assert first.slug != second.slug
        assert str(second.slug).startswith("same-name-series-")

    def test_str_returns_title(self):
        series = EventSeriesFactory.build(title="My Series")
        assert str(series) == "My Series"

    def test_deleting_series_sets_event_series_to_null(self):
        series = EventSeriesFactory.create()
        event = EventFactory.create(series=series)
        series.delete()
        event.refresh_from_db()
        assert event.series is None
        assert Event.objects.filter(pk=event.pk).exists()

    def test_get_display_description_no_disclaimer(self, settings):
        settings.SCRAPED_EVENT_DISCLAIMER = ""
        series = EventSeriesFactory.create(
            description="Hello", external_source="dansehallerne"
        )
        assert series.get_display_description() == "Hello"

    def test_get_display_description_with_disclaimer(self, settings):
        settings.SCRAPED_EVENT_DISCLAIMER = "[Scraped]"
        series = EventSeriesFactory.create(
            description="Hello", external_source="dansehallerne"
        )
        assert "[Scraped]" in series.get_display_description()


# ---------------------------------------------------------------------------
# Series CRUD views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventSeriesCreateView:
    def test_unauthenticated_redirects(self, client):
        resp = client.get(reverse("series_create"))
        assert resp.status_code == 302

    def test_authenticated_can_create(self, client):
        user = UserFactory.create()
        client.force_login(user)
        resp = client.post(
            reverse("series_create"),
            {"title": "My Weekly Practice", "description": "Mondays."},
        )
        assert resp.status_code == 302
        series = EventSeries.objects.get(title="My Weekly Practice")
        assert series.submitted_by == user


@pytest.mark.django_db
class TestEventSeriesUpdateView:
    def test_owner_can_edit(self, client):
        user = UserFactory.create()
        series = EventSeriesFactory.create(submitted_by=user, title="Old Title")
        client.force_login(user)
        resp = client.post(
            reverse("series_edit", kwargs={"slug": series.slug}),
            {"title": "New Title", "description": ""},
        )
        assert resp.status_code == 302
        series.refresh_from_db()
        assert series.title == "New Title"

    def test_non_owner_forbidden(self, client):
        owner = UserFactory.create()
        intruder = UserFactory.create()
        series = EventSeriesFactory.create(submitted_by=owner)
        client.force_login(intruder)
        resp = client.post(
            reverse("series_edit", kwargs={"slug": series.slug}),
            {"title": "Hijack", "description": ""},
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestEventSeriesDeleteView:
    def test_owner_can_delete(self, client):
        user = UserFactory.create()
        series = EventSeriesFactory.create(submitted_by=user)
        EventFactory.create(series=series, submitted_by=user)
        client.force_login(user)
        resp = client.post(reverse("series_delete", kwargs={"slug": series.slug}))
        assert resp.status_code == 302
        assert not EventSeries.objects.filter(pk=series.pk).exists()
        # Events themselves remain — only the link is broken.
        assert Event.objects.filter(submitted_by=user).count() == 1

    def test_non_owner_forbidden(self, client):
        owner = UserFactory.create()
        intruder = UserFactory.create()
        series = EventSeriesFactory.create(submitted_by=owner)
        client.force_login(intruder)
        resp = client.post(reverse("series_delete", kwargs={"slug": series.slug}))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Series detail view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventSeriesDetailView:
    def test_visible_when_has_published_events(self, client):
        series = EventSeriesFactory.create()
        EventFactory.create(series=series, is_draft=False)
        resp = client.get(reverse("series_detail", kwargs={"slug": series.slug}))
        assert resp.status_code == 200

    def test_hidden_when_only_draft_events(self, client):
        series = EventSeriesFactory.create()
        EventFactory.create(series=series, is_draft=True)
        resp = client.get(reverse("series_detail", kwargs={"slug": series.slug}))
        assert resp.status_code == 404

    def test_owner_can_see_draft_only_series(self, client):
        owner = UserFactory.create()
        series = EventSeriesFactory.create(submitted_by=owner)
        EventFactory.create(series=series, is_draft=True, submitted_by=owner)
        client.force_login(owner)
        resp = client.get(reverse("series_detail", kwargs={"slug": series.slug}))
        assert resp.status_code == 200

    def test_lists_upcoming_and_past_separately(self, client):
        series = EventSeriesFactory.create()
        upcoming = EventFactory.create(
            series=series, start_datetime=_future_dt(7), title="Future One"
        )
        past = EventFactory.create(
            series=series,
            start_datetime=timezone.now() - timezone.timedelta(days=10),
            title="Past One",
        )
        # past start_datetime needs to bypass clean's future-only check; we use
        # the factory which doesn't run full_clean.
        resp = client.get(reverse("series_detail", kwargs={"slug": series.slug}))
        assert resp.status_code == 200
        assert str(upcoming.title).encode() in resp.content
        assert str(past.title).encode() in resp.content


# ---------------------------------------------------------------------------
# Event list collapse
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventListCollapse:
    def test_multi_session_series_collapsed_to_one_card(self, client):
        series = EventSeriesFactory.create(title="Weekly Course")
        for i in range(4):
            EventFactory.create(
                series=series,
                title=f"Session {i}",
                start_datetime=_future_dt(7 + i),
            )
        # Add an unrelated lone event so we can see it doesn't get folded.
        EventFactory.create(title="Lone Event", start_datetime=_future_dt(1))

        resp = client.get(reverse("event_list"))
        assert resp.status_code == 200
        # Only the earliest session of the series should appear; the other
        # three are collapsed.
        body = resp.content.decode()
        assert body.count("Session 0") == 1
        assert "Session 1" not in body
        assert "Session 2" not in body
        assert "Session 3" not in body
        assert "Lone Event" in body
        assert "Series" in body  # collapsed badge

    def test_expand_series_un_collapses(self, client):
        series = EventSeriesFactory.create(title="Weekly Course")
        for i in range(3):
            EventFactory.create(
                series=series,
                title=f"Session {i}",
                start_datetime=_future_dt(7 + i),
            )
        resp = client.get(reverse("event_list") + "?expand_series=1")
        body = resp.content.decode()
        assert "Session 0" in body
        assert "Session 1" in body
        assert "Session 2" in body


# ---------------------------------------------------------------------------
# Event detail "Part of:" + sibling sessions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventDetailSeries:
    def test_part_of_link_present(self, client):
        series = EventSeriesFactory.create(title="Big Course")
        event = EventFactory.create(series=series, title="Session A")
        resp = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        body = resp.content.decode()
        assert "Big Course" in body
        assert "Part of" in body

    def test_sibling_sessions_excludes_past(self, client):
        series = EventSeriesFactory.create()
        main = EventFactory.create(series=series, start_datetime=_future_dt(7))
        EventFactory.create(
            series=series, start_datetime=_future_dt(10), title="Future Sibling"
        )
        EventFactory.create(
            series=series,
            start_datetime=timezone.now() - timezone.timedelta(days=5),
            title="Past Sibling",
        )
        resp = client.get(reverse("event_detail", kwargs={"slug": main.slug}))
        body = resp.content.decode()
        assert "Future Sibling" in body
        assert "Past Sibling" not in body


# ---------------------------------------------------------------------------
# Feeds: ?series= filter
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFeedsSeriesFilter:
    def test_ical_filters_by_series(self, client):
        series_a = EventSeriesFactory.create(title="Series A")
        series_b = EventSeriesFactory.create(title="Series B")
        EventFactory.create(series=series_a, title="In A")
        EventFactory.create(series=series_b, title="In B")
        EventFactory.create(title="Loose")

        resp = client.get(reverse("event_ical_feed") + f"?series={series_a.slug}")
        body = resp.content.decode()
        assert "In A" in body
        assert "In B" not in body
        assert "Loose" not in body

    def test_rss_filters_by_series(self, client):
        series_a = EventSeriesFactory.create(title="Series A")
        EventFactory.create(series=series_a, title="In A")
        EventFactory.create(title="Loose")

        resp = client.get(reverse("event_rss_feed") + f"?series={series_a.slug}")
        body = resp.content.decode()
        assert "In A" in body
        assert "Loose" not in body


# ---------------------------------------------------------------------------
# EventForm series field
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventFormSeriesField:
    def test_can_only_select_own_series(self):
        from events.forms import EventForm

        owner = UserFactory.create()
        other = UserFactory.create()
        own = EventSeriesFactory.create(submitted_by=owner)
        EventSeriesFactory.create(submitted_by=other)

        form = EventForm(creation=True, user=owner)
        choices = list(form.fields["series"].queryset)
        assert own in choices
        assert len(choices) == 1

    def test_attaching_to_other_users_series_rejected(self):
        from events.forms import EventForm

        owner = UserFactory.create()
        other = UserFactory.create()
        other_series = EventSeriesFactory.create(submitted_by=other)
        future = _future_dt(7)
        form = EventForm(
            data={
                "title": "Hijack",
                "description": "",
                "date": future.strftime("%Y-%m-%d"),
                "start_time": future.strftime("%H:%M"),
                "venue_name": "Hall",
                "category": "social",
                "is_free": True,
                "series": str(other_series.pk),
            },
            creation=True,
            user=owner,
        )
        # Series field's queryset doesn't include other_series, so it surfaces
        # as either invalid choice or as a series-clean rejection.
        assert not form.is_valid()
        assert "series" in form.errors


# ---------------------------------------------------------------------------
# Scraper round-trip: base_import series_key handling
# ---------------------------------------------------------------------------


def _build_workshop_record(series_key: str, start: datetime.datetime, title: str):
    return {
        "title": title,
        "description": "",
        "start_datetime": start.isoformat(),
        "end_datetime": (start + datetime.timedelta(hours=2)).isoformat(),
        "venue_name": "Dansehallerne",
        "venue_address": "",
        "category": "workshop",
        "is_free": False,
        "is_wheelchair_accessible": True,
        "price_note": "",
        "source_url": f"https://dansehallerne.dk/example/{series_key}/",
        "external_source": "dansehallerne",
        "series_key": series_key,
        "series_title": title,
        "series_description": "Course description.",
    }


@pytest.mark.django_db
class TestSeriesScraperRoundTrip:
    def _write_payload(self, records, tmp_path: Path) -> Path:
        path = tmp_path / "events.json"
        path.write_text(json.dumps(records))
        return path

    @pytest.fixture
    def system_user(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(
            email="dansehallerne@example.com",
            password="x" * 24,
            display_name="dansehallerne",
            display_name_slug="dansehallerne",
            is_system_account=True,
        )

    @mock.patch("events.management.commands.base_import._download_image")
    def test_importing_creates_series(self, mock_download, system_user, tmp_path):
        mock_download.return_value = None
        future = _future_dt(7).replace(microsecond=0)
        records = [
            _build_workshop_record("course-42", future, "Butoh Intensive"),
            _build_workshop_record(
                "course-42", future + datetime.timedelta(days=7), "Butoh Intensive"
            ),
        ]
        path = self._write_payload(records, tmp_path)
        call_command("import_dansehallerne_workshops", str(path))

        series_qs = EventSeries.objects.filter(
            external_source="dansehallerne", external_key="course-42"
        )
        assert series_qs.count() == 1
        series = series_qs.get()
        assert series.events.count() == 2
        assert series.submitted_by == system_user

    @mock.patch("events.management.commands.base_import._download_image")
    def test_reimport_does_not_duplicate_series(
        self, mock_download, system_user, tmp_path
    ):
        mock_download.return_value = None
        future = _future_dt(7).replace(microsecond=0)
        records = [_build_workshop_record("course-42", future, "Butoh Intensive")]
        path = self._write_payload(records, tmp_path)
        call_command("import_dansehallerne_workshops", str(path))
        call_command("import_dansehallerne_workshops", str(path))
        assert (
            EventSeries.objects.filter(
                external_source="dansehallerne", external_key="course-42"
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# Scraper detail-level series_key selection
# ---------------------------------------------------------------------------


def test_workshops_scraper_emits_series_key_for_multi_session():
    """A multi-date workshop produces records tagged with series_key."""
    from scrapers.dansehallerne_workshops import scrape_detail

    html = """
    <html><body>
      <table class="event-meta">
        <tr><th>Title</th><td>Butoh Intensive</td></tr>
        <tr><th>Artist</th><td>Some Artist</td></tr>
        <tr><th>Venue</th><td>Dansehallerne, Pasteursvej 20</td></tr>
        <tr><th>Date</th><td>1 May 2026</td></tr>
        <tr><th>Duration</th><td>2 hours</td></tr>
      </table>
      <button class="js-download" data-start="1746093600" data-end="1746100800"></button>
      <button class="js-download" data-start="1746698400" data-end="1746705600"></button>
    </body></html>
    """

    fake_resp = mock.Mock()
    fake_resp.text = html
    fake_resp.raise_for_status.return_value = None

    session = mock.Mock()
    session.get.return_value = fake_resp

    with (
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_meta_table",
            return_value={
                "title": "Butoh Intensive",
                "artist": "Some Artist",
                "venue": "Dansehallerne, Pasteursvej 20",
                "date": "1 May 2026",
                "duration": "2 hours",
            },
        ),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_description", return_value="desc"
        ),
        mock.patch("scrapers.dansehallerne_workshops.parse_image_url", return_value=""),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_venue_address",
            return_value=("Dansehallerne", "Pasteursvej 20"),
        ),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_date_string", return_value=[]
        ),
    ):
        results = scrape_detail("https://dansehallerne.dk/example/123/", session)

    assert len(results) == 2
    assert all(r.get("series_key") for r in results)
    assert all(r["series_key"] == results[0]["series_key"] for r in results)


def test_workshops_scraper_omits_series_key_for_single_session():
    from scrapers.dansehallerne_workshops import scrape_detail

    html = """
    <html><body>
      <button class="js-download" data-start="1746093600" data-end="1746100800"></button>
    </body></html>
    """
    fake_resp = mock.Mock()
    fake_resp.text = html
    fake_resp.raise_for_status.return_value = None
    session = mock.Mock()
    session.get.return_value = fake_resp

    with (
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_meta_table",
            return_value={
                "title": "Solo Workshop",
                "artist": "Some Artist",
                "venue": "Dansehallerne",
                "date": "1 May 2026",
                "duration": "2 hours",
            },
        ),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_description", return_value="desc"
        ),
        mock.patch("scrapers.dansehallerne_workshops.parse_image_url", return_value=""),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_venue_address",
            return_value=("Dansehallerne", ""),
        ),
        mock.patch(
            "scrapers.dansehallerne_workshops.parse_date_string", return_value=[]
        ),
    ):
        results = scrape_detail("https://dansehallerne.dk/example/123/", session)

    assert len(results) == 1
    assert "series_key" not in results[0]
