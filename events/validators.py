from urllib.parse import urlparse

from django.core.exceptions import ValidationError


def validate_url_scheme(value):
    """Ensure URL uses http or https scheme only."""
    if not value:
        return
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(
            "URL must use http or https scheme.",
            code="invalid_scheme",
        )
