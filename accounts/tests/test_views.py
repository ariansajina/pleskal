import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from events.tests.factories import EventFactory

from .factories import UserFactory

User = get_user_model()


def _make_verified(user):
    """Create a verified allauth EmailAddress for the given user."""
    from allauth.account.models import EmailAddress

    EmailAddress.objects.get_or_create(
        user=user,
        email=user.email,
        defaults={"primary": True, "verified": True},
    )


@pytest.mark.django_db
class TestLoginView:
    def test_get_login_page(self):
        client = Client()
        response = client.get("/accounts/login/")
        assert response.status_code == 200

    def test_login_with_email(self):
        user = UserFactory.create(email="testuser@example.com")
        _make_verified(user)
        client = Client()
        response = client.post(
            "/accounts/login/",
            {"username": "testuser@example.com", "password": "testpass123"},
        )
        assert response.status_code == 302

    def test_login_blocked_for_unverified_email(self):
        from allauth.account.models import EmailAddress

        user = UserFactory.create(email="unverified@example.com")
        EmailAddress.objects.create(
            user=user, email=user.email, primary=True, verified=False
        )
        client = Client()
        response = client.post(
            "/accounts/login/",
            {"username": "unverified@example.com", "password": "testpass123"},
        )
        # Should not redirect to success — stays on login page (200 or re-render)
        assert response.status_code != 302 or "/accounts/login/" in response.url


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
class TestAccountProfileView:
    def test_redirects_to_publisher_profile(self):
        user = UserFactory.create(display_name="Test User")
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/profile/")
        assert response.status_code == 302
        assert user.display_name_slug in response.url

    def test_requires_login(self):
        client = Client()
        response = client.get("/accounts/profile/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url


@pytest.mark.django_db
class TestPublisherProfileView:
    def test_show_upcoming_events(self):
        user = UserFactory.create(display_name="Profile User")
        client = Client()
        response = client.get(f"/accounts/publishers/{user.display_name_slug}/")
        assert response.status_code == 200

    def test_show_past_events(self):
        user = UserFactory.create(display_name="Past Events User")
        client = Client()
        response = client.get(f"/accounts/publishers/{user.display_name_slug}/?past=1")
        assert response.status_code == 200
        assert response.context["show_past"] is True

    def test_404_for_unknown_publisher(self):
        client = Client()
        response = client.get("/accounts/publishers/no-such-user/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestEditProfileView:
    def test_get_edit_profile(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/profile/edit/")
        assert response.status_code == 200

    def test_post_valid_updates_profile(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post(
            "/accounts/profile/edit/",
            {"display_name": "New Name"},
        )
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.display_name == "New Name"

    def test_post_invalid_rerenders_form(self):
        UserFactory.create(email="taken@example.com")
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post(
            "/accounts/profile/edit/",
            {"email": "taken@example.com"},
        )
        assert response.status_code == 200


@pytest.mark.django_db
class TestChangePasswordView:
    def test_get_change_password_page(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.get("/accounts/change-password/")
        assert response.status_code == 200

    def test_post_valid_changes_password(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post(
            "/accounts/change-password/",
            {
                "old_password": "testpass123",
                "new_password1": "CorrectHorse99!",
                "new_password2": "CorrectHorse99!",
            },
        )
        assert response.status_code == 302

    def test_post_wrong_old_password_rerenders(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post(
            "/accounts/change-password/",
            {
                "old_password": "wrongpassword",
                "new_password1": "CorrectHorse99!",
                "new_password2": "CorrectHorse99!",
            },
        )
        assert response.status_code == 200


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
        response = client.get("/accounts/delete/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url
