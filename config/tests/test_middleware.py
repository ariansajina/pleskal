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
class TestAuthenticatedCSP:
    def test_anonymous_policy_allows_kofi(self, client):
        resp = client.get("/about/")
        assert "storage.ko-fi.com" in resp["Content-Security-Policy"]
        assert b'js/kofi.js" defer' in resp.content

    def test_logged_in_policy_drops_kofi(self, client):
        from accounts.tests.factories import UserFactory

        client.force_login(UserFactory.create())
        resp = client.get("/about/")
        policy = resp["Content-Security-Policy"]
        assert "ko-fi.com" not in policy
        assert "script-src 'self'" in policy
        assert "frame-src https://www.openstreetmap.org" in policy
        assert b'js/kofi.js" defer' not in resp.content
