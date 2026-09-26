"""Unit tests for scrapers/warehouse9.py helper functions."""

import datetime

from icalendar import Calendar

from scrapers.warehouse9 import (
    _determine_category,
    _extract_image_url,
    _format_description,
    _is_free,
    _split_location,
    _to_utc,
    build_record,
    is_upcoming,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FUTURE = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)
PAST = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)


def _vevent(
    *,
    summary: str = "Work presentation: Tender Routes",
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    url: str = "https://warehouse9.dk/event/tender-routes/",
    location: str = "Warehouse9, Rosenlunds Allé 5, Copenhagen, 2720, Denmark",
    description: str = "Entrance: Free, with sign-up",
    attach: str | None = "https://warehouse9.dk/wp-content/uploads/x.png",
):
    """Build a single parsed VEVENT component via the icalendar library."""
    start = start or FUTURE
    end = end or (start + datetime.timedelta(hours=1))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Test//EN",
        "BEGIN:VEVENT",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
    ]
    if url:
        lines.append(f"URL:{url}")
    if attach:
        lines.append(f"ATTACH;FMTTYPE=image/png:{attach}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    cal = Calendar.from_ical("\r\n".join(lines))
    return next(iter(cal.walk("VEVENT")))


# ── _to_utc ───────────────────────────────────────────────────────────────────


def test_to_utc_converts_cph_datetime():
    naive = datetime.datetime(2026, 6, 4, 17, 0)  # interpreted as CPH (CEST, +2)
    result = _to_utc(naive)
    assert result.tzinfo == datetime.UTC
    assert result == datetime.datetime(2026, 6, 4, 15, 0, tzinfo=datetime.UTC)


def test_zoned_start_is_read_as_copenhagen_wall_clock():
    # The Qspace series is saved as Europe/London, but the site shows (and the
    # copy says) 18:30 Copenhagen time.
    feed = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\nDTSTART;TZID=Europe/London:20261001T183000\r\n"
        "DTEND;TZID=Europe/London:20261001T203000\r\n"
        "SUMMARY:Get Weird With Wrestling\r\n"
        "URL:https://warehouse9.dk/event/get-weird-with-wrestling/2026-10-01/\r\n"
        "END:VEVENT\r\nEND:VCALENDAR"
    )
    record = build_record(next(iter(Calendar.from_ical(feed).walk("VEVENT"))))
    assert record is not None
    assert record["start_datetime"] == "2026-10-01T16:30:00+00:00"
    assert record["end_datetime"] == "2026-10-01T18:30:00+00:00"


def test_explicit_utc_start_is_kept():
    start = datetime.datetime(2026, 10, 1, 16, 30, tzinfo=datetime.UTC)
    record = build_record(_vevent(start=start))
    assert record is not None
    assert record["start_datetime"] == "2026-10-01T16:30:00+00:00"


def test_to_utc_handles_bare_date():
    result = _to_utc(datetime.date(2026, 6, 4))  # midnight CPH → 22:00 prev day UTC
    assert result == datetime.datetime(2026, 6, 3, 22, 0, tzinfo=datetime.UTC)


# ── _format_description ───────────────────────────────────────────────────────


def test_format_description_separates_paragraphs():
    result = _format_description("Line one\nLine two")
    assert result == "Line one\n\nLine two"


def test_format_description_drops_blank_lines():
    result = _format_description("First\n\n   \nSecond")
    assert result == "First\n\nSecond"


def test_format_description_empty():
    assert _format_description("") == ""


# ── _split_location ───────────────────────────────────────────────────────────


def test_split_location_name_and_address():
    name, address = _split_location("Warehouse9, Rosenlunds Allé 5, Copenhagen")
    assert name == "Warehouse9"
    assert address == "Rosenlunds Allé 5"


def test_split_location_drops_city_postcode_country():
    name, address = _split_location(
        "Warehouse9, Rosenlunds Allé 5, Copenhagen, 2720, Denmark"
    )
    assert name == "Warehouse9"
    assert address == "Rosenlunds Allé 5"


def test_split_location_empty_falls_back_to_venue_name():
    name, address = _split_location("")
    assert name == "Warehouse9"
    assert address == ""


# ── _determine_category ───────────────────────────────────────────────────────


def test_category_default_is_performance():
    assert _determine_category("Solstice Walk", "A poetic walk") == "performance"


def test_category_work_presentation_is_worksharing():
    assert _determine_category("Work presentation: X", "") == "worksharing"


def test_category_party_is_social():
    assert _determine_category("Summer Party", "") == "social"


def test_category_open_stage_is_performance_despite_workshop_copy():
    assert (
        _determine_category(
            "QUEERMASH X OPEN STAGE", "Sign up for the workshop before the show."
        )
        == "performance"
    )


def test_category_residency_title_is_other():
    assert (
        _determine_category("Animated Sickwalker - Qlab artistic development", "")
        == "other"
    )


def test_category_workshop_copy_beats_residency_mention():
    assert (
        _determine_category(
            "Daydream Dialogues", "Workshops led by our residency artist."
        )
        == "workshop"
    )


def test_category_title_beats_body_keyword():
    # A stray "workshop" in the body must not override the "party" title.
    assert _determine_category("Summer Party", "We also run a workshop") == "social"


# ── _is_free ──────────────────────────────────────────────────────────────────


def test_is_free_true_when_text_says_free():
    assert _is_free("X", "Entrance: Free, with sign-up") is True


def test_is_free_false_otherwise():
    assert _is_free("X", "Tickets 120 DKK") is False


def test_is_free_ignores_the_access_note():
    # Every event ends with this note; it is about step-free access.
    description = (
        "A wrestling workshop.\n\nAccess Information\n\nWarehouse9 has level "
        "free entrance to the space and a gender neutral accessible toilet."
    )
    assert _is_free("Get Weird With Wrestling", description) is False


def test_is_free_ignores_feel_free():
    description = (
        "Two ticket options, please feel free to choose the one that suits you."
    )
    assert _is_free("Open Stage", description) is False


def test_is_free_reads_free_workshops():
    assert _is_free("X", "How much does it cost? The workshops are free.") is True


# ── _extract_image_url ────────────────────────────────────────────────────────


def test_extract_image_url():
    component = _vevent(attach="https://warehouse9.dk/wp-content/uploads/p.png")
    assert (
        _extract_image_url(component)
        == "https://warehouse9.dk/wp-content/uploads/p.png"
    )


def test_extract_image_url_missing():
    component = _vevent(attach=None)
    assert _extract_image_url(component) == ""


# ── build_record ──────────────────────────────────────────────────────────────


def test_build_record_full():
    component = _vevent()
    record = build_record(component)
    assert record is not None
    assert record["title"] == "Work presentation: Tender Routes"
    assert record["category"] == "worksharing"
    assert record["is_free"] is True
    # Every Warehouse9 event is wheelchair accessible.
    assert record["is_wheelchair_accessible"] is True
    assert record["venue_name"] == "Warehouse9"
    assert record["venue_address"].startswith("Rosenlunds Allé 5")
    assert record["external_source"] == "warehouse9"
    assert record["source_url"] == "https://warehouse9.dk/event/tender-routes/"
    assert record["image_url"].endswith(".png")
    # Datetimes round-trip as ISO strings.
    datetime.datetime.fromisoformat(record["start_datetime"])
    datetime.datetime.fromisoformat(record["end_datetime"])


def test_build_record_skips_without_title():
    component = _vevent(summary="")
    assert build_record(component) is None


def test_build_record_skips_without_url():
    component = _vevent(url="")
    assert build_record(component) is None


def test_build_record_without_end():
    # An event missing DTEND still produces a record with end_datetime None.
    cal = Calendar.from_ical(
        "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Test//EN",
                "BEGIN:VEVENT",
                f"DTSTART:{FUTURE.strftime('%Y%m%dT%H%M%SZ')}",
                "SUMMARY:No End Event",
                "URL:https://warehouse9.dk/event/no-end/",
                "LOCATION:Warehouse9, Copenhagen",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )
    )
    component = next(iter(cal.walk("VEVENT")))
    record = build_record(component)
    assert record is not None
    assert record["end_datetime"] is None


# ── is_upcoming ───────────────────────────────────────────────────────────────


def test_is_upcoming_future():
    record = {"start_datetime": FUTURE.isoformat(), "end_datetime": None}
    assert is_upcoming(record) is True


def test_is_upcoming_past():
    record = {"start_datetime": PAST.isoformat(), "end_datetime": PAST.isoformat()}
    assert is_upcoming(record) is False


def test_is_upcoming_uses_end_when_running():
    # Started in the past but ends in the future → still upcoming.
    record = {"start_datetime": PAST.isoformat(), "end_datetime": FUTURE.isoformat()}
    assert is_upcoming(record) is True
