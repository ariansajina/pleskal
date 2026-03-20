"""Tests for email sending: admin signup notification, email confirmation, password reset."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import Client

from .factories import UserFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def default_site(db):
    """Ensure a Site object with id=1 exists (required by allauth)."""
    site, _ = Site.objects.get_or_create(
        id=1, defaults={"domain": "example.com", "name": "example.com"}
    )
    return site


# ---------------------------------------------------------------------------
# Admin signup notification signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminSignupNotification:
    def test_notification_sent_on_user_creation(self, mailoutbox, settings):
        settings.ADMINS = ["admin@example.com"]
        UserFactory.create(username="newuser", email="newuser@example.com")
        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert "newuser" in msg.subject
        # Email address is intentionally omitted from the notification body
        # to avoid leaking PII in transit; admins follow the admin URL instead.
        assert "newuser@example.com" not in msg.body
        assert "/admin/accounts/user/" in msg.body
        assert msg.to == ["admin@example.com"]

    def test_notification_not_sent_on_update(self, mailoutbox, settings):
        settings.ADMINS = ["admin@example.com"]
        user = UserFactory.create()
        mailoutbox.clear()
        user.display_name = "Updated name"
        user.save()
        assert len(mailoutbox) == 0

    def test_no_notification_when_admins_empty(self, mailoutbox, settings):
        settings.ADMINS = []
        UserFactory.create()
        assert len(mailoutbox) == 0

    def test_notification_includes_username_not_email(self, mailoutbox, settings):
        settings.ADMINS = ["admin@example.com"]
        UserFactory.create(username="dancer42", email="dancer42@example.com")
        assert len(mailoutbox) == 1
        body = mailoutbox[0].body
        assert "dancer42" in body
        # Email is not included in notification to avoid PII in transit
        assert "dancer42@example.com" not in body


# ---------------------------------------------------------------------------
# Email confirmation on signup (allauth)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmailConfirmationOnSignup:
    def test_confirmation_email_sent_on_signup(self, mailoutbox, settings):
        settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"
        client = Client()
        response = client.post(
            "/accounts/signup/",
            {
                "username": "brandnewuser",
                "email": "brandnewuser@example.com",
                "password1": "CorrectHorse99!",
                "password2": "CorrectHorse99!",
            },
        )
        # allauth redirects after successful signup
        assert response.status_code in (200, 302)
        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert "brandnewuser@example.com" in msg.to
        # Subject should mention confirmation or the site
        assert msg.subject  # non-empty


# ---------------------------------------------------------------------------
# Password reset email (Django built-in RateLimitedPasswordResetView)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPasswordResetEmail:
    def test_reset_email_sent_for_existing_user(self, mailoutbox):
        user = UserFactory.create(email="resetme@example.com")
        client = Client()
        response = client.post(
            "/accounts/password-reset/",
            {"email": user.email},
        )
        assert response.status_code == 302
        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert user.email in msg.to

    def test_no_email_sent_for_unknown_address(self, mailoutbox):
        """Account enumeration hardening: no email, still redirects."""
        client = Client()
        response = client.post(
            "/accounts/password-reset/",
            {"email": "ghost@example.com"},
        )
        assert response.status_code == 302
        assert len(mailoutbox) == 0
