from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


def validate_image_file(image):
    """Validate image format and file size using Pillow."""
    if image.size > MAX_IMAGE_SIZE:
        size_mb = image.size / (1024 * 1024)
        raise ValidationError(
            f"Image file size must be at most 10 MB. Got {size_mb:.1f} MB."
        )

    try:
        img = Image.open(image)
        img.verify()
    except Exception as exc:
        raise ValidationError("Upload a valid image file.") from exc

    # Reset file pointer after verify
    image.seek(0)

    fmt = Image.open(image).format
    image.seek(0)

    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(f"Image format must be JPEG, PNG, WebP, or HEIC. Got {fmt}.")


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
