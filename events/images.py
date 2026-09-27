import hashlib
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
        img = _to_rgb_or_rgba(img)
        # Downscale before compositing so the alpha pass below only ever
        # touches at most MAX_IMAGE_DIMENSION² pixels.
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        img = _flatten_alpha(img)

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY)
    except OSError as exc:
        # Truncated/corrupt pixel data only surfaces once it is decoded.
        raise ValidationError(INVALID_IMAGE_MESSAGE) from exc
    buffer.seek(0)

    return ContentFile(buffer.read(), name="photo.webp")


def _to_rgb_or_rgba(img):
    """Convert *img* to RGB, or RGBA when it carries transparency."""
    if img.mode in ("LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        # Palette images can carry transparency via a "transparency" info
        # key rather than an alpha channel; promote to RGBA so it's
        # composited by _flatten_alpha instead of falling through to a flat
        # RGB convert (which renders the transparent regions as whatever
        # arbitrary palette color sits at the transparency index — often
        # black — instead of white).
        return img.convert("RGBA")
    if img.mode not in ("RGB", "RGBA"):
        # Covers P (no transparency), CMYK, I;16, L, 1, etc. — anything
        # WebP can't encode directly.
        return img.convert("RGB")
    return img


def _flatten_alpha(img):
    """Composite an RGBA image onto white; other images pass through."""
    if img.mode != "RGBA":
        return img
    background = Image.new("RGB", img.size, (255, 255, 255))
    background.paste(img, mask=img.getchannel("A"))
    return background


# Event list cards show the image at 150px wide (90px on phones) and at least
# 130px tall, cropped to fill. Scaling the *shorter* side to this covers a
# card up to ~180px tall at 2x pixel density, whatever the image's shape.
THUMBNAIL_MIN_SIDE = 360
THUMBNAIL_DIR = "events/thumbs"


def make_thumbnail(fileobj) -> bytes:
    """Return a WebP list-card thumbnail of the image in *fileobj*.

    The shorter side is scaled down to THUMBNAIL_MIN_SIDE (smaller images
    keep their size). Raises on unreadable images.
    """
    with Image.open(fileobj) as img:
        if img.format == "JPEG":
            # Decode at the smallest 1/2^n scale that still covers the target.
            img.draft(img.mode, (THUMBNAIL_MIN_SIDE, THUMBNAIL_MIN_SIDE))
        width, height = img.size
        if width * height > settings.MAX_IMAGE_PIXELS:
            raise ValueError(f"Image too large to thumbnail ({width}x{height})")
        thumb = _to_rgb_or_rgba(img)
        scale = THUMBNAIL_MIN_SIDE / min(width, height)
        if scale < 1:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            thumb = thumb.resize(size, Image.Resampling.LANCZOS)
        thumb = _flatten_alpha(thumb)
        buffer = io.BytesIO()
        thumb.save(buffer, format="WEBP", quality=settings.IMAGE_WEBP_QUALITY)
    return buffer.getvalue()


def store_thumbnail(image_file) -> str:
    """Generate a thumbnail for the stored *image_file*; return its storage name.

    Thumbnails are content-addressed (events/thumbs/<sha256>.webp), so the
    same picture is only ever stored once, and a name always denotes the same
    pixels.
    """
    storage = image_file.storage
    with storage.open(image_file.name, "rb") as fileobj:
        data = make_thumbnail(fileobj)
    name = f"{THUMBNAIL_DIR}/{hashlib.sha256(data).hexdigest()}.webp"
    if storage.exists(name):
        return name
    return storage.save(name, ContentFile(data, name=name))
