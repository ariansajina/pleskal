"""Tests for security hardening — axes lockout and CSP header."""

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
class TestAxesLockout:
    """Brute-force protection: 5 failed attempts locks the account."""

    def test_lockout_after_five_failures(self, client, settings):
        # Reset axes state cleanly for each test
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()  # type: ignore

        settings.AXES_FAILURE_LIMIT = 5
        UserFactory.create(email="victim@example.com")

        login_url = reverse("login")
        for _ in range(5):
            client.post(
                login_url,
                {"username": "victim@example.com", "password": "wrongpassword"},
            )

        # 6th attempt should be locked out; axes returns 429 Too Many Requests
        resp = client.post(
            login_url,
            {"username": "victim@example.com", "password": "wrongpassword"},
        )
        # Axes can return 429, 403, or 200 with error text — all indicate lockout
        assert resp.status_code in (429, 403, 200)
        if resp.status_code == 200:
            assert (
                b"locked" in resp.content.lower()
                or b"too many" in resp.content.lower()
                or b"blocked" in resp.content.lower()
            )

    def test_successful_login_resets_attempt_count(self, client, settings):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()  # type: ignore

        settings.AXES_FAILURE_LIMIT = 5
        settings.AXES_RESET_ON_SUCCESS = True
        UserFactory.create(email="gooduser@example.com")

        login_url = reverse("login")

        # 3 failed attempts
        for _ in range(3):
            client.post(
                login_url,
                {"username": "gooduser@example.com", "password": "wrongpassword"},
            )

        # Successful login
        resp = client.post(
            login_url,
            {"username": "gooduser@example.com", "password": "testpass123"},
        )
        assert resp.status_code == 302

        # Attempt count should be reset — 3 more failures shouldn't lock
        client.logout()
        for _ in range(3):
            client.post(
                login_url,
                {"username": "gooduser@example.com", "password": "wrongpassword"},
            )
        resp = client.post(
            login_url,
            {"username": "gooduser@example.com", "password": "testpass123"},
        )
        assert resp.status_code == 302  # still logs in fine


@pytest.mark.django_db
class TestAxesLockoutScope:
    """Behind Railway's proxy every request shares REMOTE_ADDR, so the lockout
    must key on the forwarded client IP and the attacked username — never on
    the proxy address alone, which would lock every user out at once."""

    @pytest.fixture(autouse=True)
    def _reset_axes(self, settings):
        from axes.models import AccessAttempt

        AccessAttempt.objects.all().delete()  # type: ignore
        settings.AXES_FAILURE_LIMIT = 5

    def _login(self, client, email, password, client_ip):
        return client.post(
            reverse("login"),
            {"username": email, "password": password},
            REMOTE_ADDR="10.0.0.1",  # the proxy, identical for everyone
            HTTP_X_FORWARDED_FOR=client_ip,
        )

    def _fail_five_times(self, client, email, client_ip):
        for _ in range(5):
            self._login(client, email, "wrongpassword", client_ip)

    def test_locked_pair_cannot_log_in_even_with_correct_password(self, client):
        UserFactory.create(email="victim@example.com")
        self._fail_five_times(client, "victim@example.com", "203.0.113.1")

        resp = self._login(client, "victim@example.com", "testpass123", "203.0.113.1")
        assert resp.status_code != 302

    def test_other_user_behind_same_proxy_is_not_locked_out(self, client):
        UserFactory.create(email="victim@example.com")
        UserFactory.create(email="bystander@example.com")
        self._fail_five_times(client, "victim@example.com", "203.0.113.1")

        resp = self._login(
            client, "bystander@example.com", "testpass123", "198.51.100.7"
        )
        assert resp.status_code == 302

    def test_email_case_variations_share_one_failure_counter(self, client):
        UserFactory.create(email="victim@example.com")
        for email in (
            "Victim@example.com",
            "VICTIM@example.com",
            "victim@Example.com",
            "vIctim@example.com",
            "viCtim@example.com",
        ):
            self._login(client, email, "wrongpassword", "203.0.113.1")

        resp = self._login(client, "victim@example.com", "testpass123", "203.0.113.1")
        assert resp.status_code != 302

    def test_same_user_from_another_client_ip_is_not_locked_out(self, client):
        UserFactory.create(email="victim@example.com")
        self._fail_five_times(client, "victim@example.com", "203.0.113.1")

        resp = self._login(client, "victim@example.com", "testpass123", "198.51.100.7")
        assert resp.status_code == 302


TILE_HOST = "https://tile.openstreetmap.org"


def _csp_sources(response, directive):
    """Return one CSP directive's source expressions as an exact-match list.

    Splitting into whole tokens keeps the assertions exact: a substring check
    against the raw header would also pass for a host that merely contains the
    expected one (`https://tile.openstreetmap.org.example.com`).
    """
    header = response["Content-Security-Policy"]
    for part in header.split("; "):
        name, _, values = part.partition(" ")
        if name == directive:
            return values.split()
    raise AssertionError(f"{directive} missing from Content-Security-Policy: {header}")


@pytest.mark.django_db
class TestCSPHeader:
    """Content-Security-Policy header is present on all responses."""

    def test_csp_header_on_homepage(self, client):
        resp = client.get(reverse("event_list"))
        assert "Content-Security-Policy" in resp

    def test_csp_default_src_self(self, client):
        resp = client.get(reverse("event_list"))
        csp = resp["Content-Security-Policy"]
        assert "default-src 'self'" in csp

    def test_csp_frame_ancestors_none(self, client):
        resp = client.get(reverse("event_list"))
        csp = resp["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp

    def test_csp_form_action_self(self, client):
        resp = client.get(reverse("event_list"))
        csp = resp["Content-Security-Policy"]
        assert "form-action 'self'" in csp

    def test_csp_present_on_login_page(self, client):
        resp = client.get(reverse("login"))
        assert "Content-Security-Policy" in resp

    def test_csp_no_unsafe_eval(self, client):
        resp = client.get(reverse("event_list"))
        csp = resp["Content-Security-Policy"]
        assert "unsafe-eval" not in csp

    def test_csp_allows_openstreetmap_frame(self, client):
        resp = client.get(reverse("event_list"))
        csp = resp["Content-Security-Policy"]
        assert "frame-src https://www.openstreetmap.org" in csp

    def test_csp_script_src_has_no_unsafe_inline(self, client):
        """Inline <script> and on*= handlers must stay blocked."""
        sources = _csp_sources(client.get(reverse("event_list")), "script-src")
        assert "'unsafe-inline'" not in sources
        assert "'unsafe-hashes'" not in sources

    def test_referrer_policy_preserved(self, client):
        """SecurityMiddleware owns this header now that the custom CSP
        middleware (which used to set it) is gone."""
        resp = client.get(reverse("event_list"))
        assert resp["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_csp_img_src_allows_map_tiles_and_data_uris(self, client):
        """Leaflet tiles and the data: URIs used by inline icons must load."""
        sources = _csp_sources(client.get(reverse("event_list")), "img-src")
        assert "'self'" in sources
        assert "data:" in sources
        # Counted rather than `host in sources`: equality cannot match a
        # lookalike host, and `in` against a URL literal is what CodeQL's
        # incomplete-URL-substring-sanitization rule flags.
        assert sources.count(TILE_HOST) == 1
