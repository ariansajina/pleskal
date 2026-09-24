"""Tests for the staff-only stats dashboard."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from analytics.models import DailyCount
from analytics.views import _chart_bars
from events.models import FeedHit
from events.tests.factories import EventFactory

URL = "/stats/"


def _add(kind, key="", count=1, days_ago=0):
    DailyCount.objects.create(
        date=timezone.localdate() - datetime.timedelta(days=days_ago),
        kind=kind,
        key=key,
        count=count,
    )


@pytest.fixture
def staff_client(client):
    client.force_login(UserFactory.create(is_staff=True))
    return client


@pytest.mark.django_db
class TestAccess:
    def test_url_name(self):
        assert reverse("stats_dashboard") == URL

    def test_anonymous_redirected_to_login(self, client):
        response = client.get(URL)
        assert response.status_code == 302
        assert reverse("login") in response["Location"]

    def test_non_staff_forbidden(self, client):
        client.force_login(UserFactory.create())
        assert client.get(URL).status_code == 403

    def test_staff_allowed(self, staff_client):
        response = staff_client.get(URL)
        assert response.status_code == 200
        assert b"Site stats" in response.content

    def test_nav_link_only_for_staff(self, client, staff_client):
        assert URL.encode() in staff_client.get("/about/").content
        client.force_login(UserFactory.create())
        assert URL.encode() not in client.get("/about/").content

    def test_disallowed_in_robots_txt(self, client):
        assert b"Disallow: /stats/" in client.get("/robots.txt").content


@pytest.mark.django_db
class TestDashboard:
    def test_empty_state(self, staff_client):
        response = staff_client.get(URL)
        assert b"No page views yet." in response.content
        assert response.context["peak"] is None

    def test_shows_totals_and_top_lists(self, staff_client):
        event = EventFactory.create(title="Butoh Night")
        _add(DailyCount.PAGE, event.get_absolute_url(), count=12)
        _add(DailyCount.PAGE, "/about/", count=3)
        _add(DailyCount.VISITORS, count=6)
        _add(DailyCount.REFERRER, "instagram.com", count=4)
        _add(DailyCount.SEARCH, "contact improv", count=2)
        _add(DailyCount.FILTER, "category:workshop", count=5)
        FeedHit.objects.create(
            feed_type=FeedHit.ICAL, date=timezone.localdate(), count=9
        )

        response = staff_client.get(URL)
        ctx = response.context
        content = response.content.decode()

        assert ctx["totals"][DailyCount.PAGE] == 15
        assert ctx["totals"]["feeds"] == 9
        assert ctx["avg_visitors"] == pytest.approx(6 / 30)
        assert [row.label for row in ctx["top_pages"]] == ["Butoh Night", "About"]
        assert "instagram.com" in content
        assert "contact improv" in content
        assert "Category: Workshop" in content
        assert ctx["peak"]["views"] == 15

    def test_period_filters_data(self, staff_client):
        _add(DailyCount.PAGE, "/about/", count=5, days_ago=20)
        _add(DailyCount.PAGE, "/about/", count=1, days_ago=0)
        assert staff_client.get(URL + "?days=7").context["totals"]["page"] == 1
        assert staff_client.get(URL + "?days=30").context["totals"]["page"] == 6

    @pytest.mark.parametrize("value", ["abc", "3", ""])
    def test_invalid_period_falls_back_to_default(self, staff_client, value):
        assert staff_client.get(URL, {"days": value}).context["days"] == 30

    def test_year_view_uses_weekly_bars(self, staff_client):
        ctx = staff_client.get(URL + "?days=365").context
        assert ctx["weekly_bars"] is True
        assert len(ctx["bars"]) == 53
        assert len(ctx["series"]) == 365


class TestChartBars:
    def _series(self, views):
        start = datetime.date(2026, 1, 1)
        return [
            {"date": start + datetime.timedelta(days=i), "views": v, "visitors": v}
            for i, v in enumerate(views)
        ]

    def test_heights_relative_to_peak(self):
        bars = _chart_bars(self._series([0, 5, 10]))
        assert [bar["height"] for bar in bars] == [0, 50.0, 100.0]
        assert bars[0]["label"] == "Thu 01 Jan"

    def test_all_zero(self):
        assert [bar["height"] for bar in _chart_bars(self._series([0, 0]))] == [0, 0]

    def test_long_series_bucketed_by_week(self):
        bars = _chart_bars(self._series([1] * 91))
        assert len(bars) == 13
        assert bars[0]["views"] == 7
        assert bars[0]["label"] == "01 Jan – 07 Jan"

    def test_partial_week_is_the_oldest_bar(self):
        bars = _chart_bars(self._series([1] * 93))
        assert [bar["views"] for bar in bars] == [2] + [7] * 13
        assert bars[-1]["label"] == "28 Mar – 03 Apr"
