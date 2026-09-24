"""Tests for the cookieless analytics middleware."""

import datetime
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from analytics import middleware
from analytics.models import DailyCount, DailySalt, VisitorHash
from events.tests.factories import EventFactory

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"


@pytest.fixture(autouse=True)
def analytics_on(settings):
    settings.ANALYTICS_ENABLED = True
    middleware._salt_cache.clear()
    yield
    middleware._salt_cache.clear()


@pytest.fixture
def browser(client):
    client.defaults["HTTP_USER_AGENT"] = BROWSER_UA
    return client


def _count(kind, key=""):
    row = DailyCount.objects.filter(kind=kind, key=key).first()
    return row.count if row else 0


def _htmx(current_url, **extra):
    return {
        "HTTP_HX_REQUEST": "true",
        "HTTP_HX_CURRENT_URL": f"http://testserver{current_url}",
        **extra,
    }


@pytest.mark.django_db
class TestPageViews:
    def test_counts_page_view(self, browser):
        browser.get("/about/")
        browser.get("/about/")
        assert _count(DailyCount.PAGE, "/about/") == 2

    def test_query_string_is_not_part_of_the_key(self, browser):
        browser.get("/?page=2")
        assert _count(DailyCount.PAGE, "/") == 1

    def test_event_detail_counted_by_path(self, browser):
        event = EventFactory.create()
        browser.get(event.get_absolute_url())
        assert _count(DailyCount.PAGE, event.get_absolute_url()) == 1

    def test_disabled_records_nothing(self, browser, settings):
        settings.ANALYTICS_ENABLED = False
        browser.get("/about/")
        assert not DailyCount.objects.exists()

    def test_sets_no_cookies_for_anonymous_visitor(self, browser):
        response = browser.get("/about/")
        cookie_names = set(response.cookies.keys())
        # csrftoken is set by the existing templates (strictly necessary);
        # analytics must not add anything on top of it.
        assert cookie_names <= {"csrftoken"}

    @pytest.mark.parametrize(
        "user_agent",
        ["", "Googlebot/2.1", "curl/8.0", "python-requests/2.32", "UptimeRobot"],
    )
    def test_ignores_bots_and_missing_user_agent(self, client, user_agent):
        client.get("/about/", HTTP_USER_AGENT=user_agent)
        assert not DailyCount.objects.exists()

    def test_ignores_prefetch(self, browser):
        browser.get("/about/", HTTP_SEC_PURPOSE="prefetch;prerender")
        assert not DailyCount.objects.exists()

    def test_ignores_non_get(self, browser):
        browser.post("/about/")
        assert not DailyCount.objects.filter(kind=DailyCount.PAGE).exists()

    def test_ignores_404(self, browser):
        browser.get("/no-such-page/")
        assert not DailyCount.objects.exists()

    def test_ignores_infrastructure_urls(self, browser):
        browser.get("/health/")
        browser.get("/robots.txt")
        browser.get("/manifest.webmanifest")
        assert not DailyCount.objects.exists()

    def test_ignores_staff(self, browser):
        browser.force_login(UserFactory.create(is_staff=True))
        browser.get("/about/")
        assert not DailyCount.objects.exists()

    def test_counts_regular_logged_in_users(self, browser):
        browser.force_login(UserFactory.create())
        browser.get("/about/")
        assert _count(DailyCount.PAGE, "/about/") == 1

    def test_ignores_non_html_responses(self, browser):
        browser.get(reverse("event_rss_feed"))
        assert not DailyCount.objects.filter(kind=DailyCount.PAGE).exists()

    def test_htmx_partial_is_not_a_page_view(self, browser):
        browser.get("/?page=2", **_htmx("/"))
        assert not DailyCount.objects.filter(kind=DailyCount.PAGE).exists()

    def test_recording_errors_never_break_the_page(self, browser):
        with mock.patch.object(
            DailyCount, "increment", side_effect=RuntimeError("db down")
        ):
            response = browser.get("/about/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestCalendarDownloads:
    def test_counts_single_event_ics(self, browser):
        event = EventFactory.create()
        path = reverse("event_ical_single", kwargs={"slug": event.slug})
        browser.get(path)
        assert _count(DailyCount.CALENDAR, path) == 1
        assert not DailyCount.objects.filter(kind=DailyCount.PAGE).exists()


@pytest.mark.django_db
class TestReferrers:
    def test_records_external_host_only(self, browser):
        browser.get("/about/", HTTP_REFERER="https://www.instagram.com/some/post?x=1")
        assert _count(DailyCount.REFERRER, "instagram.com") == 1

    def test_ignores_own_site(self, browser):
        browser.get("/about/", HTTP_REFERER="http://testserver/")
        assert not DailyCount.objects.filter(kind=DailyCount.REFERRER).exists()

    def test_ignores_missing_referrer(self, browser):
        browser.get("/about/")
        assert not DailyCount.objects.filter(kind=DailyCount.REFERRER).exists()


@pytest.mark.django_db
class TestVisitors:
    def test_same_visitor_counted_once_per_day(self, browser):
        browser.get("/about/", REMOTE_ADDR="10.0.0.1")
        browser.get("/", REMOTE_ADDR="10.0.0.1")
        assert _count(DailyCount.VISITORS) == 1

    def test_different_visitors_counted_separately(self, browser):
        browser.get("/about/", REMOTE_ADDR="10.0.0.1")
        browser.get("/about/", REMOTE_ADDR="10.0.0.2")
        browser.get("/about/", REMOTE_ADDR="10.0.0.1", HTTP_USER_AGENT="Other/1.0")
        assert _count(DailyCount.VISITORS) == 3

    def test_uses_rightmost_forwarded_ip(self, browser):
        browser.get("/about/", HTTP_X_FORWARDED_FOR="1.1.1.1, 10.0.0.9")
        browser.get("/about/", HTTP_X_FORWARDED_FOR="2.2.2.2, 10.0.0.9")
        assert _count(DailyCount.VISITORS) == 1

    def test_stores_no_ip_address(self, browser):
        browser.get("/about/", REMOTE_ADDR="10.0.0.1")
        hashed = VisitorHash.objects.get()
        assert "10.0.0.1" not in hashed.digest
        assert len(hashed.digest) == 64

    @pytest.mark.parametrize("header", ["HTTP_SEC_GPC", "HTTP_DNT"])
    def test_privacy_signals_skip_visitor_hashing(self, browser, header):
        browser.get("/about/", **{header: "1"})
        assert not VisitorHash.objects.exists()
        assert _count(DailyCount.VISITORS) == 0
        assert _count(DailyCount.PAGE, "/about/") == 1

    def test_new_day_deletes_old_salts_and_hashes(self, browser):
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        DailySalt.objects.create(date=yesterday, salt="old")
        VisitorHash.objects.create(date=yesterday, digest="a" * 64)

        browser.get("/about/")

        assert list(DailySalt.objects.values_list("date", flat=True)) == [
            timezone.localdate()
        ]
        assert not VisitorHash.objects.filter(date=yesterday).exists()
        assert VisitorHash.objects.filter(date=timezone.localdate()).count() == 1

    def test_salt_is_memoised_per_process(self, browser):
        browser.get("/about/", REMOTE_ADDR="10.0.0.1")
        salt = DailySalt.objects.get().salt
        DailySalt.objects.all().delete()
        # Still the same salt in memory, so the same visitor isn't recounted.
        browser.get("/about/", REMOTE_ADDR="10.0.0.1")
        assert middleware._salt_cache[timezone.localdate()] == salt
        assert _count(DailyCount.VISITORS) == 1


@pytest.mark.django_db
class TestSearches:
    def test_full_page_search_counted(self, browser):
        browser.get("/?q=Contact  Improv")
        assert _count(DailyCount.SEARCH, "contact improv") == 1

    def test_typing_counts_only_final_term(self, browser):
        browser.get("/?q=wo", **_htmx("/"))
        browser.get("/?q=work", **_htmx("/?q=wo"))
        browser.get("/?q=workshop", **_htmx("/?q=work"))
        assert list(
            DailyCount.objects.filter(kind=DailyCount.SEARCH, count__gt=0).values_list(
                "key", "count"
            )
        ) == [("workshop", 1)]

    def test_new_unrelated_term_is_counted_separately(self, browser):
        browser.get("/?q=butoh", **_htmx("/"))
        browser.get("/?q=tango", **_htmx("/?q=butoh"))
        assert _count(DailyCount.SEARCH, "butoh") == 1
        assert _count(DailyCount.SEARCH, "tango") == 1

    def test_unchanged_query_not_recounted_when_filtering(self, browser):
        browser.get("/?q=butoh")
        browser.get("/?q=butoh&is_free=1", **_htmx("/?q=butoh"))
        assert _count(DailyCount.SEARCH, "butoh") == 1

    def test_single_character_ignored(self, browser):
        browser.get("/?q=a")
        assert not DailyCount.objects.filter(kind=DailyCount.SEARCH).exists()

    def test_long_query_truncated(self, browser):
        browser.get("/?q=" + "x" * 300)
        key = DailyCount.objects.get(kind=DailyCount.SEARCH).key
        assert len(key) == middleware.SEARCH_KEY_MAX_LENGTH

    def test_map_searches_counted(self, browser):
        browser.get("/map/?q=butoh")
        assert _count(DailyCount.SEARCH, "butoh") == 1

    def test_other_pages_ignore_q(self, browser):
        browser.get("/about/?q=butoh")
        assert not DailyCount.objects.filter(kind=DailyCount.SEARCH).exists()


@pytest.mark.django_db
class TestFilters:
    def test_full_page_filters_counted(self, browser):
        browser.get(
            "/?category=workshop&category=bogus&is_free=1"
            "&is_wheelchair_accessible=1&past=1&date_to=2026-12-31"
            "&publisher=dansehallerne&publisher=bad%20slug!"
        )
        keys = set(
            DailyCount.objects.filter(kind=DailyCount.FILTER).values_list(
                "key", flat=True
            )
        )
        assert keys == {
            "category:workshop",
            "is_free",
            "is_wheelchair_accessible",
            "past",
            "date_range",
            "publisher:dansehallerne",
        }

    def test_only_newly_added_filters_counted(self, browser):
        browser.get("/?category=workshop", **_htmx("/"))
        browser.get(
            "/?category=workshop&category=social", **_htmx("/?category=workshop")
        )
        browser.get(
            "/?category=workshop&category=social&is_free=1",
            **_htmx("/?category=workshop&category=social"),
        )
        assert _count(DailyCount.FILTER, "category:workshop") == 1
        assert _count(DailyCount.FILTER, "category:social") == 1
        assert _count(DailyCount.FILTER, "is_free") == 1

    def test_current_url_on_other_page_is_ignored(self, browser):
        browser.get("/?is_free=1", **_htmx("/map/?is_free=1"))
        assert _count(DailyCount.FILTER, "is_free") == 1
