"""Regression tests for the security review fixes (allauth routes, re-auth
rate limit, Resend guard, admin CSV export)."""

import csv
import io

import pytest
from django.test import RequestFactory
from django.urls import NoReverseMatch, reverse

from accounts.adapter import ClosedSignupAccountAdapter
from accounts.admin import _csv_safe
from accounts.tests.factories import UserFactory


@pytest.mark.django_db
class TestAllauthRoutesNotMounted:
    """Only allauth's confirm-email view is routed; the rest stay unreachable."""

    @pytest.mark.parametrize(
        "path",
        [
            "/accounts/signup/",
            "/accounts/email/",
            "/accounts/password/reset/",
            "/accounts/password/change/",
            "/accounts/password/set/",
            "/accounts/reauthenticate/",
            "/accounts/inactive/",
            "/accounts/login/code/confirm/",
        ],
    )
    def test_allauth_route_is_404(self, client, path):
        user = UserFactory.create()
        client.force_login(user)
        assert client.get(path).status_code == 404
        assert client.post(path, {"email": "new@example.com"}).status_code == 404

    def test_signup_post_creates_no_user(self, client):
        from accounts.models import User

        before = User.objects.count()
        client.post(
            "/accounts/signup/",
            {
                "email": "intruder@example.com",
                "password1": "correct horse battery staple",
                "password2": "correct horse battery staple",
            },
        )
        assert User.objects.count() == before

    @pytest.mark.parametrize(
        "name", ["account_signup", "account_email", "account_reset_password"]
    )
    def test_allauth_names_do_not_reverse(self, name):
        with pytest.raises(NoReverseMatch):
            reverse(name)

    def test_confirm_email_route_still_mounted(self):
        assert reverse("account_confirm_email", kwargs={"key": "abc:def"}) == (
            "/accounts/confirm-email/abc:def/"
        )

    def test_invalid_confirmation_key_page_renders(self, client):
        resp = client.get("/accounts/confirm-email/not-a-real-key/")
        assert resp.status_code == 200
        assert reverse("login").encode() in resp.content


def test_adapter_closes_signup(settings):
    request = RequestFactory().get("/")
    assert ClosedSignupAccountAdapter(request).is_open_for_signup(request) is False
    assert settings.ACCOUNT_ADAPTER == "accounts.adapter.ClosedSignupAccountAdapter"


@pytest.mark.django_db
class TestReauthRateLimit:
    @pytest.mark.parametrize(
        "url_name", ["change_password", "account_delete", "edit_profile"]
    )
    def test_password_rechecks_are_rate_limited(self, client, url_name):
        user = UserFactory.create()
        client.force_login(user)
        url = reverse(url_name)
        for _ in range(20):
            assert client.post(url, {}).status_code != 429
        assert client.post(url, {}).status_code == 429

    def test_counter_is_shared_across_forms(self, client):
        user = UserFactory.create()
        client.force_login(user)
        for _ in range(20):
            client.post(reverse("change_password"), {})
        assert client.post(reverse("account_delete"), {}).status_code == 429

    def test_anonymous_is_redirected_not_counted(self, client):
        for _ in range(25):
            resp = client.post(reverse("change_password"), {})
            assert resp.status_code == 302


@pytest.mark.django_db
def test_resend_contact_not_added_without_api_key(settings, monkeypatch):
    from allauth.account.models import EmailAddress

    from accounts.signals import add_to_resend_contacts

    settings.RESEND_API_KEY = None
    calls = []
    import resend

    monkeypatch.setattr(resend.Contacts, "create", lambda params: calls.append(params))
    user = UserFactory.create()
    address = EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=True
    )
    add_to_resend_contacts(sender=None, request=None, email_address=address)
    assert calls == []


class TestCsvSafe:
    @pytest.mark.parametrize(
        "value", ["=HYPERLINK(1)", "+1", "-2", "@SUM(A1)", "\tx", "\rx"]
    )
    def test_formula_prefixes_are_neutralised(self, value):
        assert _csv_safe(value) == "'" + value

    @pytest.mark.parametrize("value", ["Alice", "a=b", "", 3, True])
    def test_plain_values_unchanged(self, value):
        assert _csv_safe(value) == str(value)

    def test_none_is_blank(self):
        assert _csv_safe(None) == ""


@pytest.mark.django_db
def test_user_csv_export_neutralises_display_name(admin_client):
    UserFactory.create(display_name="=cmd|' /C calc'!A0")
    resp = admin_client.get(reverse("admin:accounts_user_export_csv"))
    rows = list(csv.reader(io.StringIO(resp.content.decode())))
    names = [row[2] for row in rows[1:]]
    assert "'=cmd|' /C calc'!A0" in names
