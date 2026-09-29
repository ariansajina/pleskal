"""Tests for events shown as series: scraped shows linked into a series,
one list card per series, the detail page's date strip, the all-dates
download, and the limits that apply only to private users."""

import datetime
import importlib
import json

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory

from ..forms import EventForm
from ..models import Event, EventSeries
from ..series import link_scraped_series, scraped_series_key
from .factories import EventFactory


def _at(days, hour=19, minute=0):
    """An aware local datetime *days* from today at *hour*:*minute*."""
    day = timezone.localdate() + datetime.timedelta(days=days)
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute))
    )


def _series(*starts, title="Long Run", **fields):
    """A series (no rule) with one event per start, in start order."""
    series = EventSeries.objects.create(dtstart=starts[0], source_key=title)
    return [
        EventFactory.create(title=title, start_datetime=start, series=series, **fields)
        for start in starts
    ]


def _cards(resp):
    return [(e.title, e.series_card) for e in resp.context["events"]]


# ---------------------------------------------------------------------------
# Scraped shows
# ---------------------------------------------------------------------------


class TestScrapedSeriesKey:
    def test_uses_source_and_page_url(self):
        assert (
            scraped_series_key("sort-hvid", "https://sort-hvid.dk/show/")
            == "sort-hvid:https://sort-hvid.dk/show/"
        )

    @pytest.mark.parametrize("suffix", ["2026-10-01/", "2026-10-01"])
    def test_drops_a_trailing_date(self, suffix):
        url = f"https://warehouse9.dk/event/wrestling/{suffix}"
        assert (
            scraped_series_key("warehouse9", url)
            == "warehouse9:https://warehouse9.dk/event/wrestling/"
        )

    def test_keeps_a_date_inside_the_path(self):
        url = "https://dansehallerne.dk/en/2026/06/24/h0le-again/"
        assert scraped_series_key("dansehallerne", url).endswith("/24/h0le-again/")

    @pytest.mark.parametrize(("source", "url"), [("", "https://x.dk/"), ("x", "")])
    def test_blank_without_source_or_url(self, source, url):
        assert scraped_series_key(source, url) == ""


def _scraped(url, *days, source="sort-hvid"):
    return [
        EventFactory.create(
            title=f"Show {url[-8:]}",
            external_source=source,
            source_url=url,
            start_datetime=_at(day),
        )
        for day in days
    ]


@pytest.mark.django_db
class TestLinkScrapedSeries:
    def test_links_dates_of_one_show(self):
        dates = _scraped("https://sort-hvid.dk/a/", 3, 4, 5)
        assert link_scraped_series("sort-hvid", dates) == 3
        series = EventSeries.objects.get()
        assert series.source_key == "sort-hvid:https://sort-hvid.dk/a/"
        assert series.rrule == ""
        assert series.pattern is None
        assert series.dtstart == dates[0].start_datetime
        assert {e.series_id for e in Event.objects.all()} == {series.pk}

    def test_single_date_gets_no_series(self):
        link_scraped_series("sort-hvid", _scraped("https://sort-hvid.dk/a/", 3))
        assert not EventSeries.objects.exists()
        assert Event.objects.get().series_id is None

    def test_single_date_joins_an_existing_series(self):
        link_scraped_series("sort-hvid", _scraped("https://sort-hvid.dk/a/", 3, 4))
        late = _scraped("https://sort-hvid.dk/a/", 9)
        assert link_scraped_series("sort-hvid", late) == 1
        late[0].refresh_from_db()
        assert late[0].series == EventSeries.objects.get()

    def test_separate_shows_get_separate_series(self):
        dates = _scraped("https://sort-hvid.dk/a/", 3, 4)
        dates += _scraped("https://sort-hvid.dk/b/", 3, 4)
        link_scraped_series("sort-hvid", dates)
        assert EventSeries.objects.count() == 2

    def test_is_idempotent(self):
        dates = _scraped("https://sort-hvid.dk/a/", 3, 4)
        link_scraped_series("sort-hvid", dates)
        for event in dates:
            event.refresh_from_db()
        assert link_scraped_series("sort-hvid", dates) == 0
        assert EventSeries.objects.count() == 1

    def test_ignores_events_without_url(self):
        dates = _scraped("", 3, 4)
        assert link_scraped_series("sort-hvid", dates) == 0


def _record(url, start, title="Series Show"):
    return {
        "source_url": url,
        "start_datetime": start,
        "title": title,
        "description": "",
        "venue_name": "Test Venue",
        "category": "performance",
        "image_url": "",
    }


@pytest.mark.django_db
class TestImporterLinksSeries:
    def _import(self, tmp_path, records):
        path = tmp_path / "events.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        call_command("import_events", "dansehallerne", str(path), "--skip-images")

    def test_dates_of_one_page_form_a_series(self, tmp_path):
        url = "https://dansehallerne.dk/event/run"
        self._import(
            tmp_path,
            [
                _record(url, "2030-06-01T18:00:00+02:00"),
                _record(url, "2030-06-02T18:00:00+02:00"),
                _record(
                    "https://dansehallerne.dk/event/one",
                    "2030-06-01T18:00:00+02:00",
                    "One",
                ),
            ],
        )
        run = Event.objects.filter(source_url=url)
        assert run.count() == 2
        assert len({e.series_id for e in run}) == 1
        assert run.first().series.source_key == f"dansehallerne:{url}"
        assert Event.objects.get(title="One").series is None

    def test_reimport_keeps_the_series_and_adds_new_dates(self, tmp_path):
        url = "https://dansehallerne.dk/event/run"
        records = [
            _record(url, "2030-06-01T18:00:00+02:00"),
            _record(url, "2030-06-02T18:00:00+02:00"),
        ]
        self._import(tmp_path, records)
        series = EventSeries.objects.get()
        self._import(tmp_path, [*records, _record(url, "2030-06-03T18:00:00+02:00")])
        assert EventSeries.objects.get() == series
        assert series.occurrences.count() == 3

    def test_dry_run_links_nothing(self, tmp_path):
        url = "https://dansehallerne.dk/event/run"
        path = tmp_path / "events.json"
        path.write_text(
            json.dumps(
                [
                    _record(url, "2030-06-01T18:00:00+02:00"),
                    _record(url, "2030-06-02T18:00:00+02:00"),
                ]
            ),
            encoding="utf-8",
        )
        call_command("import_events", "dansehallerne", str(path), "--dry-run")
        assert not EventSeries.objects.exists()

    def test_series_goes_when_its_dates_are_deleted(self, tmp_path):
        url = "https://dansehallerne.dk/event/run"
        self._import(
            tmp_path,
            [
                _record(url, "2030-06-01T18:00:00+02:00"),
                _record(url, "2030-06-02T18:00:00+02:00"),
            ],
        )
        path = tmp_path / "events.json"
        path.write_text("[]", encoding="utf-8")
        call_command("import_events", "dansehallerne", str(path), "--force-delete")
        assert not EventSeries.objects.exists()


@pytest.mark.django_db
def test_migration_links_existing_scraped_dates():
    migration = importlib.import_module("events.migrations.0011_scraped_event_series")
    dates = _scraped(
        "https://warehouse9.dk/event/w/2026-10-01/", 3, source="warehouse9"
    )
    dates += _scraped(
        "https://warehouse9.dk/event/w/2026-10-08/", 10, source="warehouse9"
    )
    lone = _scraped("https://warehouse9.dk/event/solo/", 4, source="warehouse9")
    user_event = EventFactory.create(start_datetime=_at(3))
    migration.link_existing_scraped_series(apps, None)
    series = EventSeries.objects.get()
    assert series.source_key == "warehouse9:https://warehouse9.dk/event/w/"
    assert set(series.occurrences.all()) == set(dates)
    for event in [*lone, user_event]:
        event.refresh_from_db()
        assert event.series_id is None
    migration.unlink_scraped_series(apps, None)
    assert not EventSeries.objects.exists()


@pytest.mark.django_db
def test_series_without_rule_str():
    series = EventSeries.objects.create(dtstart=_at(1), source_key="x:https://x/")
    assert str(series) == "x:https://x/"


# ---------------------------------------------------------------------------
# Event list: one card per series
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListOneCardPerSeries:
    def test_series_is_listed_once_at_its_next_date(self, client):
        run = _series(_at(-2), _at(2), _at(3), _at(5, 20))
        EventFactory.create(title="One-off", start_datetime=_at(4))
        resp = client.get(reverse("event_list"))
        events = resp.context["events"]
        assert [e.title for e in events] == ["Long Run", "One-off"]
        assert events[0].pk == run[1].pk
        card = events[0].series_card
        assert card.count == 3
        assert [d["date"] for d in card.days] == [
            _at(3).date(),
            timezone.localtime(_at(5, 20)).date(),
        ]
        assert events[1].series_card is None
        content = resp.content.decode()
        assert "2 events · 4 dates found" in content
        assert 'class="series-next">Next<' in content
        assert "3 dates, until" in content

    def test_counts_are_per_series(self, client):
        _series(_at(-3), _at(-2), _at(2), _at(3))
        EventFactory.create(start_datetime=_at(4))
        resp = client.get(reverse("event_list"))
        assert resp.context["upcoming_count"] == 2
        assert resp.context["past_count"] == 1
        assert resp.context["page_obj"].paginator.count == 2

    def test_pagination_counts_series(self, client, settings, monkeypatch):
        monkeypatch.setattr("events.views.EVENTS_PER_PAGE", 2)
        _series(_at(1), _at(2), _at(3), title="A")
        _series(_at(1, 20), _at(4), title="B")
        EventFactory.create(title="C", start_datetime=_at(5))
        resp = client.get(reverse("event_list"))
        assert resp.context["page_obj"].paginator.num_pages == 2
        resp = client.get(reverse("event_list") + "?page=2")
        assert [e.title for e in resp.context["events"]] == ["C"]

    def test_several_times_a_day(self, client):
        _series(_at(2, 18), _at(2, 19), _at(2, 20), _at(3, 18), _at(3, 19))
        resp = client.get(reverse("event_list"))
        card = resp.context["events"][0].series_card
        assert card.times_on_day == 3
        assert card.day_count == 2
        assert card.days == [{"date": _at(3).date(), "count": 2}]
        content = resp.content.decode()
        assert "+2 more times" in content
        assert "5 showings on 2 days" in content

    def test_names_a_few_days_then_counts_the_rest(self, client):
        _series(*[_at(day) for day in range(1, 10)])
        card = client.get(reverse("event_list")).context["events"][0].series_card
        assert len(card.days) == 5
        assert card.more_days == 3

    def test_date_range_places_card_at_first_date_in_range(self, client):
        run = _series(_at(1), _at(3), _at(4), _at(9))
        start, end = _at(2).date(), _at(5).date()
        resp = client.get(reverse("event_list"), {"date_from": start, "date_to": end})
        (event,) = resp.context["events"]
        assert event.pk == run[1].pk
        card = event.series_card
        assert (card.count, card.total, card.outside) == (2, 4, 2)
        content = resp.content.decode()
        assert "2 of 4 dates in range" in content
        assert "2 more dates outside this range" in content

    def test_date_range_with_one_date_of_a_series(self, client):
        _series(_at(1), _at(8))
        day = _at(8).date()
        resp = client.get(
            reverse("event_list"), {"date_from": _at(7).date(), "date_to": day}
        )
        card = resp.context["events"][0].series_card
        assert (card.count, card.total) == (1, 2)
        assert "1 of 2 dates in range" in resp.content.decode()

    def test_single_day_lists_showtimes(self, client):
        _series(_at(3, 17), _at(3, 18), _at(4, 17))
        day = _at(3).date()
        resp = client.get(reverse("event_list"), {"date_from": day, "date_to": day})
        card = resp.context["events"][0].series_card
        assert [t.hour for t in card.showtimes] == [17, 18]
        content = resp.content.decode()
        assert "2 showings this day" in content
        assert 'class="series-next"' not in content

    def test_past_lists_series_at_latest_past_date(self, client):
        run = _series(_at(-5), _at(-3), _at(2))
        resp = client.get(reverse("event_list"), {"past": "1"})
        (event,) = resp.context["events"]
        assert event.pk == run[1].pk
        assert event.series_card.count == 2
        assert 'class="series-next">Last<' in resp.content.decode()

    def test_filters_apply_before_grouping(self, client):
        _series(_at(2), _at(3), is_free=True, title="Free Run")
        _series(_at(2, 20), _at(4), title="Paid Run")
        resp = client.get(reverse("event_list"), {"is_free": "1"})
        assert [e.title for e in resp.context["events"]] == ["Free Run"]

    def test_drafts_are_not_listed(self, client):
        run = _series(_at(2), _at(3))
        Event.objects.filter(pk=run[0].pk).update(is_draft=True)
        resp = client.get(reverse("event_list"))
        (event,) = resp.context["events"]
        assert event.pk == run[1].pk
        assert event.series_card is None
        assert b'class="badge badge--repeat"' in resp.content

    def test_htmx_partial_is_grouped(self, client):
        _series(_at(2), _at(3))
        resp = client.get(reverse("event_list"), headers={"HX-Request": "true"})
        assert len(resp.context["events"]) == 1
        assert b"1 event \xc2\xb7 2 dates found" in resp.content


@pytest.mark.django_db
class TestPublisherProfileGroups:
    def test_upcoming_past_and_drafts_are_grouped(self, client):
        owner = UserFactory.create(display_name="Studio")
        _series(_at(-3), _at(-2), _at(2), _at(3), submitted_by=owner)
        drafts = _series(_at(5), _at(6), title="Draft Run", submitted_by=owner)
        Event.objects.filter(pk__in=[d.pk for d in drafts]).update(is_draft=True)
        url = reverse("publisher_profile", args=[owner.display_name_slug])

        resp = client.get(url)
        assert [e.title for e in resp.context["events"]] == ["Long Run"]
        assert resp.context["events"][0].series_card.count == 2

        resp = client.get(url, {"past": "1"})
        (past,) = resp.context["events"]
        assert past.start_datetime == _at(-2)

        client.force_login(owner)
        resp = client.get(url)
        (draft,) = resp.context["drafts"]
        assert draft.title == "Draft Run"
        assert draft.series_card.count == 2


# ---------------------------------------------------------------------------
# Detail page: date strip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDetailStrip:
    def test_scraped_series_shows_range_and_days(self, client):
        run = _series(_at(2, 18), _at(2, 19), _at(3, 18), _at(40, 18))
        resp = client.get(reverse("event_detail", args=[run[1].slug]))
        series = resp.context["series"]
        assert series["summary"] == ""
        assert (series["count"], series["day_count"]) == (4, 3)
        assert [o.pk for o in series["current_day_times"]] == [run[0].pk, run[1].pk]
        current = [day for day in series["days"] if day["is_current"]]
        assert current[0]["date"] == _at(2).date()
        content = resp.content.decode()
        assert "4 showings on 3 days" in content
        assert "Showtimes this day" in content
        assert content.count('class="date-strip__month"') == len(
            {(d["date"].year, d["date"].month) for d in series["days"]}
        )

    def test_past_dates_are_marked(self, client):
        run = _series(_at(-2), _at(2))
        resp = client.get(reverse("event_detail", args=[run[1].slug]))
        assert [d["is_past"] for d in resp.context["series"]["days"]] == [True, False]
        assert b'class="date-tile date-tile--past"' in resp.content

    def test_dates_too_old_to_list_are_left_out(self, client, settings):
        settings.USER_EVENT_HIDE_AFTER_DAYS = 10
        run = _series(_at(-30), _at(2), _at(3))
        resp = client.get(reverse("event_detail", args=[run[1].slug]))
        assert resp.context["series"]["count"] == 2
        resp = client.get(reverse("event_detail", args=[run[0].slug]))
        assert resp.context["series"]["count"] == 3

    def test_no_strip_when_only_one_date_is_visible(self, client):
        run = _series(_at(2), _at(3))
        Event.objects.filter(pk=run[1].pk).update(is_draft=True)
        resp = client.get(reverse("event_detail", args=[run[0].slug]))
        assert resp.context["series"] is None

    def test_owner_sees_draft_dates(self, client):
        owner = UserFactory.create()
        run = _series(_at(2), _at(3), submitted_by=owner)
        Event.objects.filter(pk=run[1].pk).update(is_draft=True)
        client.force_login(owner)
        resp = client.get(reverse("event_detail", args=[run[0].slug]))
        assert resp.context["series"]["count"] == 2
        assert b'class="date-tile date-tile--draft"' in resp.content

    def test_many_dates_scroll(self, client):
        run = _series(*[_at(day) for day in range(1, 15)])
        resp = client.get(reverse("event_detail", args=[run[0].slug]))
        assert b'class="date-strip date-strip--overflow"' in resp.content
        assert b"js/date-strip.js" in resp.content


# ---------------------------------------------------------------------------
# All dates as one .ics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSeriesICal:
    def test_contains_upcoming_published_dates(self, client):
        run = _series(_at(-2), _at(2), _at(3), _at(4))
        Event.objects.filter(pk=run[3].pk).update(is_draft=True)
        resp = client.get(reverse("event_ical_series", args=[run[1].slug]))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/calendar; charset=utf-8"
        assert f'filename="{run[1].slug}-all-dates.ics"' in resp["Content-Disposition"]
        assert resp.content.count(b"BEGIN:VEVENT") == 2

    def test_linked_from_detail_page(self, client):
        run = _series(_at(2), _at(3))
        resp = client.get(reverse("event_detail", args=[run[0].slug]))
        assert reverse("event_ical_series", args=[run[0].slug]).encode() in resp.content

    def test_single_event_is_404(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_ical_series", args=[event.slug]))
        assert resp.status_code == 404

    def test_draft_is_404(self, client):
        run = _series(_at(2), _at(3))
        Event.objects.filter(pk=run[0].pk).update(is_draft=True)
        resp = client.get(reverse("event_ical_series", args=[run[0].slug]))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Limits apply to private users only
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLimitsOnlyForPrivateUsers:
    def _event(self, submitter, days=400):
        return Event(
            title="Far ahead",
            start_datetime=timezone.now() + datetime.timedelta(days=days),
            venue_name="Hall",
            submitted_by=submitter,
        )

    def test_model_rejects_far_dates_for_private_users(self):
        event = self._event(UserFactory.create())
        with pytest.raises(ValidationError, match="1 year"):
            event.full_clean()

    def test_model_allows_far_dates_for_system_accounts(self):
        self._event(UserFactory.create(is_system_account=True)).full_clean()

    def _form(self, user, days=400):
        day = timezone.localdate() + datetime.timedelta(days=days)
        return EventForm(
            {
                "title": "Far ahead",
                "date": day.strftime("%Y-%m-%d"),
                "start_time": "19:00",
                "venue_name": "Hall",
                "category": "social",
            },
            creation=True,
            user=user,
        )

    def test_form_rejects_far_dates_for_private_users(self):
        form = self._form(UserFactory.create())
        assert not form.is_valid()
        assert "1 year" in str(form.errors["date"])

    def test_form_allows_far_dates_for_system_accounts(self):
        form = self._form(UserFactory.create(is_system_account=True))
        assert form.is_valid(), form.errors
