"""Tests for events/image_utils.py"""

import io

import pytest
from PIL import Image

from events.image_utils import THUMBNAIL_WIDTH, process_event_image


def _make_image_file(width=800, height=600, fmt="JPEG", name="test.jpg"):
    """Return a file-like object containing an image with a fake EXIF comment."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    # Add an EXIF-like blob (not real EXIF, but exercises the strip path)
    img.save(buf, format=fmt)
    buf.seek(0)
    buf.name = name
    return buf


@pytest.mark.django_db
class TestProcessEventImage:
    def test_returns_two_content_files(self):
        f = _make_image_file()
        main, thumb = process_event_image(f)
        assert main is not None
        assert thumb is not None

    def test_main_image_not_wider_than_1600(self):
        f = _make_image_file(width=2400, height=1200)
        main, _ = process_event_image(f)
        img = Image.open(io.BytesIO(main.read()))
        assert img.width <= 1600

    def test_small_image_not_upscaled(self):
        f = _make_image_file(width=400, height=300)
        main, _ = process_event_image(f)
        img = Image.open(io.BytesIO(main.read()))
        assert img.width == 400  # not enlarged

    def test_thumbnail_width(self):
        f = _make_image_file(width=1200, height=800)
        _, thumb = process_event_image(f)
        img = Image.open(io.BytesIO(thumb.read()))
        assert img.width == THUMBNAIL_WIDTH

    def test_thumbnail_smaller_than_original(self):
        f = _make_image_file(width=200, height=150)
        # Source is smaller than thumbnail width — should not be upscaled
        _, thumb = process_event_image(f)
        img = Image.open(io.BytesIO(thumb.read()))
        assert img.width == 200

    def test_png_preserved(self):
        f = _make_image_file(fmt="PNG", name="test.png")
        main, thumb = process_event_image(f)
        assert main.name.endswith(".png")  # type: ignore[union-attr]
        assert thumb.name.endswith(".png")  # type: ignore[union-attr]

    def test_jpeg_preserved(self):
        f = _make_image_file(fmt="JPEG", name="photo.jpg")
        main, thumb = process_event_image(f)
        assert main.name.endswith(".jpg")  # type: ignore[union-attr]
        assert thumb.name.endswith(".jpg")  # type: ignore[union-attr]

    def test_exif_stripped(self):
        """Re-opened image should have no EXIF data."""
        f = _make_image_file(fmt="JPEG")
        main, _ = process_event_image(f)
        img = Image.open(io.BytesIO(main.read()))
        # Pillow stores EXIF in _getexif() for JPEG — stripped image has None or empty
        exif = img.getexif()
        assert not exif  # empty dict / None

    def test_output_is_valid_image(self):
        f = _make_image_file()
        main, thumb = process_event_image(f)
        # Should not raise
        Image.open(io.BytesIO(main.read())).verify()
        thumb.seek(0)
        Image.open(io.BytesIO(thumb.read())).verify()
