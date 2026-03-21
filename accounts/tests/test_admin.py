import pytest
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
