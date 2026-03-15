import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from ..validators import validate_image_file, validate_url_scheme


class TestValidateImageFile:
    def _make_image(self, fmt="JPEG", size=(100, 100)):
        buf = io.BytesIO()
        img = Image.new("RGB", size)
        img.save(buf, format=fmt)
        buf.seek(0)
        return SimpleUploadedFile(
            f"test.{fmt.lower()}",
            buf.read(),
            content_type=f"image/{fmt.lower()}",
        )

    def test_valid_jpeg(self):
        f = self._make_image("JPEG")
        validate_image_file(f)  # Should not raise

    def test_valid_png(self):
        f = self._make_image("PNG")
        validate_image_file(f)

    def test_valid_webp(self):
        f = self._make_image("WEBP")
        validate_image_file(f)

    def test_invalid_format_rejected(self):
        f = self._make_image("BMP")
        with pytest.raises(ValidationError, match="JPEG, PNG, or WebP"):
            validate_image_file(f)

    def test_oversized_file_rejected(self):
        # Create a file that reports size > 4MB
        f = self._make_image("JPEG")
        f.size = 5 * 1024 * 1024
        with pytest.raises(ValidationError, match="4 MB"):
            validate_image_file(f)

    def test_invalid_file_rejected(self):
        f = SimpleUploadedFile("test.jpg", b"not an image", content_type="image/jpeg")
        with pytest.raises(ValidationError, match="valid image"):
            validate_image_file(f)


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
