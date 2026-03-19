"""Tests for rate limiting on login, password reset, and event submission."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the cache before and after each test to reset rate limit counters."""
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Unit tests for core rate limiting helpers
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    def test_first_request_is_allowed(self):
        from config.ratelimit import check_rate_limit

        assert check_rate_limit("test:key", limit=3, window=60) is False

    def test_requests_within_limit_are_allowed(self):
        from config.ratelimit import check_rate_limit

        for _ in range(3):
            assert check_rate_limit("test:key2", limit=3, window=60) is False

    def test_request_exceeding_limit_is_blocked(self):
        from config.ratelimit import check_rate_limit

        for _ in range(3):
            check_rate_limit("test:key3", limit=3, window=60)
        assert check_rate_limit("test:key3", limit=3, window=60) is True

    def test_different_keys_are_independent(self):
        from config.ratelimit import check_rate_limit

        for _ in range(3):
            check_rate_limit("test:alpha", limit=3, window=60)
        # "beta" key is fresh; should not be blocked
        assert check_rate_limit("test:beta", limit=3, window=60) is False


class TestGetClientIp:
    def test_returns_remote_addr_by_default(self, rf):
        from config.ratelimit import get_client_ip

        request = rf.get("/", REMOTE_ADDR="1.2.3.4")
        assert get_client_ip(request) == "1.2.3.4"

    def test_prefers_x_forwarded_for(self, rf):
        from config.ratelimit import get_client_ip

        request = rf.get(
            "/",
            HTTP_X_FORWARDED_FOR="9.8.7.6, 1.2.3.4",
            REMOTE_ADDR="1.2.3.4",
        )
        assert get_client_ip(request) == "9.8.7.6"


# ---------------------------------------------------------------------------
# Login rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLoginRateLimit:
    def test_login_blocked_after_limit(self, client, settings):
        settings.AXES_ENABLED = False
        from accounts.views import RateLimitedLoginView
        from config.ratelimit import check_rate_limit

        limit = RateLimitedLoginView.rate_limit_limit
        window = RateLimitedLoginView.rate_limit_window
        key = "rl:login:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.post(
            reverse("login"),
            {"username": "any@example.com", "password": "anypassword"},
        )
        assert resp.status_code == 429

    def test_successful_login_not_blocked_within_limit(self, client, settings):
        settings.AXES_ENABLED = False
        UserFactory.create(email="ok@example.com")
        resp = client.post(
            reverse("login"),
            {"username": "ok@example.com", "password": "testpass123"},
        )
        assert resp.status_code in (200, 302)
        assert resp.status_code != 429

    def test_get_login_page_not_rate_limited(self, client):
        from accounts.views import RateLimitedLoginView
        from config.ratelimit import check_rate_limit

        limit = RateLimitedLoginView.rate_limit_limit
        window = RateLimitedLoginView.rate_limit_window
        key = "rl:login:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.get(reverse("login"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Password reset rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPasswordResetRateLimit:
    def test_password_reset_blocked_after_limit(self, client):
        from accounts.views import RateLimitedPasswordResetView
        from config.ratelimit import check_rate_limit

        limit = RateLimitedPasswordResetView.rate_limit_limit
        window = RateLimitedPasswordResetView.rate_limit_window
        key = "rl:password_reset:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.post(
            reverse("password_reset"),
            {"email": "any@example.com"},
        )
        assert resp.status_code == 429

    def test_password_reset_within_limit_is_allowed(self, client):
        resp = client.post(
            reverse("password_reset"),
            {"email": "nobody@example.com"},
        )
        assert resp.status_code in (200, 302)
        assert resp.status_code != 429

    def test_get_password_reset_page_not_rate_limited(self, client):
        from accounts.views import RateLimitedPasswordResetView
        from config.ratelimit import check_rate_limit

        limit = RateLimitedPasswordResetView.rate_limit_limit
        window = RateLimitedPasswordResetView.rate_limit_window
        key = "rl:password_reset:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.get(reverse("password_reset"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Event submission rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventSubmitRateLimit:
    def _submit_event(self, client, i=0):
        future = timezone.now() + timezone.timedelta(days=7)
        return client.post(
            reverse("event_create"),
            {
                "title": f"Rate Limit Test Event {i}",
                "description": "Description",
                "start_datetime": future.strftime("%Y-%m-%d %H:%M:%S"),
                "venue_name": "Test Venue",
                "category": "SOCIAL",
                "is_free": "on",
            },
        )

    def test_event_submit_blocked_after_limit(self, client):
        from config.ratelimit import check_rate_limit
        from events.views import EventCreateView

        user = UserFactory.create()
        client.force_login(user)

        limit = EventCreateView.rate_limit_limit
        window = EventCreateView.rate_limit_window
        key = f"rl:event_create:user:{user.pk}"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = self._submit_event(client)
        assert resp.status_code == 429

    def test_event_submit_within_limit_allowed(self, client):
        user = UserFactory.create()
        client.force_login(user)
        resp = self._submit_event(client)
        # Not a 429 (may be redirect on success or 200 with form errors)
        assert resp.status_code != 429

    def test_different_users_have_independent_limits(self, client):
        from config.ratelimit import check_rate_limit
        from events.views import EventCreateView

        user_a = UserFactory.create()
        user_b = UserFactory.create()

        # Exhaust limit for user_a
        limit = EventCreateView.rate_limit_limit
        window = EventCreateView.rate_limit_window
        key_a = f"rl:event_create:user:{user_a.pk}"
        for _ in range(limit):
            check_rate_limit(key_a, limit, window)

        # user_b should still be allowed
        client.force_login(user_b)
        resp = self._submit_event(client)
        assert resp.status_code != 429

    def test_event_submit_requires_login(self, client):
        resp = self._submit_event(client)
        # Unauthenticated requests are redirected to login, not 429
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url


# ---------------------------------------------------------------------------
# Event list / search rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventListRateLimit:
    def test_event_list_blocked_after_limit(self, client):
        from config.ratelimit import check_rate_limit
        from events.views import EventListView

        limit = EventListView.rate_limit_limit
        window = EventListView.rate_limit_window
        key = "rl:event_list:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.get(reverse("event_list"))
        assert resp.status_code == 429

    def test_event_list_within_limit_allowed(self, client):
        resp = client.get(reverse("event_list"))
        assert resp.status_code != 429

    def test_event_list_post_not_rate_limited_by_get_limit(self, client):
        """GET rate limit does not bleed into other HTTP methods."""
        from config.ratelimit import check_rate_limit
        from events.views import EventListView

        limit = EventListView.rate_limit_limit
        window = EventListView.rate_limit_window
        key = "rl:event_list:127.0.0.1"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        # POST to the same URL is not a real action but should not return 429
        # (the view has no post handler so Django returns 405)
        resp = client.post(reverse("event_list"))
        assert resp.status_code != 429


# ---------------------------------------------------------------------------
# Event update rate limiting (image processing endpoint)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventUpdateRateLimit:
    def test_event_update_blocked_after_limit(self, client):
        from config.ratelimit import check_rate_limit
        from events.tests.factories import EventFactory
        from events.views import EventUpdateView

        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)

        limit = EventUpdateView.rate_limit_limit
        window = EventUpdateView.rate_limit_window
        key = f"rl:event_update:user:{user.pk}"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.post(reverse("event_edit", kwargs={"slug": event.slug}), {})
        assert resp.status_code == 429

    def test_event_update_within_limit_allowed(self, client):
        from events.tests.factories import EventFactory

        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)

        resp = client.post(reverse("event_edit", kwargs={"slug": event.slug}), {})
        assert resp.status_code != 429

    def test_event_update_different_users_independent(self, client):
        from config.ratelimit import check_rate_limit
        from events.tests.factories import EventFactory
        from events.views import EventUpdateView

        user_a = UserFactory.create()
        user_b = UserFactory.create()
        event_b = EventFactory.create(submitted_by=user_b)

        limit = EventUpdateView.rate_limit_limit
        window = EventUpdateView.rate_limit_window
        key_a = f"rl:event_update:user:{user_a.pk}"
        for _ in range(limit):
            check_rate_limit(key_a, limit, window)

        client.force_login(user_b)
        resp = client.post(reverse("event_edit", kwargs={"slug": event_b.slug}), {})
        assert resp.status_code != 429


# ---------------------------------------------------------------------------
# Event duplicate rate limiting (image processing endpoint)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventDuplicateRateLimit:
    def test_event_duplicate_blocked_after_limit(self, client):
        from config.ratelimit import check_rate_limit
        from events.tests.factories import EventFactory
        from events.views import EventDuplicateView

        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)

        limit = EventDuplicateView.rate_limit_limit
        window = EventDuplicateView.rate_limit_window
        key = f"rl:event_duplicate:user:{user.pk}"
        for _ in range(limit):
            check_rate_limit(key, limit, window)

        resp = client.post(reverse("event_duplicate", kwargs={"slug": event.slug}), {})
        assert resp.status_code == 429

    def test_event_duplicate_within_limit_allowed(self, client):
        from events.tests.factories import EventFactory

        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client.force_login(user)

        resp = client.post(reverse("event_duplicate", kwargs={"slug": event.slug}), {})
        assert resp.status_code != 429
