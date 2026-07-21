"""Scraper for https://www.taarnby.art/kunstnere-1

Tårnby Park Studio is a one-page, once-a-year performance festival site
built on Squarespace. There is no API and no per-event detail page — every
artist/piece is a hand-formatted "section" on a single long page, with
inconsistent Danish/English labels (TID vs HVORNÅR, "HVOR:" vs "HVOR",
typos, missing years, TBA times, week-long installations, etc).

This scraper is deliberately tailored to this year's fixed program rather
than written as a fully general HTML parser: the festival page is rewritten
from scratch for each edition, so a handful of hardcoded lookups (category
mapping, a couple of title/byline swaps) are an acceptable trade-off for a
site that will only ever be scraped for the few weeks leading up to this
edition's dates.

Usage:
    uv run python scrapers/taornby.py
    uv run python scrapers/taornby.py --output events.json
    uv run python scrapers/taornby.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from typing import NamedTuple

from bs4 import BeautifulSoup, NavigableString, Tag

from scrapers.base import build_arg_parser, make_session, write_output

BASE_URL = "https://www.taarnby.art"
PROGRAM_URL = f"{BASE_URL}/kunstnere-1"
EXTERNAL_SOURCE = "taornby"
DEFAULT_VENUE = "Tårnbyparken"
# The festival is in Tårnby municipality, not Copenhagen -- Event's default
# geocoding query assumes Copenhagen when no address is given, which is wrong
# here, so every record supplies its own full, self-contained address.
VENUE_MUNICIPALITY = "Tårnby, Denmark"
DEFAULT_TIME = datetime.time(12, 0)
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

log = logging.getLogger(__name__)

# Meta labels are always rendered fully uppercase (bold, accent-colored) in
# the source markup, so matching case-sensitively avoids false positives
# from ordinary Danish prose words like lowercase "hvor" ("where").
_LABEL_PATTERN = re.compile(
    r"\b(TID|HVORN[ÅA]R|HVOR|L[ÆA]NGDE|VARIGHED|ALDER|SPROG|GENRE|INDVIELSE)\b:?"
)

_DATE_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
_RANGE_TIME_RE = re.compile(
    r"(\d{1,2})\s*[.:]\s*(\d{1,2})\s*-\s*(\d{1,2})\s*[.:]\s*(\d{1,2})"
)
_SINGLE_TIME_RE = re.compile(
    r"(?:kl\.?:?\s*)?(\d{1,2})\s*[.:]\s*(\d{1,2})", re.IGNORECASE
)
_HAS_TIME_MARKER_RE = re.compile(r"\bkl\b|\d{1,2}[.:]\d{2}", re.IGNORECASE)
_HOURS_RE = re.compile(r"(\d+)\s*tim", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*min", re.IGNORECASE)

_DANISH_STOPWORDS = {
    "og",
    "er",
    "en",
    "et",
    "som",
    "med",
    "for",
    "til",
    "af",
    "der",
    "denne",
    "dette",
    "ikke",
    "på",
    "fra",
    "de",
    "du",
    "jeg",
    "han",
    "hun",
    "vi",
    "har",
    "kan",
    "skal",
    "vil",
    "men",
    "også",
    "så",
    "hvor",
    "når",
    "hvad",
    "hvem",
    "hvorfor",
    "hvordan",
    "man",
    "sig",
    "være",
    "blev",
    "bliver",
    "været",
    "alle",
    "ind",
    "ud",
    "op",
    "ned",
    "intet",
    "ingen",
    "ender",
    "aldrig",
    "altid",
    "nogensinde",
    "meget",
    "mere",
    "mest",
    "godt",
    "bedre",
    "her",
    "nu",
    "da",
    "om",
    "over",
    "under",
    "mellem",
    "uden",
    "efter",
    "før",
    "mod",
    "hos",
    "sin",
    "sit",
    "sine",
    "deres",
    "vores",
    "jeres",
    "dens",
    "dets",
    "ved",
    "kun",
    "selv",
    "alt",
    "noget",
    "nogen",
    "andre",
    "anden",
    "sådan",
    "endnu",
    "stadig",
    "vist",
    "jo",
    "nok",
    "helt",
}
_ENGLISH_STOPWORDS = {
    "the",
    "and",
    "is",
    "of",
    "in",
    "with",
    "for",
    "an",
    "a",
    "to",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "be",
    "by",
    "as",
    "on",
    "at",
    "it",
    "its",
    "their",
    "they",
    "we",
    "you",
    "he",
    "she",
}

# Series/company labels that are never a piece's title, even when they lead
# the section (this year's program repeats a few strand names verbatim).
_PRESENTER_LABELS = {"TÅRNBY PARK STUDIO", "LIVE ART DANMARK", "FÆLLESSPISNING"}
# Generic one-word titles that must win over a person/company name.
_GENERIC_TITLE_WORDS = {"WORKSHOP", "PARTY"}
# The bio-name heuristic can't disambiguate this pair (the bio block credits
# "Maja Munksgaard Meedom" rather than her stage name "Lady Gag").
_HEADER_OVERRIDES: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"LADY GAG", "MILK BOX STAGES"}): ("MILK BOX STAGES", "LADY GAG"),
}

# Per-title category overrides; anything not listed defaults to "performance".
_CATEGORY_OVERRIDES = {
    "WORKSHOP": "workshop",
    "PARTY": "social",
    "VILD PLANTELYKKE": "social",
    "PARLIAMENT OF DISAGREEMENT": "talk",
    "STEMMER FRA AMAGER": "talk",
    "MILK BOX STAGES": "other",
    "TOUR DE TÅRNBY": "other",
    "AUGMENTED REALITIES": "other",
    "FESTIVAL PARLIAMENT": "other",
}

_PRICE_NOTE = (
    "Requires a Tårnby Park Studio festival or day pass (day pass from 25 DKK)."
)


# ── HTML text extraction ──────────────────────────────────────────────────────


def _raw_text_within(tag: Tag) -> str:
    """<br>-aware text extraction within a single top-level element.

    Only real <br> tags create line breaks; inline formatting tags (strong,
    em, span, a) never split adjacent text runs.  This matters because the
    source wraps individual words/labels in their own <span>/<strong> tags,
    which would otherwise fragment plain sentences if a naive per-string
    separator (e.g. BeautifulSoup's get_text("\\n")) were used.
    """
    parts: list[str] = []
    for node in tag.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("\n")
    text = "".join(parts).replace("‍", "").replace("​", "")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _get_blocks(section: Tag) -> list[str]:
    """One string per content block, with real paragraph breaks preserved.

    Bio/credit info is sometimes rendered as an accordion widget rather than
    a plain text block (see e.g. the "Car Piece" and "Feral Fantasies"
    sections), which uses a different internal structure
    (.accordion-item__title / .accordion-item__description) than the
    regular .sqs-html-content text blocks -- both are handled here so bio
    names are still available for title/byline disambiguation.
    """
    blocks = []
    for b in section.select(".sqs-block"):
        content = b.select_one(".sqs-html-content")
        if content is not None:
            lines = [
                _raw_text_within(child) for child in content.find_all(recursive=False)
            ]
            text = "\n".join(ln for ln in lines if ln)
            if text:
                blocks.append(text)
            continue

        for item in b.select(".accordion-item"):
            title_el = item.select_one(".accordion-item__title")
            desc_el = item.select_one(".accordion-item__description")
            title_text = _raw_text_within(title_el) if title_el else ""
            desc_text = _raw_text_within(desc_el) if desc_el else ""
            text = "\n".join(t for t in (title_text, desc_text) if t)
            if text:
                blocks.append(text)
    return blocks


def _last_image_url(section: Tag) -> str:
    imgs = section.select("img[src]")
    return str(imgs[-1]["src"]) if imgs else ""


# ── Meta block (TID/HVORNÅR/HVOR/...) parsing ─────────────────────────────────


def is_meta_block(text: str) -> bool:
    """A block counts as the schedule/venue block once it has >=2 labels."""
    return len(_LABEL_PATTERN.findall(text)) >= 2


def parse_meta(text: str) -> dict[str, str]:
    """Split a meta block into {label: value} using the uppercase labels."""
    parts = _LABEL_PATTERN.split(text)
    result: dict[str, list[str]] = {}
    for i in range(1, len(parts) - 1, 2):
        label = (
            parts[i]
            .strip()
            .rstrip(":")
            .lower()
            .replace("hvornar", "hvornår")
            .replace("laengde", "længde")
        )
        value = parts[i + 1].strip(" \n")
        result.setdefault(label, []).append(value)
    return {k: " ".join(v).strip() for k, v in result.items()}


def _infer_year(month: int, day: int, today: datetime.date) -> int:
    """Return the nearest future calendar year for the given month/day."""
    try:
        candidate = datetime.date(today.year, month, day)
    except ValueError:
        return today.year + 1
    return today.year if candidate >= today else today.year + 1


class SingleSlot(NamedTuple):
    date: datetime.date
    start_time: datetime.time | None
    end_time: datetime.time | None


class RangeSlot(NamedTuple):
    start_date: datetime.date
    end_date: datetime.date


def extract_date_time_pairs(
    when: str, today: datetime.date
) -> list[SingleSlot | RangeSlot]:
    """
    Parse a schedule string into one entry per distinct date found.

    Returns a list of:
      SingleSlot(date, start_time_or_None, end_time_or_None)
      RangeSlot(start_date, end_date)  -- e.g. a week-long installation with
        no showtimes, "17/8 - 22/8"

    Multiple showtimes on the same day (joined by "og"/"&") collapse to the
    first one, matching the convention already used by sydhavnteater.py.
    """
    dates = list(_DATE_RE.finditer(when))
    if not dates:
        return []

    has_time_marker = bool(_HAS_TIME_MARKER_RE.search(when))
    if len(dates) == 2 and not has_time_marker:
        d1, d2 = dates
        day1, month1 = int(d1.group(1)), int(d1.group(2))
        day2, month2 = int(d2.group(1)), int(d2.group(2))
        y1 = _infer_year(month1, day1, today)
        y2 = _infer_year(month2, day2, today)
        return [
            RangeSlot(
                datetime.date(y1, month1, day1),
                datetime.date(y2, month2, day2),
            )
        ]

    results: list[SingleSlot | RangeSlot] = []
    for i, m in enumerate(dates):
        day, month = int(m.group(1)), int(m.group(2))
        year = _infer_year(month, day, today)
        date = datetime.date(year, month, day)

        segment_start = m.end()
        segment_end = dates[i + 1].start() if i + 1 < len(dates) else len(when)
        segment = when[segment_start:segment_end]

        start_t = end_t = None
        range_m = _RANGE_TIME_RE.search(segment)
        if range_m:
            start_t = datetime.time(int(range_m.group(1)), int(range_m.group(2)))
            end_t = datetime.time(int(range_m.group(3)), int(range_m.group(4)))
        else:
            single_m = _SINGLE_TIME_RE.search(segment)
            if single_m:
                start_t = datetime.time(int(single_m.group(1)), int(single_m.group(2)))
        results.append(SingleSlot(date, start_t, end_t))
    return results


def _parse_duration_minutes(text: str) -> int | None:
    """Parse '35 min', '1 time og 15 min', 'ca 2 timer' -> minutes."""
    hours_m = _HOURS_RE.search(text)
    minutes_m = _MINUTES_RE.search(text)
    if not hours_m and not minutes_m:
        return None
    hours = int(hours_m.group(1)) if hours_m else 0
    minutes = int(minutes_m.group(1)) if minutes_m else 0
    total = hours * 60 + minutes
    return total or None


def _dt(date: datetime.date, t: datetime.time) -> datetime.datetime:
    return datetime.datetime(
        date.year, date.month, date.day, t.hour, t.minute, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


# ── English description extraction ────────────────────────────────────────────


def is_english_paragraph(text: str) -> bool:
    words = re.findall(r"[a-zA-ZæøåÆØÅ']+", text.lower())
    if not words:
        return False
    word_set = set(words)
    en_hits = len(word_set & _ENGLISH_STOPWORDS)
    da_hits = len(word_set & _DANISH_STOPWORDS)
    if en_hits == 0 and da_hits == 0:
        # No recognized stopwords (e.g. a short fragment) -- fall back to
        # the presence of Danish-only letters as a weak signal.
        return not re.search(r"[æøå]", text.lower())
    return en_hits > da_hits


def _extract_english_description(desc_blocks: list[str]) -> str:
    paragraphs = []
    for b in desc_blocks:
        for para in b.split("\n"):
            para = para.strip()
            if para and is_english_paragraph(para):
                paragraphs.append(para)
    return "\n\n".join(paragraphs)


# ── Title / byline disambiguation ─────────────────────────────────────────────


def _collect_bio_names(blocks_after_meta: list[str]) -> set[str]:
    """First lines of post-meta blocks that are themselves ALL CAPS are
    treated as artist/company names credited in the bio/credits blocks."""
    names = set()
    for b in blocks_after_meta:
        first_line = b.split("\n", 1)[0].strip()
        upper = first_line.upper()
        if (
            first_line
            and first_line == upper
            and upper not in {"KØB BILLET", "KREDITERING"}
        ):
            names.add(upper)
    return names


def _looks_like_artist(candidate: str, bio_names: set[str]) -> bool:
    cand = candidate.strip().upper()
    if cand in bio_names:
        return True
    return any(name in cand for name in bio_names)


def pick_title_and_artist(
    block0: str, block1: str, bio_names: set[str]
) -> tuple[str, str]:
    """Return (title, artist) given the section's first two header blocks,
    whose order (title-first vs byline-first) varies event to event."""
    key = frozenset({block0.strip().upper(), block1.strip().upper()})
    if key in _HEADER_OVERRIDES:
        return _HEADER_OVERRIDES[key]

    b0_artist = _looks_like_artist(block0, bio_names)
    b1_artist = _looks_like_artist(block1, bio_names)
    if b1_artist and not b0_artist:
        return block0, block1
    if b0_artist and not b1_artist:
        return block1, block0

    b0u, b1u = block0.strip().upper(), block1.strip().upper()
    if b0u in _PRESENTER_LABELS and b1u not in _PRESENTER_LABELS:
        return block1, block0
    if b1u in _PRESENTER_LABELS and b0u not in _PRESENTER_LABELS:
        return block0, block1
    if b0u in _GENERIC_TITLE_WORDS and b1u not in _GENERIC_TITLE_WORDS:
        return block0, block1
    if b1u in _GENERIC_TITLE_WORDS and b0u not in _GENERIC_TITLE_WORDS:
        return block1, block0

    return block0, block1


# ── Section -> record(s) ──────────────────────────────────────────────────────


def build_records(
    section: Tag, today: datetime.date, fallback_date: datetime.date | None
) -> list[dict]:
    blocks = _get_blocks(section)
    meta_idx = next((i for i, b in enumerate(blocks) if is_meta_block(b)), None)
    if meta_idx is None or meta_idx < 2:
        return []

    header_blocks = blocks[:2]
    bio_names = _collect_bio_names(blocks[meta_idx + 1 :])
    title, artist = pick_title_and_artist(header_blocks[0], header_blocks[1], bio_names)

    if not title.strip():
        log.warning("Skipping section with empty title")
        return []

    meta = parse_meta(blocks[meta_idx])
    description = _extract_english_description(blocks[2:meta_idx])
    if (
        artist
        and artist.strip().upper() not in _PRESENTER_LABELS | _GENERIC_TITLE_WORDS
    ):
        description = (
            f"By {artist.title()}\n\n{description}"
            if description
            else (f"By {artist.title()}")
        )
    if not description:
        description = "Details to be announced."

    venue_name = meta.get("hvor") or DEFAULT_VENUE
    category = _CATEGORY_OVERRIDES.get(title.strip().upper(), "performance")
    duration_minutes = _parse_duration_minutes(
        meta.get("længde") or meta.get("varighed") or ""
    )
    image_url = _last_image_url(section)

    when_str = meta.get("hvornår") or meta.get("tid") or ""
    pairs = extract_date_time_pairs(when_str, today)

    if not pairs and meta.get("indvielse"):
        # Week-long installations often only give a fixed time for their
        # opening/inauguration ("INDVIELSE") event.
        pairs = extract_date_time_pairs(meta["indvielse"], today)

    records: list[dict] = []

    if not pairs:
        # No parseable date anywhere for this entry -- fall back to the
        # earliest date found elsewhere on the page, at a default time, and
        # say so in the price note so a human can go verify the real time.
        fallback = fallback_date or today
        start_dt = _dt(fallback, DEFAULT_TIME)
        records.append(
            _make_record(
                title,
                description,
                start_dt,
                None,
                venue_name,
                category,
                image_url,
                extra_note="Exact date/time to be confirmed -- see taarnby.art.",
            )
        )
        return records

    for pair in pairs:
        if isinstance(pair, RangeSlot):
            start_dt = _dt(pair.start_date, DEFAULT_TIME)
            end_dt = _dt(pair.end_date, DEFAULT_TIME)
            records.append(
                _make_record(
                    title,
                    description,
                    start_dt,
                    end_dt,
                    venue_name,
                    category,
                    image_url,
                    extra_note="Runs across multiple days -- see taarnby.art for details.",
                )
            )
        else:
            start_time = pair.start_time or DEFAULT_TIME
            start_dt = _dt(pair.date, start_time)
            end_dt = None
            if pair.end_time:
                end_dt = _dt(pair.date, pair.end_time)
            elif duration_minutes:
                end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
            extra_note = (
                None if pair.start_time else "Exact time TBA -- see taarnby.art."
            )
            records.append(
                _make_record(
                    title,
                    description,
                    start_dt,
                    end_dt,
                    venue_name,
                    category,
                    image_url,
                    extra_note=extra_note,
                )
            )

    return records


def _make_record(
    title: str,
    description: str,
    start_dt: datetime.datetime,
    end_dt: datetime.datetime | None,
    venue_name: str,
    category: str,
    image_url: str,
    extra_note: str | None = None,
) -> dict:
    price_note = _PRICE_NOTE
    if extra_note:
        price_note = f"{extra_note} {_PRICE_NOTE}"[:200]
    return {
        "title": title.title(),
        "description": description,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat() if end_dt else None,
        "venue_name": venue_name,
        "venue_address": f"{venue_name}, {VENUE_MUNICIPALITY}",
        "category": category,
        "is_free": False,
        "is_wheelchair_accessible": False,
        "price_note": price_note,
        "source_url": PROGRAM_URL,
        "external_source": EXTERNAL_SOURCE,
        "image_url": image_url,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape() -> list[dict]:
    session = make_session()
    resp = session.get(PROGRAM_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    article = soup.find("article")
    if article is None:
        log.warning("No <article> found on %s", PROGRAM_URL)
        return []

    sections = article.find_all("section", class_="page-section", recursive=False)
    today = datetime.datetime.now(CPH_TZ).date()

    # First pass: find the earliest parseable date on the page, used as a
    # fallback for the rare entry with no date info at all.
    fallback_date: datetime.date | None = None
    for section in sections:
        blocks = _get_blocks(section)
        meta_idx = next((i for i, b in enumerate(blocks) if is_meta_block(b)), None)
        if meta_idx is None:
            continue
        meta = parse_meta(blocks[meta_idx])
        when_str = meta.get("hvornår") or meta.get("tid") or ""
        for pair in extract_date_time_pairs(when_str, today):
            date = pair.start_date if isinstance(pair, RangeSlot) else pair.date
            if fallback_date is None or date < fallback_date:
                fallback_date = date

    records: list[dict] = []
    for section in sections:
        section_records = build_records(section, today, fallback_date)
        records.extend(section_records)

    log.info("Built %d event records from %d sections", len(records), len(sections))
    return records


def main() -> None:
    args = build_arg_parser(
        "Scrape taarnby.art festival program",
        "taornby_events.json",
        include_delay=False,
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    records = scrape()
    write_output(records, args.output, args.dry_run)


if __name__ == "__main__":
    main()
