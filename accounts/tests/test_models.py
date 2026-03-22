import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from .factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestUserModel:
    def test_uuid_primary_key(self):
        user = UserFactory.create()
        assert isinstance(user.pk, uuid.UUID)

    def test_email_unique(self):
        UserFactory.create(email="dupe@example.com")
        with pytest.raises(IntegrityError):
            UserFactory.create(email="dupe@example.com")

    def test_str_returns_email(self):
        user = UserFactory.create(email="dancer@example.com")
        assert "dancer" in str(user)

    def test_username_field_is_email(self):
        assert User.USERNAME_FIELD == "email"

    def test_required_fields_is_empty(self):
        assert User.REQUIRED_FIELDS == []

    def test_display_name_slug_auto_generated(self):
        user = UserFactory.create(display_name="Anna Møller")
        assert user.display_name_slug != ""

    def test_display_name_slug_unique(self):
        user1 = UserFactory.create(display_name="Same Name")
        user2 = UserFactory.create(display_name="Same Name")
        assert user1.display_name_slug != user2.display_name_slug

    def test_display_name_slug_falls_back_to_email_prefix(self):
        user = UserFactory.create(email="beatrice@example.com", display_name="")
        assert "beatrice" in user.display_name_slug


@pytest.mark.django_db
class TestUserManager:
    def test_create_user_requires_email(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(email=None, password="pass")

    def test_create_user_defaults(self):
        user = User.objects.create_user(email="new@example.com", password="pass123")
        assert user.is_staff is False

    def test_create_superuser_defaults(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="pass123"
        )
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_create_superuser_requires_email(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_superuser(email=None, password="pass")
