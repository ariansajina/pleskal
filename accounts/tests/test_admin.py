import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.test import Client

from .factories import UserFactory


@pytest.mark.django_db
class TestUserAdmin:
    def test_user_change_page_loads(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create(display_name="Tango Dancer")
        client = Client()
        client.force_login(superuser)

        response = client.get(f"/admin/accounts/user/{user.pk}/change/")
        assert response.status_code == 200
        assert b"display_name" in response.content

    def _post_action(self, client, action, user_pks):
        return client.post(
            "/admin/accounts/user/",
            {
                "action": action,
                "_selected_action": [str(pk) for pk in user_pks],
            },
            follow=True,
        )

    def test_resend_verification_email_sends_to_unverified_user(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create()
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=False
        )
        client = Client()
        client.force_login(superuser)

        response = self._post_action(client, "resend_verification_email", [user.pk])

        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert user.email in mail.outbox[0].to
        assert b"Sent 1 verification email" in response.content

    def test_resend_verification_email_skips_verified_user(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create()
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=True
        )
        client = Client()
        client.force_login(superuser)

        response = self._post_action(client, "resend_verification_email", [user.pk])

        assert response.status_code == 200
        assert len(mail.outbox) == 0
        assert b"Skipped 1 user" in response.content

    def test_resend_verification_email_skips_user_without_email_record(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create()
        client = Client()
        client.force_login(superuser)

        response = self._post_action(client, "resend_verification_email", [user.pk])

        assert response.status_code == 200
        assert len(mail.outbox) == 0
        assert b"Skipped 1 user" in response.content

    def test_resend_verification_email_mixed_users(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        unverified = UserFactory.create()
        verified = UserFactory.create()
        EmailAddress.objects.create(
            user=unverified, email=unverified.email, primary=True, verified=False
        )
        EmailAddress.objects.create(
            user=verified, email=verified.email, primary=True, verified=True
        )
        client = Client()
        client.force_login(superuser)

        response = self._post_action(
            client,
            "resend_verification_email",
            [unverified.pk, verified.pk],
        )

        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert unverified.email in mail.outbox[0].to
        assert b"Sent 1 verification email" in response.content
        assert b"Skipped 1 user" in response.content
