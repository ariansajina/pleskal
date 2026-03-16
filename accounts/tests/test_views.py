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
                "intro_message": "I love dancing and want to share events.",
            },
        )
        assert response.status_code == 302
        user = User.objects.get(email="newuser@example.com")
        assert user.is_approved is False
        assert user.is_moderator is False

    def test_register_saves_intro_message(self):
        client = Client()
        client.post(
            "/accounts/register/",
            {
                "username": "newuser2",
                "email": "newuser2@example.com",
                "password1": "Str0ng!Pass#",
                "password2": "Str0ng!Pass#",
                "intro_message": "I organise salsa nights.",
            },
        )
        user = User.objects.get(email="newuser2@example.com")
        assert user.intro_message == "I organise salsa nights."

    def test_register_redirects_to_pending_page(self):
        client = Client()
        response = client.post(
            "/accounts/register/",
            {
                "username": "newuser3",
                "email": "newuser3@example.com",
                "password1": "Str0ng!Pass#",
                "password2": "Str0ng!Pass#",
                "intro_message": "Dancing enthusiast.",
            },
        )
        assert response.status_code == 302
        assert response.url == "/accounts/register/pending/"

    def test_register_requires_intro_message(self):
        client = Client()
        response = client.post(
            "/accounts/register/",
            {
                "username": "newuser4",
                "email": "newuser4@example.com",
                "password1": "Str0ng!Pass#",
                "password2": "Str0ng!Pass#",
                "intro_message": "",
            },
        )
        assert response.status_code == 200
        assert not User.objects.filter(email="newuser4@example.com").exists()


@pytest.mark.django_db
class TestRegistrationPendingView:
    def test_get_pending_page(self):
        client = Client()
        response = client.get("/accounts/register/pending/")
        assert response.status_code == 200

    def test_register_redirects_authenticated_user(self):
        user = UserFactory.create()
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
        user = UserFactory.create(email="test@example.com")
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
        user = UserFactory.create()
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
        UserFactory.create(email="exists@example.com")
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
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/delete/")
        assert response.status_code == 200

    def test_delete_account(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post("/accounts/delete/")
        assert response.status_code == 302
        assert not User.objects.filter(pk=user.pk).exists()

    def test_delete_anonymizes_events(self):
        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client = Client()
        client.force_login(user)
        client.post("/accounts/delete/")
        event.refresh_from_db()
        assert event.submitted_by is None

    def test_delete_with_delete_posts_removes_events(self):
        from events.models import Event

        user = UserFactory.create()
        event = EventFactory.create(submitted_by=user)
        client = Client()
        client.force_login(user)
        client.post("/accounts/delete/", {"delete_posts": "1"})
        assert not Event.objects.filter(pk=event.pk).exists()

    def test_delete_logs_out_user(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        client.post("/accounts/delete/")
        # After deletion, accessing a protected page should redirect to login
        response = client.get("/accounts/delete/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url
