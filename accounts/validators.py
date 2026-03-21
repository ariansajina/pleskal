import zxcvbn
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

# Minimum zxcvbn score (0–4) required for a password to be accepted.
# Score 2 = "somewhat guessable" — good enough for typical web apps.
# Set ZXCVBN_MIN_SCORE in settings to override.
DEFAULT_MIN_SCORE = 2

SCORE_LABELS = {
    0: _("very weak"),
    1: _("weak"),
    2: _("fair"),
    3: _("strong"),
    4: _("very strong"),
}


class ZxcvbnPasswordValidator:
    """
    Password validator that uses zxcvbn to enforce a minimum strength score.

    Configured via AUTH_PASSWORD_VALIDATORS OPTIONS:
        "OPTIONS": {"min_score": 3}   # require "strong" passwords
    """

    def __init__(self, min_score: int = DEFAULT_MIN_SCORE):
        if min_score not in range(5):
            raise ValueError("min_score must be an integer between 0 and 4.")
        self.min_score = min_score

    def validate(self, password: str, user=None) -> None:
        user_inputs = []
        if user is not None:
            for attr in ("email", "display_name"):
                value = getattr(user, attr, None)
                if value:
                    user_inputs.append(value)

        result = zxcvbn.zxcvbn(password, user_inputs=user_inputs)
        score = result["score"]

        if score < self.min_score:
            feedback_parts = []
            feedback = result.get("feedback", {})
            if feedback.get("warning"):
                feedback_parts.append(feedback["warning"])
            feedback_parts.extend(feedback.get("suggestions", []))

            hint = " ".join(feedback_parts) if feedback_parts else ""
            label = SCORE_LABELS.get(score, _("weak"))

            raise ValidationError(
                _(
                    "This password is %(label)s (strength %(score)d/4). %(hint)s"
                ).strip(),
                code="password_too_weak",
                params={"label": label, "score": score, "hint": hint},
            )

    def get_help_text(self) -> str:
        return _(
            "Choose a strong, memorable password — avoid names, dates, and common words. "
            "I recommend using a password manager to generate and store a unique password."
        )
