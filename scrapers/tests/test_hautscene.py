"""Unit tests for scrapers/hautscene.py helper functions."""

import datetime

import pytest

from scrapers.hautscene import parse_date, parse_time

# ── parse_date ────────────────────────────────────────────────────────────────


def test_parse_date_standard():
    assert parse_date("24.3.26") == datetime.date(2026, 3, 24)


def test_parse_date_zero_padded():
    assert parse_date("01.03.26") == datetime.date(2026, 3, 1)


def test_parse_date_end_of_year():
    assert parse_date("31.12.27") == datetime.date(2027, 12, 31)


def test_parse_date_invalid_returns_none():
    assert parse_date("not-a-date") is None


def test_parse_date_empty_returns_none():
    assert parse_date("") is None


def test_parse_date_invalid_day_returns_none():
    assert parse_date("32.01.26") is None


# ── parse_time ────────────────────────────────────────────────────────────────


def test_parse_time_range():
    start, end = parse_time("15:00 - 18:00")
    assert start == datetime.time(15, 0)
    assert end == datetime.time(18, 0)


def test_parse_time_single():
    start, end = parse_time("19:30")
    assert start == datetime.time(19, 30)
    assert end is None


def test_parse_time_midnight():
    start, end = parse_time("00:00 - 01:00")
    assert start == datetime.time(0, 0)
    assert end == datetime.time(1, 0)


def test_parse_time_dot_separator():
    start, end = parse_time("15.00 - 17.00")
    assert start == datetime.time(15, 0)
    assert end == datetime.time(17, 0)


def test_parse_time_invalid_raises():
    with pytest.raises(ValueError):
        parse_time("not-a-time")
