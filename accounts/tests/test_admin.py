import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from .factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestUserAdminApproval:
    def test_approve_users_action(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        pending_users = UserFactory.create_batch(3, is_approved=False)
        client = Client()
        client.force_login(superuser)

        ids = [str(u.pk) for u in pending_users]
        response = client.post(
            "/admin/accounts/user/",
            {
                "action": "approve_users",
                "_selected_action": ids,
            },
        )
        assert response.status_code in (200, 302)
        assert User.objects.filter(pk__in=ids, is_approved=True).count() == 3

    def test_approve_users_action_skips_already_approved(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        already_approved = UserFactory.create(is_approved=True)
        pending = UserFactory.create(is_approved=False)
        client = Client()
        client.force_login(superuser)

        response = client.post(
            "/admin/accounts/user/",
            {
                "action": "approve_users",
                "_selected_action": [str(already_approved.pk), str(pending.pk)],
            },
        )
        assert response.status_code in (200, 302)
        # Both should now be approved
        already_approved.refresh_from_db()
        pending.refresh_from_db()
        assert already_approved.is_approved is True
        assert pending.is_approved is True

    def test_intro_message_visible_in_admin(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create(intro_message="Hello I love tango")
        client = Client()
        client.force_login(superuser)

        response = client.get(f"/admin/accounts/user/{user.pk}/change/")
        assert response.status_code == 200
        assert b"intro_message" in response.content
