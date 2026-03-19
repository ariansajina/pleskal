"""Image processing utilities: EXIF stripping, resizing, WebP conversion."""

import io

from django.core.files.base import ContentFile
from PIL import Image

MAX_WIDTH = 1600
THUMBNAIL_WIDTH = 400
WEBP_QUALITY = 70


def _resize_to_width(img: Image.Image, width: int) -> Image.Image:
    """Return a copy of img scaled to the given width, preserving aspect ratio."""
    if img.width <= width:
        return img.copy()
    ratio = width / img.width
    new_height = int(img.height * ratio)
    return img.resize((width, new_height), Image.Resampling.LANCZOS)


def _strip_exif_and_save_webp(img: Image.Image) -> bytes:
    """Re-save image as WebP without EXIF metadata."""
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    if clean.mode in ("RGBA", "P"):
        clean = clean.convert("RGB")
    buf = io.BytesIO()
    clean.save(buf, format="WEBP", quality=WEBP_QUALITY)
    buf.seek(0)
    return buf.read()


def process_event_image(image_file) -> tuple[ContentFile, ContentFile]:
    """
    Process an uploaded image:
      1. Open and decode fully.
      2. Strip EXIF by re-saving pixel data only.
      3. Resize main image to max 1600px wide.
      4. Generate 400px-wide thumbnail.
      5. Save both as WebP (quality=82).

    Returns (processed_image_content_file, thumbnail_content_file).
    """
    image_file.seek(0)
    img = Image.open(image_file)
    img.load()  # fully decode (needed before EXIF strip)

    original_name = getattr(image_file, "name", "image")
    stem = original_name.rsplit(".", 1)[0] if "." in original_name else original_name

    # --- Main image: resize + strip EXIF + WebP ---
    main_img = _resize_to_width(img, MAX_WIDTH)
    main_bytes = _strip_exif_and_save_webp(main_img)
    main_file = ContentFile(main_bytes, name=f"{stem}.webp")

    # --- Thumbnail: 400px wide + strip EXIF + WebP ---
    thumb_img = _resize_to_width(img, THUMBNAIL_WIDTH)
    thumb_bytes = _strip_exif_and_save_webp(thumb_img)
    thumb_file = ContentFile(thumb_bytes, name=f"{stem}_thumb.webp")

    return main_file, thumb_file
