"""Tests for events.views._get_quick_date_ranges and _advanced_filters_open."""

import datetime

import pytest

import events.views as events_views
from events.views import _advanced_filters_open, _get_quick_date_ranges


class _FixedDate(datetime.date):
    """A datetime.date subclass whose .today() returns a fixed value."""

    _fixed = datetime.date(2026, 1, 1)

    @classmethod
    def today(cls):
        return cls._fixed


def _freeze_today(monkeypatch, value):
    fixed = type("_Fixed", (_FixedDate,), {"_fixed": value})
    monkeypatch.setattr(events_views.datetime, "date", fixed)


@pytest.mark.django_db
class TestThisWeekendRange:
    def test_weekday_gives_upcoming_saturday_to_sunday(self, monkeypatch):
        # 2026-07-15 is a Wednesday.
        _freeze_today(monkeypatch, datetime.date(2026, 7, 15))
        ranges = _get_quick_date_ranges()
        assert ranges["this_weekend"] == ("2026-07-18", "2026-07-19")

    def test_saturday_gives_saturday_to_sunday(self, monkeypatch):
        _freeze_today(monkeypatch, datetime.date(2026, 7, 18))
        ranges = _get_quick_date_ranges()
        assert ranges["this_weekend"] == ("2026-07-18", "2026-07-19")

    def test_sunday_gives_sunday_to_sunday(self, monkeypatch):
        _freeze_today(monkeypatch, datetime.date(2026, 7, 19))
        ranges = _get_quick_date_ranges()
        assert ranges["this_weekend"] == ("2026-07-19", "2026-07-19")


class TestAdvancedFiltersOpen:
    quick_date_ranges = {
        "this_week": ("2026-07-15", "2026-07-19"),
        "this_weekend": ("2026-07-18", "2026-07-19"),
        "next_week": ("2026-07-20", "2026-07-26"),
        "this_month": ("2026-07-01", "2026-07-31"),
        "next_month": ("2026-08-01", "2026-08-31"),
    }

    def _open(self, **overrides):
        kwargs = {
            "search_query": "",
            "categories": [],
            "publisher_slugs": [],
            "is_free": False,
            "is_wheelchair_accessible": False,
            "date_from": "",
            "date_to": "",
            "quick_date_ranges": self.quick_date_ranges,
        }
        kwargs.update(overrides)
        return _advanced_filters_open(**kwargs)

    def test_no_params_closed(self):
        assert self._open() is False

    def test_is_free_opens(self):
        # is_free now lives inside the panel (only This week/Next week are
        # in the quickbar), so it must force the disclosure open.
        assert self._open(is_free=True) is True

    def test_date_range_matching_this_week_stays_closed(self):
        assert (
            self._open(
                date_from="2026-07-15",
                date_to="2026-07-19",
            )
            is False
        )

    def test_date_range_matching_next_week_stays_closed(self):
        assert (
            self._open(
                date_from="2026-07-20",
                date_to="2026-07-26",
            )
            is False
        )

    def test_date_range_matching_this_weekend_opens(self):
        # This weekend moved into the panel, so it's no longer exempt.
        assert (
            self._open(
                date_from="2026-07-18",
                date_to="2026-07-19",
            )
            is True
        )

    def test_category_opens(self):
        assert self._open(categories=["workshop"]) is True

    def test_publisher_opens(self):
        assert self._open(publisher_slugs=["some-publisher"]) is True

    def test_search_opens(self):
        assert self._open(search_query="tango") is True

    def test_wheelchair_opens(self):
        assert self._open(is_wheelchair_accessible=True) is True

    def test_arbitrary_date_range_opens(self):
        assert (
            self._open(
                date_from="2026-09-01",
                date_to="2026-09-05",
            )
            is True
        )
