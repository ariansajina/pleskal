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

    if img.mode == "P" and "transparency" in img.info:
        # Palette images can carry transparency via a "transparency" info key
        # rather than an alpha channel; promote to RGBA first so it's handled
        # by the compositing branch below instead of falling through to a
        # flat RGB convert (which renders the transparent regions as whatever
        # arbitrary palette color sits at the transparency index — often
        # black — instead of white).
        img = img.convert("RGBA")

    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.convert("RGBA").getchannel("A"))
        img = background
    elif img.mode != "RGB":
        # Covers P (no transparency), CMYK, I;16, L, 1, etc. — anything WebP
        # can't encode directly.
        img = img.convert("RGB")

    img.thumbnail(
        (settings.MAX_IMAGE_DIMENSION, settings.MAX_IMAGE_DIMENSION),
        Image.Resampling.LANCZOS,
    )

    buffer = io.BytesIO()
    try:
        img.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY)
    except OSError as exc:
        raise ValidationError("Upload a valid image file.") from exc
    buffer.seek(0)

    return ContentFile(buffer.read(), name="photo.webp")
