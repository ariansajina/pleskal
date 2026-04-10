"""Unit tests for scrapers/sort_hvid.py helper functions."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock

import pytest
import requests
from bs4 import BeautifulSoup

from scrapers.sort_hvid import (
    _combine_dt,
    _expand_dates,
    _parse_date,
    _parse_schedule,
    collect_event_urls,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


# ── _parse_date ───────────────────────────────────────────────────────────────


def test_parse_date_standard():
    assert _parse_date("24. April 2026") == datetime.date(2026, 4, 24)


def test_parse_date_different_month():
    assert _parse_date("1. January 2027") == datetime.date(2027, 1, 1)


def test_parse_date_with_whitespace():
    assert _parse_date("  15. May 2026  ") == datetime.date(2026, 5, 15)


def test_parse_date_invalid_returns_none():
    assert _parse_date("not-a-date") is None


def test_parse_date_empty_returns_none():
    assert _parse_date("") is None


def test_parse_date_wrong_format_returns_none():
    assert _parse_date("2026-04-24") is None


# ── _parse_schedule ───────────────────────────────────────────────────────────


def test_parse_schedule_single_day():
    result = _parse_schedule("Saturday @ 17h00")
    assert result == {5: datetime.time(17, 0)}


def test_parse_schedule_day_range():
    result = _parse_schedule("Tuesday-Friday @ 20h00")
    assert result == {
        1: datetime.time(20, 0),
        2: datetime.time(20, 0),
        3: datetime.time(20, 0),
        4: datetime.time(20, 0),
    }


def test_parse_schedule_multiple_segments():
    result = _parse_schedule("Tuesday-Friday @ 20h00, Saturday @ 17h00")
    assert result[1] == datetime.time(20, 0)
    assert result[4] == datetime.time(20, 0)
    assert result[5] == datetime.time(17, 0)
    assert 6 not in result  # Sunday not included


def test_parse_schedule_uppercase_h():
    result = _parse_schedule("Wednesday 19H30")
    assert result == {2: datetime.time(19, 30)}


def test_parse_schedule_wraparound_range():
    # Friday-Sunday wraps: Fri=4, Sat=5, Sun=6
    result = _parse_schedule("Friday-Sunday @ 20h00")
    assert 4 in result
    assert 5 in result
    assert 6 in result


def test_parse_schedule_invalid_falls_back_to_default():
    result = _parse_schedule("not-a-schedule")
    # Default: Mon-Fri at 20:00
    assert len(result) == 5
    for wd in range(5):
        assert result[wd] == datetime.time(20, 0)


def test_parse_schedule_empty_falls_back_to_default():
    result = _parse_schedule("")
    assert len(result) == 5


# ── _expand_dates ─────────────────────────────────────────────────────────────


def test_expand_dates_single_day():
    # April 24, 2026 is a Friday (weekday=4)
    start = datetime.date(2026, 4, 24)
    end = datetime.date(2026, 4, 24)
    schedule = {4: datetime.time(20, 0)}
    result = _expand_dates(start, end, schedule)
    assert len(result) == 1
    assert result[0] == (start, datetime.time(20, 0))


def test_expand_dates_range():
    # One week: Mon-Sun, only select Mon (0) and Wed (2)
    start = datetime.date(2026, 4, 20)  # Monday
    end = datetime.date(2026, 4, 26)  # Sunday
    schedule = {0: datetime.time(18, 0), 2: datetime.time(19, 0)}
    result = _expand_dates(start, end, schedule)
    assert len(result) == 2
    dates = [r[0] for r in result]
    assert datetime.date(2026, 4, 20) in dates  # Monday
    assert datetime.date(2026, 4, 22) in dates  # Wednesday


def test_expand_dates_no_matching_days():
    # Range is only Monday, but schedule only has Saturday
    start = datetime.date(2026, 4, 20)  # Monday
    end = datetime.date(2026, 4, 20)
    schedule = {5: datetime.time(17, 0)}  # Saturday only
    result = _expand_dates(start, end, schedule)
    assert result == []


def test_expand_dates_end_before_start_returns_empty():
    start = datetime.date(2026, 4, 25)
    end = datetime.date(2026, 4, 20)
    schedule = {0: datetime.time(20, 0)}
    result = _expand_dates(start, end, schedule)
    assert result == []


# ── _combine_dt ───────────────────────────────────────────────────────────────


def test_combine_dt_returns_utc():
    date = datetime.date(2026, 6, 1)
    t = datetime.time(20, 0)
    result = _combine_dt(date, t)
    assert result.tzinfo is datetime.UTC
    # 20:00 CEST (UTC+2) → 18:00 UTC
    assert result.hour == 18


def test_combine_dt_winter_time():
    # January: CET = UTC+1
    date = datetime.date(2026, 1, 15)
    t = datetime.time(20, 0)
    result = _combine_dt(date, t)
    assert result.hour == 19  # 20:00 CET → 19:00 UTC


# ── collect_event_urls ────────────────────────────────────────────────────────


def test_collect_event_urls_finds_forestilling_links():
    html = """
    <html><body>
      <a href="/en/forestilling/my-show/">My Show</a>
      <a href="/en/forestilling/another-show/">Another</a>
      <a href="/en/about/">About us</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 2
    assert "https://sort-hvid.dk/en/forestilling/my-show/" in urls


def test_collect_event_urls_deduplicates():
    html = """
    <html><body>
      <a href="/en/forestilling/same-show/">A</a>
      <a href="/en/forestilling/same-show/">B</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 1


def test_collect_event_urls_http_error_raises():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
    with pytest.raises(requests.HTTPError):
        collect_event_urls(session)


def test_collect_event_urls_empty_page():
    html = "<html><body><p>No events</p></body></html>"
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert urls == []


# ── scrape_detail ─────────────────────────────────────────────────────────────

# April 24 2026 is a Friday (weekday=4); April 22 is a Wednesday (2)
_MINIMAL_EVENT_HTML = """
<html><body>
  <h1>Test Performance</h1>
  <strong>24. April 2026</strong>
  <strong>Friday @ 20h00</strong>
</body></html>
"""


def test_scrape_detail_returns_list_of_events():
    session = _mock_session(_MINIMAL_EVENT_HTML)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/test/", session)
    assert result is not None
    assert len(result) >= 1
    assert result[0]["title"] == "Test Performance"
    assert result[0]["external_source"] == "sort-hvid"
    assert result[0]["venue_name"] == "Sort/Hvid"
    assert result[0]["is_wheelchair_accessible"] is False


def test_scrape_detail_http_error_returns_none():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session)
    assert result is None


def test_scrape_detail_no_h1_returns_none():
    html = """
    <html><body>
      <strong>24. April 2026</strong>
      <strong>Friday @ 20h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session) is None


def test_scrape_detail_empty_title_returns_none():
    html = """
    <html><body>
      <h1>   </h1>
      <strong>24. April 2026</strong>
      <strong>Friday @ 20h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session) is None


def test_scrape_detail_no_date_range_returns_none():
    html = "<html><body><h1>My Show</h1></body></html>"
    session = _mock_session(html)
    assert scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session) is None


def test_scrape_detail_bad_start_date_returns_none():
    html = """
    <html><body>
      <h1>Bad Date Show</h1>
      <strong>not-a-date - 22. May 2026</strong>
      <strong>Friday @ 20h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session) is None


def test_scrape_detail_date_range_expands_to_multiple_events():
    # April 24 (Fri) – April 26 (Sun), schedule: Fri and Sat → 2 events
    html = """
    <html><body>
      <h1>Multi-Day Show</h1>
      <strong>24. April 2026 - 26. April 2026</strong>
      <strong>Friday-Saturday @ 20h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/multi/", session)
    assert result is not None
    assert len(result) == 2


def test_scrape_detail_no_schedule_defaults_to_start_date():
    # No schedule strong tag — should default to start_date's weekday at 20:00
    html = """
    <html><body>
      <h1>No Schedule Show</h1>
      <strong>24. April 2026</strong>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session)
    assert result is not None
    assert len(result) == 1


def test_scrape_detail_schedule_produces_no_dates_returns_none():
    # Range is only Saturday (Apr 26), but schedule only has Friday
    html = """
    <html><body>
      <h1>Mismatch Show</h1>
      <strong>26. April 2026</strong>
      <strong>Monday @ 20h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    # April 26, 2026 is a Sunday. Monday schedule won't match.
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session)
    assert result is None


def test_scrape_detail_image_url_extracted():
    html = """
    <html><body>
      <h1>Show With Image</h1>
      <strong>25. April 2026</strong>
      <strong>Saturday @ 17h00</strong>
      <img src="https://sort-hvid.dk/wp-content/uploads/poster.gif">
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/img/", session)
    assert result is not None
    assert "wp-content/uploads/poster.gif" in result[0]["image_url"]


def test_scrape_detail_category_from_hashtag():
    html = """
    <html><body>
      <h1>Opera Show</h1>
      <strong>24. April 2026</strong>
      <strong>Friday @ 20h00</strong>
      <span>#opera</span>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/opera/", session)
    assert result is not None
    assert result[0]["category"] == "performance"


def test_scrape_detail_description_from_performance_content():
    html = """
    <html><body>
      <h1>Described Show</h1>
      <strong>24. April 2026</strong>
      <strong>Friday @ 20h00</strong>
      <div class="performance-content">
        <p>This is the description.</p>
        <p>Second paragraph.</p>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/desc/", session)
    assert result is not None
    assert "This is the description" in result[0]["description"]


def test_scrape_detail_bad_end_date_falls_back_to_start():
    # End date is invalid — should fall back to start_date
    html = """
    <html><body>
      <h1>Partial Date Show</h1>
      <strong>25. April 2026 - not-a-date</strong>
      <strong>Saturday @ 17h00</strong>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://sort-hvid.dk/en/forestilling/x/", session)
    assert result is not None
    assert len(result) == 1
