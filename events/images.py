import io

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

INVALID_IMAGE_MESSAGE = "Upload a valid image file."


def validate_and_process(upload) -> ContentFile:
    """
    Validates that the upload is a real image within the size limit,
    converts it to a compressed WebP, and resizes it to fit within
    MAX_IMAGE_DIMENSION on both axes. Returns a ContentFile ready
    for assignment to an ImageField.

    Memory use is bounded by MAX_IMAGE_PIXELS, checked from the header before
    any pixel data is decoded: a small, highly compressible file (e.g. a
    blank 12000x12000 PNG) otherwise decodes to gigabytes of pixels.
    """
    try:
        img = Image.open(upload)
        img.verify()
        upload.seek(0)
        img = Image.open(upload)
    except Exception as exc:
        raise ValidationError(INVALID_IMAGE_MESSAGE) from exc

    max_dimension = settings.MAX_IMAGE_DIMENSION
    if img.format == "JPEG":
        # JPEG can decode directly at 1/2, 1/4 or 1/8 scale; pick the smallest
        # scale that still covers the output size, so big camera photos are
        # never decoded at full resolution (this also shrinks img.size).
        img.draft(img.mode, (max_dimension, max_dimension))

    width, height = img.size
    if width * height > settings.MAX_IMAGE_PIXELS:
        raise ValidationError(
            "Image resolution is too high "
            f"(max {settings.MAX_IMAGE_PIXELS // 1_000_000} megapixels)."
        )

    try:
        if img.mode in ("LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            # Palette images can carry transparency via a "transparency" info
            # key rather than an alpha channel; promote to RGBA so it's
            # composited below instead of falling through to a flat RGB
            # convert (which renders the transparent regions as whatever
            # arbitrary palette color sits at the transparency index — often
            # black — instead of white).
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA"):
            # Covers P (no transparency), CMYK, I;16, L, 1, etc. — anything
            # WebP can't encode directly.
            img = img.convert("RGB")

        # Downscale before compositing so the alpha pass below only ever
        # touches at most MAX_IMAGE_DIMENSION² pixels.
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.getchannel("A"))
            img = background

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY)
    except OSError as exc:
        # Truncated/corrupt pixel data only surfaces once it is decoded.
        raise ValidationError(INVALID_IMAGE_MESSAGE) from exc
    buffer.seek(0)

    return ContentFile(buffer.read(), name="photo.webp")
