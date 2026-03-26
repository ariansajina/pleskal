import io

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()


def validate_and_process(upload) -> ContentFile:
    """
    Validates that the upload is a real image within the size limit,
    converts it to a compressed WebP, and resizes it to fit within
    MAX_IMAGE_DIMENSION on both axes. Returns a ContentFile ready
    for assignment to an ImageField.
    """
    try:
        img = Image.open(upload)
        img.verify()
        upload.seek(0)
        img = Image.open(upload)
    except Exception as exc:
        raise ValidationError("Upload a valid image file.") from exc

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.thumbnail(
        (settings.MAX_IMAGE_DIMENSION, settings.MAX_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )

    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY)
    buffer.seek(0)

    return ContentFile(buffer.read(), name="photo.webp")
