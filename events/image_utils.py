"""Image processing utilities: EXIF stripping, resizing, thumbnail generation."""

import io

from django.core.files.base import ContentFile
from PIL import Image

MAX_WIDTH = 1600
THUMBNAIL_WIDTH = 400


def _resize_to_width(img: Image.Image, width: int) -> Image.Image:
    """Return a copy of img scaled to the given width, preserving aspect ratio."""
    if img.width <= width:
        return img.copy()
    ratio = width / img.width
    new_height = int(img.height * ratio)
    return img.resize((width, new_height), Image.LANCZOS)


def _strip_exif_and_save(img: Image.Image, fmt: str) -> bytes:
    """Re-save image data without EXIF by copying pixel data only."""
    # Reconstruct image from raw bytes — this drops all metadata/EXIF.
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    buf = io.BytesIO()
    save_fmt = "JPEG" if fmt == "JPEG" else fmt
    if img.mode in ("RGBA", "P") and save_fmt == "JPEG":
        clean = clean.convert("RGB")
    clean.save(buf, format=save_fmt, optimize=True)
    buf.seek(0)
    return buf.read()


def process_event_image(image_file) -> tuple[ContentFile, ContentFile]:
    """
    Process an uploaded image:
      1. Open and verify format.
      2. Strip EXIF by re-saving pixel data only.
      3. Resize main image to max 1600px wide.
      4. Generate 400px-wide thumbnail.

    Returns (processed_image_content_file, thumbnail_content_file).
    The filenames use the original name stem with .jpg / .webp / .png extension
    matching the source format.
    """
    image_file.seek(0)
    img = Image.open(image_file)
    img.load()  # fully decode (needed before EXIF strip)
    fmt = img.format or "JPEG"  # preserve original format

    # Map Pillow format names to file extensions
    ext_map = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    ext = ext_map.get(fmt, "jpg")

    original_name = getattr(image_file, "name", "image")
    stem = original_name.rsplit(".", 1)[0] if "." in original_name else original_name

    # --- Main image: resize + strip EXIF ---
    main_img = _resize_to_width(img, MAX_WIDTH)
    main_bytes = _strip_exif_and_save(main_img, fmt)
    main_file = ContentFile(main_bytes, name=f"{stem}.{ext}")

    # --- Thumbnail: 400px wide + strip EXIF ---
    thumb_img = _resize_to_width(img, THUMBNAIL_WIDTH)
    thumb_bytes = _strip_exif_and_save(thumb_img, fmt)
    thumb_file = ContentFile(thumb_bytes, name=f"{stem}_thumb.{ext}")

    return main_file, thumb_file
