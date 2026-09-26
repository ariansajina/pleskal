"""Unit tests for scrapers/faar302.py."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock, patch

import requests
from bs4 import BeautifulSoup

from scrapers.faar302 import (
    build_records,
    fetch_ticket_events,
    parse_date_range,
    parse_description,
    parse_listing,
    price_note,
    scrape,
    show_times,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
NOW = datetime.datetime(2026, 9, 25, 12, 0, tzinfo=datetime.UTC)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _card(slug: str, title: str, dates: str, event_no: str | None = "147686") -> str:
    button = (
        f'<a class="button basm basm_select" href="#" data-event_no="{event_no}">'
        "Køb billet</a>"
        if event_no
        else ""
    )
    return f"""
    <div class="forestilling">
      <a href="https://www.faar302.dk/forestilling/{slug}/">
        <div class="coverpic b-lazy" style="background: url('placeholder.gif')"
             data-src="https://www.faar302.dk/wp-content/uploads/2026/04/{slug}.jpg">
        </div>
      </a>
      <div class="fortekst">
        {button}
        <a class="forteksten" href="https://www.faar302.dk/forestilling/{slug}/">
          <h3>
            {dates}
          </h3>
          <h1>{title}</h1>
        </a>
      </div>
    </div>
    """


LISTING_HTML = f"""
<html><body>
<nav><a href="https://www.faar302.dk/billetter/">Billetter</a></nav>
{_card("gazed", "Gazed", "7.-10. Oktober 2026")}
{_card("skuret", "SKURET", "15. September - 2. Oktober 2026", "151582")}
{_card("gazed", "Gazed", "7.-10. Oktober 2026")}
{_card("uden-billet", "Uden billet", "1. November 2099", None)}
</body></html>
"""

DETAIL_HTML = """
<html><body>
<div class="forestilling"><h3>7.-10. Oktober 2026</h3><h1>Gazed</h1></div>
<div class="textbox">
  <h2>En solo om at se og blive set</h2>
  <p>Første afsnit.</p>
  <p>&nbsp;</p>
  <p><strong>Varighed</strong> ca. 35 min</p>
</div>
<footer>TEATER FÅR302 · Toldbodgade 6-8</footer>
</body></html>
"""

TICKET_EVENT = {
    "eventNo": 147686,
    "title": "GAZED",
    "ticketPriceMin": 40,
    "ticketPriceMax": 165,
    "showDates": ["2026-10-07T18:00:00", "2026-10-09T18:00:00"],
    "shows": [
        {"showTime": "2026-10-07T18:00:00", "ticketsLeft": None},
        {"showTime": "2026-10-09T18:00:00", "ticketsLeft": None},
        {"showTime": "2026-10-09T18:00:00", "ticketsLeft": None},
        {"showTime": "2026-09-01T18:00:00", "ticketsLeft": None},
    ],
}

SHOW = {
    "url": "https://www.faar302.dk/forestilling/gazed/",
    "title": "Gazed",
    "date_text": "7.-10. Oktober 2026",
    "image_url": "https://www.faar302.dk/wp-content/uploads/2026/04/gazed.jpg",
    "event_no": "147686",
}


# ── parse_listing ─────────────────────────────────────────────────────────────


class TestParseListing:
    def test_extracts_cards(self):
        shows = parse_listing(_soup(LISTING_HTML))
        assert [s["title"] for s in shows] == ["Gazed", "SKURET", "Uden billet"]
        gazed = shows[0]
        assert gazed["url"] == "https://www.faar302.dk/forestilling/gazed/"
        assert gazed["date_text"] == "7.-10. Oktober 2026"
        assert gazed["image_url"].endswith("/2026/04/gazed.jpg")
        assert gazed["event_no"] == "147686"

    def test_card_without_ticket_button_has_empty_event_no(self):
        shows = parse_listing(_soup(LISTING_HTML))
        assert shows[2]["event_no"] == ""

    def test_skips_cards_without_title_or_show_link(self):
        html = """
        <div class="forestilling"><a href="https://www.faar302.dk/x/"><h1>X</h1></a></div>
        <div class="forestilling"><a href="https://www.faar302.dk/forestilling/y/"></a></div>
        """
        assert parse_listing(_soup(html)) == []


# ── parse_date_range ──────────────────────────────────────────────────────────


class TestParseDateRange:
    def test_same_month(self):
        assert parse_date_range("7.-10. Oktober 2026") == (
            datetime.date(2026, 10, 7),
            datetime.date(2026, 10, 10),
        )

    def test_across_months(self):
        assert parse_date_range("15. September - 2. Oktober 2026") == (
            datetime.date(2026, 9, 15),
            datetime.date(2026, 10, 2),
        )

    def test_across_years_without_start_year(self):
        assert parse_date_range("20. December - 5. Januar 2027") == (
            datetime.date(2026, 12, 20),
            datetime.date(2027, 1, 5),
        )

    def test_across_years_with_both_years(self):
        assert parse_date_range("20. December 2026 – 5. Januar 2027") == (
            datetime.date(2026, 12, 20),
            datetime.date(2027, 1, 5),
        )

    def test_single_date(self):
        assert parse_date_range("12. Marts 2027") == (
            datetime.date(2027, 3, 12),
            datetime.date(2027, 3, 12),
        )

    def test_unparseable(self):
        assert parse_date_range("") is None
        assert parse_date_range("Kommer snart") is None
        assert parse_date_range("12. Foo 2027") is None
        assert parse_date_range("7. Oktober") is None
        assert parse_date_range("31. Februar 2027") is None
        assert parse_date_range("10. Oktober 2026 - 7. Oktober 2026") is None


# ── parse_description ─────────────────────────────────────────────────────────


class TestParseDescription:
    def test_converts_textbox_to_markdown(self):
        md = parse_description(_soup(DETAIL_HTML))
        assert md.startswith("## En solo om at se og blive set")
        assert "Første afsnit." in md
        assert "**Varighed** ca. 35 min" in md
        assert "\n\n\n" not in md
        assert "Toldbodgade" not in md

    def test_missing_textbox(self):
        assert parse_description(_soup("<html><body></body></html>")) == ""


# ── Ticketing API ─────────────────────────────────────────────────────────────


def _json_response(payload) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


class TestFetchTicketEvents:
    def test_follows_pagination(self):
        session = MagicMock()
        session.get.side_effect = [
            _json_response({"items": [{"eventNo": 1}], "pagination": {"pageCount": 2}}),
            _json_response(
                {"items": [{"eventNo": 2}, {}], "pagination": {"pageCount": 2}}
            ),
        ]
        events = fetch_ticket_events(session)
        assert set(events) == {"1", "2"}
        assert session.get.call_count == 2
        assert session.get.call_args.kwargs["params"]["page"] == 2

    def test_failure_returns_empty(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("down")
        assert fetch_ticket_events(session) == {}

    def test_bad_json_returns_empty(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("not json")
        session.get.return_value = resp
        assert fetch_ticket_events(session) == {}


class TestShowTimes:
    def test_sorted_deduplicated_copenhagen_times(self):
        times = show_times(TICKET_EVENT)
        assert times == [
            datetime.datetime(2026, 9, 1, 18, 0, tzinfo=CPH_TZ),
            datetime.datetime(2026, 10, 7, 18, 0, tzinfo=CPH_TZ),
            datetime.datetime(2026, 10, 9, 18, 0, tzinfo=CPH_TZ),
        ]

    def test_falls_back_to_show_dates(self):
        times = show_times({"shows": [], "showDates": ["2026-10-07T18:00:00", "x"]})
        assert times == [datetime.datetime(2026, 10, 7, 18, 0, tzinfo=CPH_TZ)]

    def test_none(self):
        assert show_times(None) == []


class TestPriceNote:
    def test_range(self):
        assert price_note(TICKET_EVENT) == "40–165 kr."

    def test_single_price(self):
        assert price_note({"ticketPriceMin": 185, "ticketPriceMax": 185}) == "185 kr."
        assert price_note({"ticketPriceMin": None, "ticketPriceMax": 150}) == "150 kr."

    def test_missing(self):
        assert price_note(None) == ""
        assert price_note({"ticketPriceMin": 0, "ticketPriceMax": None}) == ""


# ── build_records ─────────────────────────────────────────────────────────────


class TestBuildRecords:
    def test_one_record_per_upcoming_performance(self):
        records = build_records(SHOW, "Beskrivelse", TICKET_EVENT, now=NOW)
        assert [r["start_datetime"] for r in records] == [
            "2026-10-07T18:00:00+02:00",
            "2026-10-09T18:00:00+02:00",
        ]
        rec = records[0]
        assert rec["title"] == "Gazed"
        assert rec["description"] == "Beskrivelse"
        assert rec["end_datetime"] is None
        assert rec["venue_name"] == "Teater FÅR302"
        assert rec["venue_address"] == "Toldbodgade 6"
        assert rec["category"] == "performance"
        assert rec["is_free"] is False
        assert rec["is_wheelchair_accessible"] is False
        assert rec["price_note"] == "40–165 kr."
        assert rec["source_url"] == SHOW["url"]
        assert rec["external_source"] == "faar302"
        assert rec["image_url"] == SHOW["image_url"]

    def test_date_range_fallback_without_ticket_data(self):
        show = {**SHOW, "date_text": "15. September - 2. Oktober 2026"}
        (rec,) = build_records(show, "", None, now=NOW)
        assert rec["start_datetime"] == "2026-09-15T00:00:00+02:00"
        assert rec["end_datetime"] == "2026-10-02T23:59:00+02:00"
        assert rec["price_note"] == ""

    def test_single_day_fallback_has_no_end(self):
        show = {**SHOW, "date_text": "1. November 2026"}
        (rec,) = build_records(show, "", None, now=NOW)
        assert rec["start_datetime"] == "2026-11-01T00:00:00+01:00"
        assert rec["end_datetime"] is None

    def test_fallback_drops_finished_run(self):
        show = {**SHOW, "date_text": "1.-3. September 2026"}
        assert build_records(show, "", None, now=NOW) == []

    def test_fallback_unparseable_dates(self):
        show = {**SHOW, "date_text": "Kommer snart"}
        assert build_records(show, "", None, now=NOW) == []

    def test_defaults_now(self):
        show = {**SHOW, "date_text": "1. Januar 2099"}
        assert len(build_records(show, "", None)) == 1


# ── scrape ────────────────────────────────────────────────────────────────────


def test_scrape_joins_listing_details_and_ticket_times():
    def fake_get_soup(url, session):
        if url == "https://www.faar302.dk/":
            return _soup(LISTING_HTML)
        if url.endswith("/skuret/"):
            raise requests.HTTPError("404")
        return _soup(DETAIL_HTML)

    future_event = {
        **TICKET_EVENT,
        "shows": [{"showTime": "2099-10-07T18:00:00"}],
    }
    with (
        patch("scrapers.faar302.get_soup", side_effect=fake_get_soup),
        patch("scrapers.faar302.get_crawl_delay", return_value=0.0),
        patch(
            "scrapers.faar302.fetch_ticket_events",
            return_value={"147686": future_event},
        ),
        patch("scrapers.faar302.time.sleep"),
    ):
        records = scrape(delay=0)

    # Gazed from the ticket API; SKURET's detail page failed and is skipped;
    # "Uden billet" has no ticket data and falls back to its listed date.
    assert [(r["title"], r["start_datetime"]) for r in records] == [
        ("Gazed", "2099-10-07T18:00:00+02:00"),
        ("Uden billet", "2099-11-01T00:00:00+01:00"),
    ]
    assert all(r["description"].startswith("## En solo") for r in records)


def test_scrape_honours_crawl_delay():
    with (
        patch("scrapers.faar302.get_soup", return_value=_soup("<html></html>")),
        patch("scrapers.faar302.get_crawl_delay", return_value=5.0),
        patch("scrapers.faar302.fetch_ticket_events", return_value={}),
    ):
        assert scrape(delay=0) == []
