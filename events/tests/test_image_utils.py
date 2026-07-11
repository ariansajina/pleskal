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

    def test_rgba_transparency_composited_onto_white(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        buf = io.BytesIO()
        # Fully transparent red pixel should become white, not black.
        Image.new("RGBA", (10, 10), color=(255, 0, 0, 0)).save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "rgba.png", buf.getvalue(), content_type="image/png"
        )
        result = validate_and_process(upload)
        out = Image.open(io.BytesIO(result.read())).convert("RGB")
        assert out.getpixel((5, 5)) == (255, 255, 255)

    def test_cmyk_converted_without_crashing(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        buf = io.BytesIO()
        Image.new("CMYK", (100, 100)).save(buf, format="TIFF")
        upload = SimpleUploadedFile(
            "cmyk.tiff", buf.getvalue(), content_type="image/tiff"
        )
        result = validate_and_process(upload)
        out = Image.open(io.BytesIO(result.read()))
        assert out.format == "WEBP"

    def test_palette_mode_converted(self, settings):
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        buf = io.BytesIO()
        Image.new("RGB", (50, 50)).convert("P").save(buf, format="PNG")
        upload = SimpleUploadedFile("p.png", buf.getvalue(), content_type="image/png")
        result = validate_and_process(upload)
        out = Image.open(io.BytesIO(result.read()))
        assert out.format == "WEBP"

    def test_palette_transparency_composited_onto_white(self, settings):
        """A P-mode image with a transparency index (e.g. GIF) must not
        render its transparent regions as an arbitrary dark palette color."""
        settings.MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
        settings.MAX_IMAGE_DIMENSION = 1200
        settings.IMAGE_WEBP_QUALITY = 70
        buf = io.BytesIO()
        rgba = Image.new("RGBA", (10, 10), color=(255, 0, 0, 0))
        rgba.save(buf, format="GIF")
        buf.seek(0)
        src = Image.open(buf)
        assert src.mode == "P"
        assert "transparency" in src.info

        upload = SimpleUploadedFile("p.gif", buf.getvalue(), content_type="image/gif")
        result = validate_and_process(upload)
        out = Image.open(io.BytesIO(result.read())).convert("RGB")
        assert out.getpixel((5, 5)) == (255, 255, 255)
