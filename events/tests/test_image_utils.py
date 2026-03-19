"""Tests for events/images.py"""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from events.images import validate_and_process


def _make_upload(
    width=800, height=600, fmt="JPEG", name="test.jpg"
) -> SimpleUploadedFile:
    """Return a SimpleUploadedFile containing an image."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(buf, format=fmt)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


@pytest.mark.django_db
class TestValidateAndProcess:
    def test_returns_content_file(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        result = validate_and_process(_make_upload())
        assert result is not None

    def test_output_named_photo_webp(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        result = validate_and_process(_make_upload())
        assert result.name == "photo.webp"

    def test_output_is_webp(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        result = validate_and_process(_make_upload(fmt="PNG", name="test.png"))
        img = Image.open(io.BytesIO(result.read()))
        assert img.format == "WEBP"

    def test_image_resized_within_max_dimension(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        result = validate_and_process(_make_upload(width=2400, height=1800))
        img = Image.open(io.BytesIO(result.read()))
        assert img.width <= 1200
        assert img.height <= 1200

    def test_small_image_not_upscaled(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        result = validate_and_process(_make_upload(width=400, height=300))
        img = Image.open(io.BytesIO(result.read()))
        assert img.width == 400

    def test_oversized_file_raises_validation_error(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 100  # tiny limit
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        with pytest.raises(ValidationError, match="10 MB"):
            validate_and_process(_make_upload())

    def test_invalid_file_raises_validation_error(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        bad = SimpleUploadedFile(
            "bad.jpg", b"not an image at all", content_type="image/jpeg"
        )
        with pytest.raises(ValidationError, match="valid image"):
            validate_and_process(bad)

    def test_rgba_converted_to_rgb(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        buf = io.BytesIO()
        Image.new("RGBA", (100, 100), color=(255, 0, 0, 128)).save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "rgba.png", buf.getvalue(), content_type="image/png"
        )
        result = validate_and_process(upload)
        out = Image.open(io.BytesIO(result.read()))
        assert out.mode == "RGB"
