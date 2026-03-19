"""Tests for events/images.py"""

import io

import pytest
from django.core.exceptions import ValidationError
from PIL import Image

from events.images import validate_and_process


def _make_upload(width=800, height=600, fmt="JPEG", name="test.jpg"):
    """Return a file-like object containing an image."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(buf, format=fmt)
    buf.seek(0)
    buf.name = name
    buf.size = buf.getbuffer().nbytes
    return buf


@pytest.mark.django_db
class TestValidateAndProcess:
    def test_returns_content_file(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload()
        result = validate_and_process(f)
        assert result is not None

    def test_output_named_photo_jpg(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload()
        result = validate_and_process(f)
        assert result.name == "photo.jpg"

    def test_output_is_jpeg(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload(fmt="PNG", name="test.png")
        result = validate_and_process(f)
        img = Image.open(io.BytesIO(result.read()))
        assert img.format == "JPEG"

    def test_image_resized_within_max_dimension(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload(width=2400, height=1800)
        result = validate_and_process(f)
        img = Image.open(io.BytesIO(result.read()))
        assert img.width <= 1200
        assert img.height <= 1200

    def test_small_image_not_upscaled(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload(width=400, height=300)
        result = validate_and_process(f)
        img = Image.open(io.BytesIO(result.read()))
        assert img.width == 400

    def test_oversized_file_raises_validation_error(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 100  # tiny limit
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        f = _make_upload()
        with pytest.raises(ValidationError, match="10 MB"):
            validate_and_process(f)

    def test_invalid_file_raises_validation_error(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        buf = io.BytesIO(b"not an image at all")
        buf.name = "bad.jpg"
        buf.size = len(b"not an image at all")
        with pytest.raises(ValidationError, match="valid image"):
            validate_and_process(buf)

    def test_rgba_converted_to_rgb(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_JPEG_QUALITY = 85
        buf = io.BytesIO()
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "rgba.png"
        buf.size = buf.getbuffer().nbytes
        result = validate_and_process(buf)
        out = Image.open(io.BytesIO(result.read()))
        assert out.mode == "RGB"
