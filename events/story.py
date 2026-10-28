"""Instagram story image of an event: its list card, stood upright, on a
1080×1920 canvas.

The card keeps the look of `.card` in `templates/base.html` (light theme,
hover state: blue border and offset shadow; title, date, venue, "by" line,
badges) but stacks the photo above the text, at sizes made for a phone held
upright. Measurements are in CSS pixels scaled by SCALE; colors mirror the
`:root` tokens there, so keep them in sync when the card's design changes.
The card and the site line under it are centered between the areas
Instagram covers (progress bar and profile at the top, reply bar at the
bottom), leaving room for a link sticker, which a web page can't attach.
"""

import functools
import io
import logging
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import dateformat, timezone
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Event

logger = logging.getLogger(__name__)

STORY_SIZE = (1080, 1920)
SCALE = 2.5  # story pixels per CSS pixel
CARD_WIDTH = 352  # CSS px; 880 story px
IMAGE_HEIGHT = 224  # CSS px; 560 story px
SAFE_TOP = 250  # story px Instagram covers at the top ...
SAFE_BOTTOM = 340  # ... and at the bottom
JPEG_QUALITY = 90

FONT_DIR = Path(settings.BASE_DIR) / "static" / "fonts"
LOGO_PATH = "images/logo.png"

# :root tokens (templates/base.html)
SURFACE = (0xF4, 0xF0, 0xE8)
DOT = (51, 51, 204, 26)  # --dot, rgba(51, 51, 204, 0.10)
CARD_BG = (255, 255, 255, 230)  # --card-bg-hover, rgba(255, 255, 255, 0.9)
BLUE = (0x33, 0x33, 0xCC)
INK = (0x1A, 0x18, 0x66)
INK_MUTED = (0x3D, 0x3B, 0x8A)
BORDER = (0xAA, 0xAA, 0xDD)
BY_MUTED = (157, 155, 194)  # --ink-muted at opacity 0.5 on the card

# .badge--<category>: (color, background, border)
BADGES = {
    "performance": ((0xBE, 0x12, 0x3C), (0xFF, 0xF1, 0xF2), None),
    "workshop": ((0x25, 0x63, 0xEB), (0xEF, 0xF6, 0xFF), None),
    "worksharing": ((0x93, 0x33, 0xEA), (0xFA, 0xF5, 0xFF), None),
    "openpractice": ((0x0E, 0x74, 0x90), (0xCF, 0xFA, 0xFE), None),
    "talk": ((0x64, 0x74, 0x8B), (0xF8, 0xFA, 0xFC), None),
    "social": ((0xC2, 0x41, 0x0C), (0xFF, 0xF7, 0xED), None),
    "other": ((0x47, 0x55, 0x69), (0xF1, 0xF5, 0xF9), (0xCB, 0xD5, 0xE1)),
    "free": ((0x04, 0x78, 0x57), (0xEC, 0xFD, 0xF5), None),
    "repeat": (INK_MUTED, None, BORDER),
}


def px(css: float) -> int:
    return round(css * SCALE)


@functools.cache
def font(size_css: float, bold: bool = False) -> ImageFont.FreeTypeFont:
    weight = 700 if bold else 400
    path = FONT_DIR / f"atkinson-hyperlegible-{weight}.woff2"
    return ImageFont.truetype(str(path), px(size_css))


def line_height(f: ImageFont.FreeTypeFont) -> int:
    """CSS `line-height: normal`: the font's ascent + descent."""
    ascent, descent = f.getmetrics()
    return ascent + descent


def clamp(text: str, f: ImageFont.FreeTypeFont, width: int, lines: int) -> list[str]:
    """Word-wrap *text* to *width*, keeping at most *lines* lines and ending
    a cut-off last line with an ellipsis (`-webkit-line-clamp`)."""
    words = text.split()
    out: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if text_width(f, candidate) <= width:
            current = candidate
            continue
        if current:
            out.append(current)
        current = word
        # A word wider than the column breaks anywhere.
        while text_width(f, current) > width:
            cut = len(current)
            while cut > 1 and text_width(f, current[:cut]) > width:
                cut -= 1
            out.append(current[:cut])
            current = current[cut:]
    if current:
        out.append(current)
    if len(out) <= lines:
        return out
    last = out[lines - 1]
    while last and text_width(f, f"{last}…") > width:
        last = last[:-1]
    return [*out[: lines - 1], f"{last.rstrip()}…"]


MIDDOT = "·"  # not in Atkinson Hyperlegible; browsers fall back for it


def middot_width(f: ImageFont.FreeTypeFont) -> float:
    return f.size * 0.28


def text_width(f: ImageFont.FreeTypeFont, text: str) -> float:
    return f.getlength(text.replace(MIDDOT, "")) + text.count(MIDDOT) * middot_width(f)


def draw_text_line(draw, xy, text, f, fill, line_px, letter_spacing=0):
    """Draw *text* in a line box of *line_px* height whose top-left is *xy*,
    centering the font's content area in it as browsers do; return its width."""
    x, y = xy
    ascent, descent = f.getmetrics()
    baseline = y + (line_px - ascent - descent) / 2 + ascent
    start = x
    for i, segment in enumerate(text.split(MIDDOT)):
        if i:
            cx = x + middot_width(f) / 2
            cy = baseline - f.size * 0.3
            r = f.size * 0.065
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
            x += middot_width(f)
        if not letter_spacing:
            draw.text((x, baseline), segment, font=f, fill=fill, anchor="ls")
            x += f.getlength(segment)
            continue
        for char in segment:
            draw.text((x, baseline), char, font=f, fill=fill, anchor="ls")
            x += f.getlength(char) + letter_spacing
    return x - start


def date_parts(event: Event) -> list[str]:
    """The card's date line, as separate flex items (event_card.html)."""
    start = timezone.localtime(event.start_datetime)
    end = event.end_datetime and timezone.localtime(event.end_datetime)
    if start.strftime("%H:%M") == "00:00":
        parts = [dateformat.format(start, "D j M")]
        if event.ends_on_later_day:
            parts += ["–", dateformat.format(end, "D j M")]
        return parts
    parts = [dateformat.format(start, "D j M · H:i")]
    if end:
        end_format = "D j M · H:i" if event.ends_on_later_day else "H:i"
        parts += ["–", dateformat.format(end, end_format)]
    return parts


def badges(event: Event) -> list[tuple[str, str]]:
    out = [(str(event.category), event.get_category_display())]  # ty: ignore[unresolved-attribute]
    if event.is_free:
        out.append(("free", "Free"))
    if event.series_id:
        out.append(("repeat", "Repeats"))
    return out


def load_event_image(event: Event) -> Image.Image:
    """The event's own image, else its publisher default, else the logo."""
    if event.image:
        try:
            with event.image.open("rb") as fh:  # ty: ignore[unresolved-attribute]
                img = Image.open(fh)
                img.load()
                return img
        except Exception:
            logger.warning("Story: can't read image of event %s", event.pk)
    return Image.open(finders.find(event._default_image_path()))


def render_badge(draw, x, y, kind, label, size):
    """Draw a `.badge` at *size* CSS px (11.2 on the site) with its top-left
    at (x, y), padding and border scaled along; return its width."""
    color, background, border = BADGES.get(kind, BADGES["other"])
    f = font(size, bold=True)
    text = label.upper()
    spacing = px(size * 0.08)
    stroke = px(size * 1.5 / 11.2)
    pad_x, pad_y = px(size * 8 / 11.2), px(size * 3.2 / 11.2)
    text_w = sum(f.getlength(c) + spacing for c in text)
    width = round(text_w) + 2 * pad_x + 2 * stroke
    height = badge_height(size)
    if background:
        draw.rectangle([x, y, x + width - 1, y + height - 1], fill=background)
    draw.rectangle(
        [x, y, x + width - 1, y + height - 1], outline=border or color, width=stroke
    )
    draw_text_line(
        draw,
        (x + stroke + pad_x, y + stroke + pad_y),
        text,
        f,
        color,
        line_height(f),
        spacing,
    )
    return width


def badge_height(size: float) -> int:
    f = font(size, bold=True)
    return line_height(f) + 2 * px(size * 3.2 / 11.2) + 2 * px(size * 1.5 / 11.2)


def render_card(event: Event) -> Image.Image:
    """The event's card, photo on top, as an RGBA image."""
    border = px(2)
    pad = px(20)
    width = px(CARD_WIDTH)
    image_h = px(IMAGE_HEIGHT)
    text_w = width - 2 * border - 2 * pad

    title_font = font(28, bold=True)
    meta_font = font(17)
    badge_size = 13
    title_lh = px(28 * 1.2)
    meta_lh = line_height(meta_font)
    title = clamp(str(event.title), title_font, text_w, 3)
    venue = clamp(str(event.venue_name), meta_font, text_w, 2)
    show_by = bool(event.submitted_by) and not event.publisher_is_venue

    text_h = (
        pad
        + len(title) * title_lh
        + px(10)
        + meta_lh
        + px(4)
        + len(venue) * meta_lh
        + ((px(4) + meta_lh) if show_by else 0)
        + px(14)
        + badge_height(badge_size)
        + pad
    )
    height = border + image_h + border + text_h + border

    card = Image.new("RGBA", (width, height), CARD_BG)
    draw = ImageDraw.Draw(card)

    # Photo: object-fit: cover, over a blue rule
    try:
        img = ImageOps.exif_transpose(load_event_image(event)).convert("RGBA")
        img = ImageOps.fit(img, (width - 2 * border, image_h), Image.Resampling.LANCZOS)
        card.alpha_composite(img, (border, border))
    except Exception:
        logger.warning("Story: no image for event %s", event.pk)
    draw.rectangle(
        [0, border + image_h, width - 1, 2 * border + image_h - 1], fill=BLUE
    )

    x = border + pad
    y = 2 * border + image_h + pad
    for line in title:
        draw_text_line(draw, (x, y), line, title_font, INK, title_lh)
        y += title_lh
    y += px(10)

    # Date line: flex items with a gap, clipped to the column
    meta = Image.new("RGBA", (text_w, meta_lh))
    meta_draw = ImageDraw.Draw(meta)
    mx = 0
    for part in date_parts(event):
        mx += draw_text_line(meta_draw, (mx, 0), part, meta_font, INK_MUTED, meta_lh)
        mx += px(8)
    card.alpha_composite(meta, (x, y))
    y += meta_lh + px(4)

    for line in venue:
        draw_text_line(draw, (x, y), line, meta_font, BLUE, meta_lh)
        y += meta_lh

    if show_by:
        # "by" at opacity 0.5, then the publisher in blue
        y += px(4)
        by_w = draw_text_line(draw, (x, y), "by ", meta_font, BY_MUTED, meta_lh)
        name = clamp(
            event.submitted_by.public_name,  # ty: ignore[unresolved-attribute]
            meta_font,
            text_w - round(by_w),
            1,
        )[0]
        draw_text_line(draw, (x + round(by_w), y), name, meta_font, BLUE, meta_lh)
        y += meta_lh
    y += px(14)

    bx = x
    for kind, label in badges(event):
        bx += render_badge(draw, bx, y, kind, label, badge_size) + px(6)

    # Card border (hover state: blue)
    draw.rectangle([0, 0, width - 1, height - 1], outline=BLUE, width=border)
    return card


def dotted_background() -> Image.Image:
    """The body's dot grid: 1px dots every 22px, scaled."""
    canvas = Image.new("RGBA", STORY_SIZE, (*SURFACE, 255))
    dots = Image.new("RGBA", STORY_SIZE)
    draw = ImageDraw.Draw(dots)
    step = 22 * SCALE
    r = SCALE / 2 + 0.5
    for row in range(int(STORY_SIZE[1] / step) + 1):
        for col in range(int(STORY_SIZE[0] / step) + 1):
            cx, cy = col * step + step / 2, row * step + step / 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT)
    canvas.alpha_composite(dots)
    return canvas


def render_story(event: Event) -> bytes:
    """JPEG bytes of the event's story image."""
    canvas = dotted_background()
    draw = ImageDraw.Draw(canvas)
    width, height = STORY_SIZE

    card = render_card(event)
    shadow = px(4)

    # Under the card: the logo and the site's domain, side by side
    site_font = font(18, bold=True)
    domain = settings.SITE_DOMAIN
    logo = Image.open(finders.find(LOGO_PATH)).convert("RGBA")
    logo.thumbnail((px(36), px(36)), Image.Resampling.LANCZOS)
    gap = px(10)
    site_w = logo.width + gap + round(site_font.getlength(domain))
    site_h = logo.height

    # Center card + site line between the areas Instagram covers
    group_h = card.height + shadow + px(24) + site_h
    top = SAFE_TOP + max(0, (height - SAFE_TOP - SAFE_BOTTOM - group_h) // 2)

    card_x = (width - card.width) // 2
    # The card is translucent, so the dots show through as on the site; take
    # its backdrop before the shadow, which CSS doesn't paint under the card.
    box = (card_x, top, card_x + card.width, top + card.height)
    backdrop = canvas.crop(box)
    backdrop.alpha_composite(card)
    # .card:hover box-shadow, scaled up with the card
    draw.rectangle(
        [box[0] + shadow, box[1] + shadow, box[2] - 1 + shadow, box[3] - 1 + shadow],
        fill=BLUE,
    )
    canvas.paste(backdrop, box)

    site_x = (width - site_w) // 2
    site_y = box[3] + shadow + px(24)
    canvas.alpha_composite(logo, (site_x, site_y))
    draw.text(
        (site_x + logo.width + gap, site_y + site_h / 2),
        domain,
        font=site_font,
        fill=BLUE,
        anchor="lm",
    )

    out = io.BytesIO()
    canvas.convert("RGB").save(
        out, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True
    )
    return out.getvalue()
