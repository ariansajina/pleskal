"""Tests for accounts.hashers — HMAC-peppered PBKDF2 password hasher."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from accounts.hashers import HmacPepperedPasswordHasher, _apply_pepper, _get_pepper
from accounts.tests.factories import UserFactory

User = get_user_model()

_VALID_PEPPER = "ab" * 32  # 32-byte pepper as 64 hex chars
_OTHER_PEPPER = "cd" * 32


class TestGetPepper:
    def test_returns_bytes_from_valid_hex(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            key = _get_pepper()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_dev_fallback_when_empty_and_debug(self):
        with override_settings(PASSWORD_PEPPER="", DEBUG=True):
            key = _get_pepper()
        assert len(key) == 32  # all-zero dev pepper

    def test_raises_in_production_when_unset(self):
        with (
            override_settings(PASSWORD_PEPPER="", DEBUG=False),
            pytest.raises(ImproperlyConfigured, match="PASSWORD_PEPPER must be set"),
        ):
            _get_pepper()

    def test_raises_on_invalid_hex(self):
        with (
            override_settings(PASSWORD_PEPPER="not-valid-hex", DEBUG=False),
            pytest.raises(ImproperlyConfigured, match="hex-encoded"),
        ):
            _get_pepper()

    def test_raises_on_wrong_length(self):
        short_pepper = "ab" * 16  # 16 bytes, not 32
        with (
            override_settings(PASSWORD_PEPPER=short_pepper, DEBUG=False),
            pytest.raises(ImproperlyConfigured, match="32 bytes"),
        ):
            _get_pepper()


class TestApplyPepper:
    def test_returns_string(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            result = _apply_pepper("password")
        assert isinstance(result, str)

    def test_is_deterministic(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            assert _apply_pepper("password") == _apply_pepper("password")

    def test_different_passwords_give_different_output(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            assert _apply_pepper("foo") != _apply_pepper("bar")

    def test_different_peppers_give_different_output(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            a = _apply_pepper("password")
        with override_settings(PASSWORD_PEPPER=_OTHER_PEPPER, DEBUG=False):
            b = _apply_pepper("password")
        assert a != b


class TestHmacPepperedPasswordHasher:
    def setup_method(self):
        self.hasher = HmacPepperedPasswordHasher()

    def test_algorithm_identifier(self):
        assert self.hasher.algorithm == "hmac_pbkdf2_sha256"

    def test_encode_produces_algorithm_prefix(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            encoded = self.hasher.encode("password", self.hasher.salt())
        assert encoded.startswith("hmac_pbkdf2_sha256$")

    def test_verify_correct_password(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            encoded = self.hasher.encode("secret", self.hasher.salt())
            assert self.hasher.verify("secret", encoded) is True

    def test_verify_wrong_password(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            encoded = self.hasher.encode("secret", self.hasher.salt())
            assert self.hasher.verify("wrong", encoded) is False

    def test_same_password_different_salt_differs(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            enc1 = self.hasher.encode("password", self.hasher.salt())
            enc2 = self.hasher.encode("password", self.hasher.salt())
        assert enc1 != enc2

    def test_peppered_differs_from_unpeppered(self):
        """A peppered hash carries a distinct algorithm prefix."""
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            peppered_encoded = self.hasher.encode("password", self.hasher.salt())
        # Plain PBKDF2 hashes start with "pbkdf2_sha256$"; ours must not.
        assert not peppered_encoded.startswith("pbkdf2_sha256$")

    def test_wrong_pepper_fails_verification(self):
        with override_settings(PASSWORD_PEPPER=_VALID_PEPPER, DEBUG=False):
            encoded = self.hasher.encode("password", self.hasher.salt())
        with override_settings(PASSWORD_PEPPER=_OTHER_PEPPER, DEBUG=False):
            assert self.hasher.verify("password", encoded) is False


class TestHasherIntegration:
    """End-to-end tests via Django's auth layer."""

    def test_make_password_uses_peppered_hasher(self):
        with override_settings(
            PASSWORD_PEPPER=_VALID_PEPPER,
            DEBUG=False,
            PASSWORD_HASHERS=[
                "accounts.hashers.HmacPepperedPasswordHasher",
                "django.contrib.auth.hashers.PBKDF2PasswordHasher",
            ],
        ):
            encoded = make_password("mysecret")
        assert encoded.startswith("hmac_pbkdf2_sha256$")

    def test_check_password_roundtrip(self):
        with override_settings(
            PASSWORD_PEPPER=_VALID_PEPPER,
            DEBUG=False,
            PASSWORD_HASHERS=[
                "accounts.hashers.HmacPepperedPasswordHasher",
                "django.contrib.auth.hashers.PBKDF2PasswordHasher",
            ],
        ):
            encoded = make_password("correct")
            assert check_password("correct", encoded) is True
            assert check_password("wrong", encoded) is False

    @pytest.mark.django_db
    def test_hasher_is_configured_in_settings(self, settings):
        """PASSWORD_HASHERS must list HmacPepperedPasswordHasher first."""
        assert (
            settings.PASSWORD_HASHERS[0]
            == "accounts.hashers.HmacPepperedPasswordHasher"
        )

    @pytest.mark.django_db
    def test_new_user_password_stored_with_pepper_prefix(self, settings):
        settings.PASSWORD_PEPPER = _VALID_PEPPER
        user = UserFactory.create(password="testpass123")
        user.refresh_from_db()
        assert user.password.startswith("hmac_pbkdf2_sha256$")

    @pytest.mark.django_db
    def test_legacy_pbkdf2_hash_still_verifies(self, settings):
        """Existing plain PBKDF2 hashes continue to work (fallback hasher)."""
        from django.contrib.auth.hashers import PBKDF2PasswordHasher

        settings.PASSWORD_PEPPER = _VALID_PEPPER
        plain_encoded = PBKDF2PasswordHasher().encode("oldpassword", "somesalt")
        user = UserFactory.create()
        user.password = plain_encoded
        user.save(update_fields=["password"])

        assert check_password("oldpassword", user.password) is True

    @pytest.mark.django_db
    def test_authenticate_works_with_peppered_hash(self, client, settings):
        from django.urls import reverse

        settings.PASSWORD_PEPPER = _VALID_PEPPER
        UserFactory.create(email="testuser@example.com", password="mypassword")
        # Use client.post so django-axes receives a proper request object.
        resp = client.post(
            reverse("login"),
            {"username": "testuser@example.com", "password": "mypassword"},
        )
        assert resp.status_code == 302
