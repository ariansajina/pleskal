"""Tests for email sending: admin signup notification and password reset."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from .factories import UserFactory

User = get_user_model()


# ---------------------------------------------------------------------------
# Resend contact sync signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResendContactSync:
    def _make_email_address(self, user):
        email_address = MagicMock()
        email_address.user = user
        email_address.email = user.email
        return email_address

    def test_system_account_skipped(self, settings):
        settings.RESEND_API_KEY = "test-key"
        user = UserFactory.create(is_system_account=True)
        email_address = self._make_email_address(user)
        mock_resend = MagicMock()

        with patch.dict("sys.modules", {"resend": mock_resend}):
            from accounts.signals import add_to_resend_contacts

            add_to_resend_contacts(
                sender=None, request=None, email_address=email_address
            )
            mock_resend.Contacts.create.assert_not_called()

    def test_regular_user_added(self, settings):
        settings.RESEND_API_KEY = "test-key"
        user = UserFactory.create(is_system_account=False)
        email_address = self._make_email_address(user)
        mock_resend = MagicMock()

        with patch.dict("sys.modules", {"resend": mock_resend}):
            from accounts.signals import add_to_resend_contacts

            add_to_resend_contacts(
                sender=None, request=None, email_address=email_address
            )
            mock_resend.Contacts.create.assert_called_once()


# ---------------------------------------------------------------------------
# Admin signup notification signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminSignupNotification:
    def test_notification_sent_on_user_creation(self, mailoutbox, settings):
        settings.ADMINS = ["admin@example.com"]
        UserFactory.create(email="newuser@example.com")
        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert "newuser@example.com" in msg.body
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

    def test_notification_includes_email(self, mailoutbox, settings):
        settings.ADMINS = ["admin@example.com"]
        UserFactory.create(email="dancer42@example.com")
        assert len(mailoutbox) == 1
        body = mailoutbox[0].body
        assert "dancer42@example.com" in body


# ---------------------------------------------------------------------------
# Password reset email (Django built-in RateLimitedPasswordResetView)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPasswordResetEmail:
    def test_reset_email_sent_for_existing_user(self, mailoutbox, settings):
        settings.ADMINS = []  # suppress admin signup notification
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
