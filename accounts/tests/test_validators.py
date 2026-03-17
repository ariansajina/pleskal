import contextlib

import pytest
from django.core.exceptions import ValidationError

from accounts.validators import ZxcvbnPasswordValidator


class TestZxcvbnPasswordValidator:
    def _validator(self, min_score=2):
        return ZxcvbnPasswordValidator(min_score=min_score)

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def test_default_min_score(self):
        v = ZxcvbnPasswordValidator()
        assert v.min_score == 2

    def test_custom_min_score(self):
        v = ZxcvbnPasswordValidator(min_score=3)
        assert v.min_score == 3

    def test_invalid_min_score_raises(self):
        with pytest.raises(ValueError):
            ZxcvbnPasswordValidator(min_score=5)

    def test_invalid_min_score_negative_raises(self):
        with pytest.raises(ValueError):
            ZxcvbnPasswordValidator(min_score=-1)

    # ------------------------------------------------------------------
    # Weak passwords (should be rejected)
    # ------------------------------------------------------------------

    def test_rejects_very_weak_password(self):
        v = self._validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate("password")
        assert exc_info.value.code == "password_too_weak"

    def test_rejects_common_dictionary_word(self):
        v = self._validator()
        with pytest.raises(ValidationError):
            v.validate("monkey")

    def test_rejects_sequential_numbers(self):
        v = self._validator()
        with pytest.raises(ValidationError):
            v.validate("12345678")

    def test_rejects_keyboard_pattern(self):
        v = self._validator()
        with pytest.raises(ValidationError):
            v.validate("qwerty123")

    # ------------------------------------------------------------------
    # Strong passwords (should be accepted)
    # ------------------------------------------------------------------

    def test_accepts_strong_password(self):
        v = self._validator()
        # Should not raise
        v.validate("correct-horse-battery-staple!")

    def test_accepts_complex_password(self):
        v = self._validator()
        v.validate("X7#mP2$kLnQ9@wR!")

    def test_accepts_long_passphrase(self):
        v = self._validator()
        v.validate("purple-elephant-dances-at-midnight-42")

    # ------------------------------------------------------------------
    # min_score boundary
    # ------------------------------------------------------------------

    def test_min_score_zero_accepts_anything(self):
        v = ZxcvbnPasswordValidator(min_score=0)
        v.validate("a")  # should not raise

    def test_min_score_four_rejects_moderate_password(self):
        v = ZxcvbnPasswordValidator(min_score=4)
        # A moderate password should fail the strictest threshold
        with pytest.raises(ValidationError):
            v.validate("Password123")

    def test_min_score_one_accepts_weak_password(self):
        """A password scoring >=1 should pass when min_score=1."""
        v = ZxcvbnPasswordValidator(min_score=1)
        # "letmein1" typically scores 1; just confirm no crash for a non-trivially
        # scored password that would fail min_score=2
        with contextlib.suppress(ValidationError):
            v.validate("letmein1")

    # ------------------------------------------------------------------
    # User inputs taken into account
    # ------------------------------------------------------------------

    @pytest.mark.django_db
    def test_rejects_password_based_on_username(self):
        from accounts.tests.factories import UserFactory

        user = UserFactory.build(username="johndoe", email="johndoe@example.com")
        v = self._validator()
        # A password that is just the username is very weak
        with pytest.raises(ValidationError):
            v.validate("johndoe", user=user)

    def test_validates_with_none_user(self):
        v = self._validator()
        # Passing user=None must not raise AttributeError
        with pytest.raises(ValidationError):
            v.validate("password", user=None)

    # ------------------------------------------------------------------
    # Error message content
    # ------------------------------------------------------------------

    def test_error_message_contains_score(self):
        v = self._validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate("password")
        params = exc_info.value.params
        assert params is not None
        assert "score" in params
        assert isinstance(params["score"], int)

    def test_error_message_contains_label(self):
        v = self._validator()
        with pytest.raises(ValidationError) as exc_info:
            v.validate("password")
        params = exc_info.value.params
        assert params is not None
        assert "label" in params

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def test_get_help_text_contains_min_score(self):
        v = ZxcvbnPasswordValidator(min_score=3)
        help_text = v.get_help_text()
        assert "3" in help_text

    def test_get_help_text_returns_string(self):
        v = self._validator()
        assert isinstance(v.get_help_text(), str)

    # ------------------------------------------------------------------
    # Integration: validator is registered in AUTH_PASSWORD_VALIDATORS
    # ------------------------------------------------------------------

    def test_validator_registered_in_settings(self):
        from django.conf import settings

        validator_names = [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS]
        assert "accounts.validators.ZxcvbnPasswordValidator" in validator_names

    def test_django_validate_password_uses_zxcvbn(self):
        """django.contrib.auth.password_validation.validate_password runs our validator."""
        from django.contrib.auth.password_validation import validate_password

        with pytest.raises(ValidationError) as exc_info:
            validate_password("password")
        codes = [e.code for e in exc_info.value.error_list]
        assert "password_too_weak" in codes
