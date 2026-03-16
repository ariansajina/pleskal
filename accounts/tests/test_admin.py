import pytest
from django.test import Client

from .factories import UserFactory


@pytest.mark.django_db
class TestUserAdmin:
    def test_intro_message_visible_in_admin(self):
        superuser = UserFactory.create(is_staff=True, is_superuser=True)
        user = UserFactory.create(intro_message="Hello I love tango")
        client = Client()
        client.force_login(superuser)

        response = client.get(f"/admin/accounts/user/{user.pk}/change/")
        assert response.status_code == 200
        assert b"intro_message" in response.content
