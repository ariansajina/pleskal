"""Unit tests for scrapers/teaterbilletter.py."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from bs4 import BeautifulSoup

from scrapers import teaterbilletter
from scrapers.teaterbilletter import (
    ListingUnavailable,
    TeaterbilletterVenue,
    build_records,
    credits,
    description,
    event_page_url,
    fetch_events,
    image_url,
    matches_filter,
    price_note,
    scrape,
    show_times,
    ticket_links,
    venue_address,
    venue_page_links,
)

NOW = datetime.datetime(2026, 9, 29, 12, 0, tzinfo=datetime.UTC)

VENUE = TeaterbilletterVenue(
    external_source="blaagaardteater",
    venue_codes=("VN0000046",),
    venue_names={"VN0000046": "Blaagaard Teater"},
    is_wheelchair_accessible=True,
)

# Trimmed from a real /api/events item (HUN ER VRED at Blaagaard Teater).
EVENT: dict[str, Any] = {
    "eventNo": 147563,
    "title": "HUN  ER VRED",
    "slug": "hun-er-vred-147563",
    "teaser": "Et performativt værk om adoption.",
    "description": "Første afsnit.\nAndet afsnit.\n\nTredje afsnit.",
    "categoryName": "Performance",
    "mappedCategoryNames": ["Events"],
    "exitLinkUrl": "https://teaterbilletter.dk/forestillinger/hun-er-vred-147563#select/147563",
    "durationInMinutes": 100,
    "ticketPriceMin": 70,
    "ticketPriceMax": 220,
    "venue": {
        "code": "VN0000046",
        "name": "Blaagaard Teater",
        "street": "Nørrebrogade",
        "number": "37",
        "letter": "",
        "postCode": "2200",
        "city": "København N",
    },
    "images": [
        {
            "url": "https://www.tereba.dk/medias/sq.jpg",
            "width": 1080,
            "orientation": "Square",
        },
        {
            "url": "https://www.tereba.dk/medias/wide.jpg",
            "width": 1949,
            "orientation": "Landscape",
        },
        {
            "url": "https://www.tereba.dk/medias/tall.jpg",
            "width": 668,
            "orientation": "Portrait",
        },
    ],
    "scheduledShows": [
        # Past performance: dropped by build_records.
        {
            "dateTime": "2026-09-01T18:00:00",
            "state": "Active",
            "type": "Almindelig åben",
        },
        # 20:00 in Copenhagen (UTC+1 in December).
        {"dateTime": "2026-12-10T19:00:00", "state": "Active", "type": "Premiere"},
        {
            "dateTime": "2026-12-11T19:00:00",
            "state": "Active",
            "type": "Almindelig åben",
        },
        {
            "dateTime": "2026-12-11T19:00:00",
            "state": "Active",
            "type": "Almindelig åben",
        },
        {
            "dateTime": "2026-12-12T09:00:00",
            "state": "Active",
            "type": "Lukket forestilling",
        },
        {
            "dateTime": "2026-12-13T15:00:00",
            "state": "Cancelled",
            "type": "Almindelig åben",
        },
    ],
}


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ── fetch_events ──────────────────────────────────────────────────────────────


class TestFetchEvents:
    def test_pages_through_results_for_all_venue_codes(self):
        session = MagicMock()
        session.get.side_effect = [
            _response({"items": [{"eventNo": 1}], "pagination": {"pageCount": 2}}),
            _response({"items": [{"eventNo": 2}], "pagination": {"pageCount": 2}}),
        ]
        events = fetch_events(session, ("VN1", "VN2"))
        assert [e["eventNo"] for e in events] == [1, 2]
        params = session.get.call_args_list[0].kwargs["params"]
        assert params["venueCodes"] == "VN1,VN2"
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_error_payload_raises(self):
        session = MagicMock()
        session.get.return_value = _response(
            {"error": "EVENTS_UNAVAILABLE", "message": "Could not load events."}
        )
        with pytest.raises(ValueError, match="EVENTS_UNAVAILABLE"):
            fetch_events(session, ("VN1",))

    def test_http_error_raises(self):
        session = MagicMock()
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError(
            "500"
        )
        with pytest.raises(requests.HTTPError):
            fetch_events(session, ("VN1",))


# ── Filters and field helpers ─────────────────────────────────────────────────


class TestMatchesFilter:
    DANCE = TeaterbilletterVenue(
        external_source="x",
        venue_codes=("VN1",),
        genres=teaterbilletter.DANCE_AND_EVENTS_GENRES,
        categories=teaterbilletter.DANCE_AND_PERFORMANCE_CATEGORIES,
    )

    @pytest.mark.parametrize(
        ("genres", "category", "expected"),
        [
            (["Events"], "Anden genre", True),
            (["Dans"], "Dans og ballet", True),
            (["Drama"], "Performance", True),  # Kropsteater filed under Drama
            ([], "Nycirkus", True),  # new circus without genre tags
            (["Drama"], "Skuespil og dramatik", False),
            (["Musik"], "Anden genre", False),
            ([], "", False),
        ],
    )
    def test_dance_and_events(self, genres, category, expected):
        event = {"mappedCategoryNames": genres, "categoryName": category}
        assert matches_filter(event, self.DANCE) is expected

    def test_no_filter_takes_everything(self):
        event = {"mappedCategoryNames": ["Børneteater"], "categoryName": "x"}
        assert matches_filter(event, VENUE)


class TestShowTimes:
    def test_converts_utc_to_copenhagen_across_dst(self):
        event = {
            "scheduledShows": [
                # Both are 20:00 local: CEST (UTC+2) in October, CET (UTC+1) in November.
                {"dateTime": "2026-10-22T18:00:00", "state": "Active", "type": "x"},
                {"dateTime": "2026-11-12T19:00:00", "state": "Active", "type": "x"},
            ]
        }
        assert [t.isoformat() for t in show_times(event)] == [
            "2026-10-22T20:00:00+02:00",
            "2026-11-12T20:00:00+01:00",
        ]

    def test_skips_closed_cancelled_duplicate_and_bad_times(self):
        event = {
            **EVENT,
            "scheduledShows": [*EVENT["scheduledShows"], {"dateTime": "not a date"}],
        }
        assert [t.isoformat() for t in show_times(event)] == [
            "2026-09-01T20:00:00+02:00",
            "2026-12-10T20:00:00+01:00",
            "2026-12-11T20:00:00+01:00",
        ]

    def test_falls_back_to_shows_then_show_dates(self):
        shows = {"shows": [{"showTime": "2026-10-07T18:00:00"}, None]}
        assert [t.hour for t in show_times(shows)] == [20]
        dates = {"showDates": ["2026-10-07T18:00:00"]}
        assert [t.hour for t in show_times(dates)] == [20]
        assert show_times({}) == []


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (40, 165, "40–165 kr."),
        (100, 100, "100 kr."),
        (0, 80, "80 kr."),
        (None, None, ""),
    ],
)
def test_price_note(low, high, expected):
    assert price_note({"ticketPriceMin": low, "ticketPriceMax": high}) == expected


class TestDescription:
    def test_teaser_leads_and_every_line_is_a_paragraph(self):
        assert description(EVENT) == (
            "Et performativt værk om adoption.\n\n"
            "Første afsnit.\n\nAndet afsnit.\n\nTredje afsnit."
        )

    def test_teaser_repeated_in_description_is_dropped(self):
        event = {
            "teaser": "I 25 år har hun stået på hænder.\n\nEt sjældent indblik.",
            "description": "I 25 år har hun stået på hænder. Nu undersøger hun det.",
        }
        assert description(event) == (
            "Et sjældent indblik.\n\n"
            "I 25 år har hun stået på hænder. Nu undersøger hun det."
        )

    def test_empty(self):
        assert description({"teaser": None, "description": ""}) == ""

    def test_credits_end_the_description(self):
        event = {**EVENT, "accreditations": ACCREDITATIONS}
        paragraphs = description(event).split("\n\n")
        assert paragraphs[-2] == "Tredje afsnit."
        assert paragraphs[-1] == credits(event)
        assert paragraphs[-1].startswith("**Instruktør** Saga Gärde")


# Trimmed from the API's HUN ER VRED, plus a duplicate and blank entries.
ACCREDITATIONS = [
    {
        "positionTypeName": "Cast",
        "firstName": "Uma",
        "lastName": "Feed",
        "positionName": "Medvirkende",
    },
    {
        "positionTypeName": "Production",
        "firstName": "Saga",
        "lastName": "Gärde",
        "positionName": "Instruktør",
    },
    {
        "positionTypeName": "Cast",
        "firstName": "Daniel  Jeremiah",
        "lastName": "Persson",
        "positionName": "Medvirkende",
    },
    {
        "positionTypeName": "Production",
        "firstName": "Ellen",
        "lastName": "Ruge",
        "positionName": "Lysdesigner",
    },
    {
        "positionTypeName": "Production",
        "firstName": "Saga",
        "lastName": "Gärde",
        "positionName": "Instruktør",
    },
    {
        "positionTypeName": "Production",
        "firstName": "",
        "lastName": "Rodrigo y Gabriela",
        "positionName": "Komponist",
    },
    {
        "positionTypeName": "Production",
        "firstName": "",
        "lastName": "",
        "positionName": "Scenograf",
    },
    {
        "positionTypeName": "Production",
        "firstName": "Nobody",
        "lastName": "",
        "positionName": "",
    },
    None,
]


class TestCredits:
    def test_one_line_per_role_crew_before_cast(self):
        event = {
            "accreditations": ACCREDITATIONS,
            "producer": {"code": "OR1", "name": "AMFI "},
            "organizer": {"code": "OR2", "name": "Blaagaard Teater"},
        }
        assert credits(event) == (
            "**Instruktør** Saga Gärde  \n"
            "**Lysdesigner** Ellen Ruge  \n"
            "**Komponist** Rodrigo y Gabriela  \n"
            "**Medvirkende** Uma Feed, Daniel Jeremiah Persson  \n"
            "**Produktion** AMFI"
        )

    def test_venue_producing_itself_is_not_repeated(self):
        venue = {"code": "OR2", "name": "Blaagaard Teater"}
        event = {"accreditations": [], "producer": venue, "organizer": venue}
        assert credits(event) == ""

    def test_no_credits(self):
        assert credits({}) == ""


def test_image_url_prefers_largest_landscape():
    assert image_url(EVENT) == "https://www.tereba.dk/medias/wide.jpg"
    square_only = {"images": [EVENT["images"][0], EVENT["images"][2]]}
    assert image_url(square_only) == "https://www.tereba.dk/medias/sq.jpg"
    assert image_url({"images": []}) == ""


def test_event_page_url():
    assert (
        event_page_url(EVENT)
        == "https://teaterbilletter.dk/forestillinger/hun-er-vred-147563"
    )
    assert event_page_url({"slug": "nok-147034"}) == (
        "https://teaterbilletter.dk/forestillinger/nok-147034"
    )


def test_venue_address():
    assert venue_address(EVENT) == "Nørrebrogade 37"
    afuk = {"venue": {"street": "Enghavevej", "number": "82", "letter": "B"}}
    assert venue_address(afuk) == "Enghavevej 82B"
    assert venue_address({}) == ""


# ── build_records ─────────────────────────────────────────────────────────────


class TestBuildRecords:
    def test_one_record_per_upcoming_public_performance(self):
        records = build_records(EVENT, VENUE, now=NOW)
        assert [(r["start_datetime"], r["end_datetime"]) for r in records] == [
            ("2026-12-10T20:00:00+01:00", "2026-12-10T21:40:00+01:00"),
            ("2026-12-11T20:00:00+01:00", "2026-12-11T21:40:00+01:00"),
        ]
        rec = records[0]
        assert rec["title"] == "HUN ER VRED"
        assert rec["venue_name"] == "Blaagaard Teater"
        assert rec["venue_address"] == "Nørrebrogade 37"
        assert rec["source_url"] == (
            "https://teaterbilletter.dk/forestillinger/hun-er-vred-147563"
        )
        assert rec["external_source"] == "blaagaardteater"
        assert rec["category"] == "performance"
        assert rec["is_wheelchair_accessible"] is True
        assert rec["is_free"] is False
        assert rec["price_note"] == "70–220 kr."
        assert rec["image_url"] == "https://www.tereba.dk/medias/wide.jpg"

    def test_api_venue_name_used_without_override(self):
        event = {**EVENT, "venue": {**EVENT["venue"], "code": "VN9", "name": "Skuret"}}
        (rec, _) = build_records(event, VENUE, now=NOW)
        assert rec["venue_name"] == "Skuret"

    def test_venue_page_link_replaces_the_ticketing_link(self):
        url = "https://blaagaardteater.dk/program/hun-er-vred"
        (rec, _) = build_records(EVENT, VENUE, url, now=NOW)
        assert rec["source_url"] == url

    def test_no_duration_leaves_end_open(self):
        (rec, _) = build_records({**EVENT, "durationInMinutes": 0}, VENUE, now=NOW)
        assert rec["end_datetime"] is None

    @pytest.mark.parametrize("title", ["", "AFLYST! HUN ER VRED"])
    def test_untitled_or_cancelled_is_skipped(self, title):
        assert build_records({**EVENT, "title": title}, VENUE, now=NOW) == []

    def test_defaults_now(self):
        event = {
            **EVENT,
            "scheduledShows": [{"dateTime": "2099-01-01T19:00:00", "state": "Active"}],
        }
        assert len(build_records(event, VENUE)) == 1


# ── Links to the venue's own show pages ─────────────────────────────────────────

LISTING_HTML = """
<div class="grid">
  <div class="card"><button data-event_no="147563">Køb billet</button>
    <h2><a href="/program/hun-er-vred">HUN ER VRED</a></h2></div>
  <div class="card"><h2><a href="/program/blaa-nabo">BLAA NABO</a></h2></div>
  <div class="card"><button data-event_no="150810">Køb billet</button></div>
  <div class="card"><button data-event_no="147563"></button>
    <h2><a href="/program/duplicate">Dup</a></h2></div>
  <div class="card"><button data-event_no="146534"></button>
    <h2><a href="https://blaagaardteater.dk/program/myac">MYAC</a></h2></div>
</div>
"""


# What faar302.dk serves some requests instead of its programme (status 200).
CHALLENGE_HTML = "<html><head><title>Et øjeblik…</title></head><body></body></html>"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def test_ticket_links_maps_ticket_numbers_to_absolute_pages():
    links = ticket_links(
        _soup(LISTING_HTML), "https://blaagaardteater.dk/program", ".card", "h2 a[href]"
    )
    assert links == {
        "147563": "https://blaagaardteater.dk/program/hun-er-vred",
        "146534": "https://blaagaardteater.dk/program/myac",
    }


class TestVenuePageLinks:
    URL = "https://blaagaardteater.dk/program"

    def _links(self, events, fake_get_soup):
        hook = venue_page_links(self.URL, ".card", "h2 a[href]")
        with (
            patch("scrapers.teaterbilletter.get_soup", side_effect=fake_get_soup),
            patch("scrapers.teaterbilletter.time.sleep"),
        ):
            return hook(MagicMock(), events)

    def test_reads_only_the_programme(self):
        fetched: list[str] = []

        def fake_get_soup(url, session):
            fetched.append(url)
            return _soup(LISTING_HTML)

        events = [{"eventNo": 147563}, {"eventNo": 150810, "title": "No page"}]
        assert self._links(events, fake_get_soup) == {
            "147563": f"{self.URL}/hun-er-vred",
            "146534": f"{self.URL}/myac",
        }
        assert fetched == [self.URL]

    def test_bot_challenge_is_retried_once(self):
        pages = iter([_soup(CHALLENGE_HTML), _soup(LISTING_HTML)])
        links = self._links([{"eventNo": 147563}], lambda url, session: next(pages))
        assert links["147563"] == f"{self.URL}/hun-er-vred"

    @pytest.mark.parametrize(
        "failure",
        [requests.ConnectionError("down"), "challenge"],
        ids=["http-error", "bot-challenge"],
    )
    def test_unreadable_listing_fails_instead_of_dropping_links(self, failure):
        calls: list[str] = []

        def fake_get_soup(url, session):
            calls.append(url)
            if failure == "challenge":
                return _soup(CHALLENGE_HTML)
            raise failure

        with pytest.raises(ListingUnavailable, match="blaagaardteater.dk/program"):
            self._links([{"eventNo": 147563}], fake_get_soup)
        assert calls == [self.URL, self.URL]

    def test_no_events_skips_the_listing(self):
        def fake_get_soup(url, session):
            raise AssertionError("listing fetched")

        assert self._links([], fake_get_soup) == {}


# ── scrape ────────────────────────────────────────────────────────────────────


def test_scrape_filters_links_and_builds():
    venue = TeaterbilletterVenue(
        external_source="blaagaardteater",
        venue_codes=("VN0000046",),
        genres=frozenset({"Events"}),
    )
    future = [{"dateTime": "2099-12-10T19:00:00", "state": "Active"}]
    drama = {
        **EVENT,
        "eventNo": 1,
        "mappedCategoryNames": ["Drama"],
        "scheduledShows": future,
    }
    events = [{**EVENT, "scheduledShows": future}, drama]
    seen: list[list[dict]] = []

    def venue_links(session, selected):
        seen.append(selected)
        return {"147563": "https://example.dk/hun"}

    with patch("scrapers.teaterbilletter.fetch_events", return_value=events) as fetch:
        records = scrape(venue, venue_links=venue_links, session=MagicMock())

    assert fetch.call_args.args[1] == ("VN0000046",)
    assert [e["eventNo"] for e in seen[0]] == [147563]
    assert [(r["title"], r["source_url"]) for r in records] == [
        ("HUN ER VRED", "https://example.dk/hun")
    ]


def test_scrape_without_links_uses_new_session():
    with (
        patch("scrapers.teaterbilletter.make_session") as make_session,
        patch("scrapers.teaterbilletter.fetch_events", return_value=[]) as fetch,
    ):
        assert scrape(VENUE) == []
    assert fetch.call_args.args[0] is make_session.return_value


def test_run_cli_writes_scrape_output(tmp_path):
    out = tmp_path / "out.json"
    with patch("sys.argv", ["prog", "--output", str(out)]):
        teaterbilletter.run_cli(lambda: [{"title": "X"}], "venue")
    assert out.read_text(encoding="utf-8").startswith("[")
