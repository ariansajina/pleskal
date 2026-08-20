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
        assert "https://tile.openstreetmap.org" in sources
