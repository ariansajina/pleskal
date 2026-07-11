import pytest
from django.core.exceptions import ValidationError

from ..validators import validate_url_scheme


class TestValidateUrlScheme:
    def test_http_accepted(self):
        validate_url_scheme("http://example.com")

    def test_https_accepted(self):
        validate_url_scheme("https://example.com")

    def test_javascript_rejected(self):
        with pytest.raises(ValidationError, match="http or https"):
            validate_url_scheme("javascript:alert(1)")

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError, match="http or https"):
            validate_url_scheme("ftp://example.com")

    def test_empty_string_accepted(self):
        validate_url_scheme("")  # Should not raise

    def test_none_accepted(self):
        validate_url_scheme(None)  # Should not raise
