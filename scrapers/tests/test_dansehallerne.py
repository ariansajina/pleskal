"""Unit tests for scrapers/dansehallerne.py helper functions."""

import datetime
import zoneinfo

from scrapers.dansehallerne import parse_date_string

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")


def _dt(year, month, day, hour, minute):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=CPH_TZ).astimezone(
        datetime.UTC
    )


# ── parse_date_string ─────────────────────────────────────────────────────────


def test_single_date():
    result = parse_date_string("1.5.2026, 18:00")
    assert result == [(_dt(2026, 5, 1, 18, 0), None)]


def test_day_range():
    result = parse_date_string("1.-3.5.2026, 18:00")
    assert result == [
        (_dt(2026, 5, 1, 18, 0), None),
        (_dt(2026, 5, 2, 18, 0), None),
        (_dt(2026, 5, 3, 18, 0), None),
    ]


def test_two_ranges():
    result = parse_date_string("1.–3.5 + 8.–10.5.2026, 18:00")
    assert len(result) == 6
    assert result[0] == (_dt(2026, 5, 1, 18, 0), None)
    assert result[2] == (_dt(2026, 5, 3, 18, 0), None)
    assert result[3] == (_dt(2026, 5, 8, 18, 0), None)
    assert result[5] == (_dt(2026, 5, 10, 18, 0), None)


def test_unicode_dash():
    # Both – (en-dash) and - (hyphen) should work
    result_unicode = parse_date_string("1.\u20133.5.2026, 18:00")
    result_hyphen = parse_date_string("1.-3.5.2026, 18:00")
    assert result_unicode == result_hyphen


def test_invalid_returns_empty():
    assert parse_date_string("not a date") == []


def test_missing_time_returns_empty():
    assert parse_date_string("1.5.2026") == []
