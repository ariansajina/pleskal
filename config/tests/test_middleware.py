import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
class TestNoStoreForAuthenticated:
    def test_logged_in_pages_are_no_store(self, client):
        client.force_login(UserFactory.create())
        response = client.get(reverse("event_list"))
        assert response.status_code == 200
        assert "no-store" in response["Cache-Control"]
        assert "private" in response["Cache-Control"]

    def test_anonymous_pages_stay_cacheable(self, client):
        response = client.get(reverse("event_list"))
        assert response.status_code == 200
        assert "no-store" not in response.get("Cache-Control", "")

    def test_existing_cache_control_is_kept(self, client):
        client.force_login(UserFactory.create())
        response = client.get(reverse("robots_txt"))
        assert response["Cache-Control"] == "max-age=86400"


def test_service_worker_skips_no_store_responses(client):
    body = client.get(reverse("pwa_service_worker")).content.decode()
    assert "function isCacheable(response)" in body
    assert "no-store" in body
    # Every cache write goes through the no-store check.
    assert body.count("cache.put(") == body.count("if (isCacheable(response))")


@pytest.mark.django_db
class TestAnonymousPagesSetNoCsrfCookie:
    def test_event_list_sets_no_cookie(self, client):
        response = client.get(reverse("event_list"))
        assert response.status_code == 200
        assert "csrftoken" not in response.cookies
        assert b"X-CSRFToken" not in response.content

    def test_logged_in_pages_carry_the_htmx_token(self, client):
        client.force_login(UserFactory.create())
        response = client.get(reverse("event_list"))
        assert b"X-CSRFToken" in response.content

    def test_login_form_still_gets_its_token(self, client):
        response = client.get(reverse("login"))
        assert "csrftoken" in response.cookies


@pytest.mark.django_db
class TestEdgeCacheAnonymous:
    def test_off_by_default(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 0
        response = client.get(reverse("event_list"))
        assert "s-maxage" not in response.get("Cache-Control", "")

    def test_anonymous_html_is_edge_cacheable(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 60
        response = client.get(reverse("about"))
        cache_control = response["Cache-Control"]
        assert "public" in cache_control
        assert "s-maxage=60" in cache_control
        assert "max-age=0" in cache_control
        assert "HX-Request" in response["Vary"]

    def test_htmx_requests_are_not_marked(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 60
        response = client.get(reverse("event_list"), HTTP_HX_REQUEST="true")
        assert "s-maxage" not in response.get("Cache-Control", "")

    def test_pages_setting_a_cookie_are_not_marked(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 60
        response = client.get(reverse("login"))
        assert "s-maxage" not in response.get("Cache-Control", "")

    def test_requests_with_a_session_are_not_marked(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 60
        client.cookies[settings.SESSION_COOKIE_NAME] = "abc"
        response = client.get(reverse("about"))
        assert "s-maxage" not in response.get("Cache-Control", "")

    def test_logged_in_pages_stay_no_store(self, client, settings):
        settings.EDGE_CACHE_SECONDS = 60
        client.force_login(UserFactory.create())
        response = client.get(reverse("about"))
        assert "no-store" in response["Cache-Control"]
        assert "public" not in response["Cache-Control"]
