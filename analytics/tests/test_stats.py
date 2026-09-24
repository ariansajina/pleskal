"""Tests for the analytics read-side helpers."""

import datetime

import pytest

from accounts.tests.factories import UserFactory
from analytics import stats
from analytics.models import DailyCount
from events.tests.factories import EventFactory

DAY = datetime.date(2026, 3, 10)


def _add(kind, key="", count=1, date=DAY):
    DailyCount.objects.create(date=date, kind=kind, key=key, count=count)


def test_date_range_is_inclusive():
    assert stats.date_range(7, DAY) == (datetime.date(2026, 3, 4), DAY)


@pytest.mark.django_db
class TestTotalsAndSeries:
    def test_totals_default_to_zero(self):
        totals = stats.totals(DAY, DAY)
        assert totals[DailyCount.PAGE] == 0
        assert totals["feeds"] == 0

    def test_totals_sum_within_range_only(self):
        _add(DailyCount.PAGE, "/a/", 2)
        _add(DailyCount.PAGE, "/b/", 3)
        _add(DailyCount.PAGE, "/a/", 100, date=DAY - datetime.timedelta(days=1))
        assert stats.totals(DAY, DAY)[DailyCount.PAGE] == 5

    def test_daily_series_fills_gaps(self):
        _add(DailyCount.PAGE, "/a/", 4)
        _add(DailyCount.VISITORS, "", 2)
        series = stats.daily_series(DAY - datetime.timedelta(days=2), DAY)
        assert [(d["views"], d["visitors"]) for d in series] == [(0, 0), (0, 0), (4, 2)]


@pytest.mark.django_db
class TestTopLists:
    def test_top_pages_labels(self):
        event = EventFactory.create(title="Butoh Night")
        publisher = UserFactory.create(display_name="Dansehallerne")
        _add(DailyCount.PAGE, event.get_absolute_url(), 5)
        _add(DailyCount.PAGE, f"/accounts/publishers/{publisher.display_name_slug}/", 4)
        _add(DailyCount.PAGE, "/", 3)
        _add(DailyCount.PAGE, "/events/deleted-event/", 2)
        _add(DailyCount.PAGE, "/gone-forever/", 1)
        _add(DailyCount.PAGE, "/subscribe/", 0)

        rows = stats.top_pages(DAY, DAY)
        assert [(r.label, r.count) for r in rows] == [
            ("Butoh Night", 5),
            ("Publisher: Dansehallerne", 4),
            ("Event list (home)", 3),
            ("/events/deleted-event/", 2),
            ("/gone-forever/", 1),
        ]
        assert rows[0].path == event.get_absolute_url()

    def test_calendar_downloads_labelled_with_event(self):
        event = EventFactory.create(title="Tango Class")
        _add(DailyCount.CALENDAR, f"/events/{event.slug}/calendar.ics", 3)
        rows = stats.top_pages(DAY, DAY, kind=DailyCount.CALENDAR)
        assert [(r.label, r.count) for r in rows] == [("Tango Class", 3)]

    def test_top_lists_sum_across_days_and_limit(self):
        for i in range(3):
            _add(DailyCount.SEARCH, "butoh", 1, date=DAY - datetime.timedelta(days=i))
        _add(DailyCount.SEARCH, "tango", 2)
        _add(DailyCount.SEARCH, "salsa", 1)
        rows = stats.top_searches(DAY - datetime.timedelta(days=2), DAY, limit=2)
        assert [(r.label, r.count) for r in rows] == [("butoh", 3), ("tango", 2)]

    def test_top_referrers(self):
        _add(DailyCount.REFERRER, "instagram.com", 2)
        assert [r.label for r in stats.top_referrers(DAY, DAY)] == ["instagram.com"]

    def test_top_filters_labels(self):
        _add(DailyCount.FILTER, "category:workshop", 3)
        _add(DailyCount.FILTER, "is_free", 2)
        _add(DailyCount.FILTER, "publisher:dansehallerne", 1)
        assert [r.label for r in stats.top_filters(DAY, DAY)] == [
            "Category: Workshop",
            "Free events",
            "Publisher: dansehallerne",
        ]

    @pytest.mark.parametrize(
        ("key", "label"),
        [
            ("category:bogus", "Category: bogus"),
            ("date_range", "Date range"),
            ("unknown", "unknown"),
        ],
    )
    def test_filter_label_fallbacks(self, key, label):
        assert stats.filter_label(key) == label
