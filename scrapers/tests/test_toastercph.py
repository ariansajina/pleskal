"""Unit tests for scrapers/toastercph.py."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock

from scrapers.toastercph import (
    _determine_category,
    _infer_year,
    collect_listing_cards,
    parse_date_raw,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
TODAY = datetime.date(2026, 9, 26)


def _cph(year, month, day, hour=0, minute=0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, tzinfo=CPH_TZ).astimezone(
        datetime.UTC
    )


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


# ── _infer_year ───────────────────────────────────────────────────────────────


def test_infer_year_upcoming_date_is_this_year():
    assert _infer_year(10, 1, TODAY) == 2026


def test_infer_year_recent_past_stays_this_year():
    # A multi-date entry's first date, a few days gone, is not next year's.
    assert _infer_year(9, 23, TODAY) == 2026


def test_infer_year_early_months_roll_over():
    assert _infer_year(3, 3, TODAY) == 2027


# ── parse_date_raw ────────────────────────────────────────────────────────────


def test_single_slot_with_time_range():
    assert parse_date_raw("16/10 at 20.30-01.00", TODAY) == [
        (_cph(2026, 10, 16, 20, 30), _cph(2026, 10, 17, 1, 0))
    ]


def test_slot_with_explicit_year():
    # The listing now writes the year after the date; the time must survive.
    assert parse_date_raw("01/10 2026 at 18.00-21.00", TODAY) == [
        (_cph(2026, 10, 1, 18, 0), _cph(2026, 10, 1, 21, 0))
    ]


def test_multi_slot_each_with_its_own_time():
    assert parse_date_raw("17/10 at 19.00-20.40 + 18/10 at 15.00-16.40", TODAY) == [
        (_cph(2026, 10, 17, 19, 0), _cph(2026, 10, 17, 20, 40)),
        (_cph(2026, 10, 18, 15, 0), _cph(2026, 10, 18, 16, 40)),
    ]


def test_multi_slot_shared_time_and_explicit_years():
    # "Rene penge?": the years are given, the time applies to all dates, and
    # the first date has already passed.
    raw = "23/9 2026 + 11/11 2026 + 3/3 2027 - alle dage kl. 10-12"
    assert parse_date_raw(raw, TODAY) == [
        (_cph(2026, 11, 11, 10, 0), _cph(2026, 11, 11, 12, 0)),
        (_cph(2027, 3, 3, 10, 0), _cph(2027, 3, 3, 12, 0)),
    ]


def test_date_range_uses_start_date():
    assert parse_date_raw("17/10 - 3/11 at 20.00", TODAY) == [
        (_cph(2026, 10, 17), None)
    ]


def test_opening_hours_entries_are_skipped():
    raw = "17/10 - 3/11 - during opening hours at Husets Teater"
    assert parse_date_raw(raw, TODAY) == []


def test_date_without_time_is_midnight():
    assert parse_date_raw("5/10", TODAY) == [(_cph(2026, 10, 5), None)]


def test_unparseable_returns_empty():
    assert parse_date_raw("", TODAY) == []
    assert parse_date_raw("TBA", TODAY) == []


# ── _determine_category ───────────────────────────────────────────────────────


def test_category_from_series_and_type():
    assert _determine_category("show", "Workshops") == "workshop"
    assert _determine_category("show", None) == "performance"
    assert _determine_category("industry_event", "Seminar") == "other"


# ── Listing + detail ──────────────────────────────────────────────────────────

_LISTING = """
<html><body>
  <h1>Upcoming</h1>
  <div class="event-list">
    <div class="event">
      <div class="image"><img src="https://toastercph.dk/img/a.jpg"></div>
      <div class="c3"><a href="https://toastercph.dk/industry-event/rene-penge/?lang=en">
        <h2>Rene penge? <span>Udviklet af Art Hub Copenhagen, HAUT og Toaster</span></h2>
      </a></div>
      <div class="info">
        <h5>11/11 2026 - kl. 10-12</h5>
        <h5>Thoravej29, Lokale 3.1, 2400 København NV</h5>
        <h5>Seminar- og workshoprække</h5>
      </div>
    </div>
    <div class="event">
      <div class="c3"><a href="https://toastercph.dk/show/nervetraade/?lang=en">
        <h2>Nervetråde <span>Sara Sjölin</span></h2>
      </a></div>
      <div class="info"><h5>01/10 2026 at 18.00-21.00</h5><h5>Den Frie</h5></div>
    </div>
  </div>
  <h1>Past</h1>
  <div class="event-list"></div>
</body></html>
"""


def test_collect_listing_cards_drops_credit_line_from_title():
    cards = collect_listing_cards(_mock_session(_LISTING))
    assert [c["title_raw"] for c in cards] == [
        "Rene penge?",
        "Nervetråde by Sara Sjölin",
    ]
    assert cards[0]["event_type"] == "industry_event"
    assert cards[1]["event_type"] == "show"


_DETAIL = """
<html><body>
  <nav>Free entry to our summer party!</nav>
  <div class="description"><p>{text}</p></div>
  <a class="button ticket" href="https://billetto.dk/x">Read more</a>
</body></html>
"""


def _card(**overrides) -> dict:
    card = {
        "title_raw": "Nervetråde by Sara Sjölin",
        "detail_url": "https://toastercph.dk/show/nervetraade/?lang=en",
        "date_raw": "01/10 2026 at 18.00-21.00",
        "venue": "Den Frie",
        "series": None,
        "image_url": "",
        "event_type": "show",
    }
    card.update(overrides)
    return card


def test_scrape_detail_ignores_button_label_and_page_chrome():
    session = _mock_session(_DETAIL.format(text="A performance."))
    records = scrape_detail(_card(), session, TODAY)
    assert len(records) == 1
    assert records[0]["price_note"] == ""  # not "Read more"
    assert records[0]["is_free"] is False  # the nav's free party isn't this event
    assert records[0]["start_datetime"] == _cph(2026, 10, 1, 18, 0).isoformat()
    assert records[0]["venue_address"] == ""


def test_scrape_detail_free_from_description_and_address_venue():
    session = _mock_session(
        _DETAIL.format(text="ANTAL PLADSER: 20 – gratis adgang med opsamling.")
    )
    card = _card(
        date_raw="11/11 2026 - kl. 10-12",
        venue="Thoravej29, Lokale 3.1, 2400 København NV",
    )
    records = scrape_detail(card, session, TODAY)
    assert records[0]["is_free"] is True
    assert records[0]["venue_address"] == "Thoravej29, Lokale 3.1, 2400 København NV"
