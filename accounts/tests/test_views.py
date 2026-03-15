import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from events.tests.factories import EventFactory

from .factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestRegisterView:
    def test_get_register_page(self):
        client = Client()
        response = client.get("/accounts/register/")
        assert response.status_code == 200

    def test_register_creates_user(self):
        client = Client()
        response = client.post(
            "/accounts/register/",
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "password1": "Str0ng!Pass#",
                "password2": "Str0ng!Pass#",
            },
        )
        assert response.status_code == 302
        user = User.objects.get(email="newuser@example.com")
        assert user.is_approved is False
        assert user.is_moderator is False

    def test_register_redirects_authenticated_user(self):
        user = UserFactory()
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/register/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestLoginView:
    def test_get_login_page(self):
        client = Client()
        response = client.get("/accounts/login/")
        assert response.status_code == 200

    def test_login_with_email(self):
        user = UserFactory(email="test@example.com")
        user.set_password("testpass123")
        user.save()
        client = Client()
        response = client.post(
            "/accounts/login/",
            {"username": "test@example.com", "password": "testpass123"},
        )
        assert response.status_code == 302


@pytest.mark.django_db
class TestLogoutView:
    def test_logout(self):
        user = UserFactory()
        client = Client()
        client.force_login(user)
        response = client.post("/accounts/logout/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestPasswordResetView:
    def test_get_reset_page(self):
        client = Client()
        response = client.get("/accounts/password-reset/")
        assert response.status_code == 200

    def test_reset_always_shows_same_message(self):
        """Account enumeration hardening: always redirects."""
        client = Client()
        # Non-existent email
        response = client.post(
            "/accounts/password-reset/",
            {"email": "nonexistent@example.com"},
        )
        assert response.status_code == 302

        # Existing email
        UserFactory(email="exists@example.com")
        response = client.post(
            "/accounts/password-reset/",
            {"email": "exists@example.com"},
        )
        assert response.status_code == 302


@pytest.mark.django_db
class TestAccountDeleteView:
    def test_delete_requires_login(self):
        client = Client()
        response = client.get("/accounts/delete/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_get_delete_confirmation(self):
        user = UserFactory()
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/delete/")
        assert response.status_code == 200

    def test_delete_account(self):
        user = UserFactory()
        client = Client()
        client.force_login(user)
        response = client.post("/accounts/delete/")
        assert response.status_code == 302
        assert not User.objects.filter(pk=user.pk).exists()

    def test_delete_anonymizes_events(self):
        user = UserFactory()
        event = EventFactory(submitted_by=user)
        client = Client()
        client.force_login(user)
        client.post("/accounts/delete/")
        event.refresh_from_db()
        assert event.submitted_by is None

    def test_delete_logs_out_user(self):
        user = UserFactory()
        client = Client()
        client.force_login(user)
        client.post("/accounts/delete/")
        # After deletion, accessing a protected page should redirect to login
        response = client.get("/accounts/delete/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url
