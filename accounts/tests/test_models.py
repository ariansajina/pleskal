import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from .factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestUserModel:
    def test_uuid_primary_key(self):
        user = UserFactory()
        assert isinstance(user.pk, uuid.UUID)

    def test_default_is_approved_false(self):
        user = UserFactory()
        assert user.is_approved is False

    def test_default_is_moderator_false(self):
        user = UserFactory()
        assert user.is_moderator is False

    def test_email_unique(self):
        UserFactory(email="dupe@example.com")
        with pytest.raises(IntegrityError):
            UserFactory(email="dupe@example.com")

    def test_str_returns_username(self):
        user = UserFactory(username="dancer")
        assert str(user) == "dancer"

    def test_username_field_is_email(self):
        assert User.USERNAME_FIELD == "email"

    def test_required_fields_includes_username(self):
        assert "username" in User.REQUIRED_FIELDS


@pytest.mark.django_db
class TestUserManager:
    def test_create_user_requires_email(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(username="nomail", email=None, password="pass")

    def test_create_user_defaults(self):
        user = User.objects.create_user(
            username="newuser", email="new@example.com", password="pass123"
        )
        assert user.is_approved is False
        assert user.is_moderator is False
        assert user.is_staff is False

    def test_create_superuser_defaults(self):
        user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass123"
        )
        assert user.is_approved is True
        assert user.is_moderator is True
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_create_superuser_requires_email(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_superuser(username="admin", email=None, password="pass")
