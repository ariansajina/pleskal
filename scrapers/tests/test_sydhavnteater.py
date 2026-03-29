"""Unit tests for scrapers/sydhavnteater.py helper functions."""

import datetime

from scrapers.sydhavnteater import (
    CATEGORY_MAP,
    CPH_TZ,
    _extract_where,
    build_records,
    is_upcoming,
    parse_description,
    parse_when,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FUTURE_DATE = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
PAST_DATE = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()


def _make_event(**overrides) -> dict:
    base = {
        "title": "Test Event",
        "slug": "test-event",
        "uri": "event/test-event",
        "dateFrom": f"{FUTURE_DATE}T07:00:00+00:00",
        "dateTo": f"{FUTURE_DATE}T07:00:00+00:00",
        "ticketLink": None,
        "textEnglish": "<p>Short intro.</p>",
        "stage": [{"title": "Kapelscenen"}],
        "category": [{"title": "Forestillinger"}],
        "media": [{"url": "https://cms.sydhavnteater.dk/assets/img.jpg"}],
        "sections": [],
    }
    base.update(overrides)
    return base


# ── is_upcoming ───────────────────────────────────────────────────────────────


def test_is_upcoming_future():
    assert is_upcoming(_make_event()) is True


def test_is_upcoming_past():
    event = _make_event(
        dateFrom=f"{PAST_DATE}T07:00:00+00:00",
        dateTo=f"{PAST_DATE}T07:00:00+00:00",
    )
    assert is_upcoming(event) is False


def test_is_upcoming_today():
    today = datetime.date.today().isoformat()
    event = _make_event(
        dateFrom=f"{today}T07:00:00+00:00",
        dateTo=f"{today}T07:00:00+00:00",
    )
    assert is_upcoming(event) is True


def test_is_upcoming_run_ends_in_future():
    # dateFrom is past but dateTo is future — event is still running
    event = _make_event(
        dateFrom=f"{PAST_DATE}T07:00:00+00:00",
        dateTo=f"{FUTURE_DATE}T07:00:00+00:00",
    )
    assert is_upcoming(event) is True


def test_is_upcoming_missing_dates():
    assert is_upcoming({"dateFrom": None, "dateTo": None}) is False


# ── parse_description ─────────────────────────────────────────────────────────


def test_parse_description_uses_sections():
    event = _make_event(
        textEnglish="<p>Short intro.</p>",
        sections=[{"headlineEnglish": None, "textEnglish": "<p>Full description.</p>"}],
    )
    result = parse_description(event)
    assert "Full description" in result
    assert "Short intro" not in result


def test_parse_description_falls_back_to_text_english():
    event = _make_event(
        textEnglish="<p>Short intro.</p>",
        sections=[],
    )
    assert "Short intro" in parse_description(event)


def test_parse_description_skips_empty_sections():
    event = _make_event(
        textEnglish="<p>Fallback.</p>",
        sections=[{"headlineEnglish": None, "textEnglish": "   "}],
    )
    assert "Fallback" in parse_description(event)


def test_parse_description_returns_markdown():
    event = _make_event(
        textEnglish="<p>Hello <strong>world</strong>.</p>",
        sections=[],
    )
    result = parse_description(event)
    assert "**world**" in result


def test_parse_description_empty():
    event = _make_event(textEnglish=None, sections=[])
    assert parse_description(event) == ""


# ── category mapping ──────────────────────────────────────────────────────────


def test_category_map_performance():
    assert CATEGORY_MAP["forestillinger"] == "performance"


def test_category_map_workshop():
    assert CATEGORY_MAP["workshops"] == "workshop"


# ── parse_when ────────────────────────────────────────────────────────────────


def test_parse_when_simple_time():
    result = parse_when("at 20.00")
    assert result == {-1: [datetime.time(20, 0)]}


def test_parse_when_bare_time():
    result = parse_when("20.00")
    assert result == {-1: [datetime.time(20, 0)]}


def test_parse_when_colon_time():
    result = parse_when("at 18:00")
    assert result == {-1: [datetime.time(18, 0)]}


def test_parse_when_two_times_same_day():
    result = parse_when("at 16.00 & 18.00")
    assert result == {-1: [datetime.time(16, 0), datetime.time(18, 0)]}


def test_parse_when_weekday_range():
    # "Tue — Sat at 20.00" → weekdays 1–5
    result = parse_when("Tue — Sat at 20.00")
    assert result is not None
    for wd in (1, 2, 3, 4, 5):
        assert wd in result
        assert result[wd] == [datetime.time(20, 0)]
    assert 0 not in result  # Monday excluded
    assert 6 not in result  # Sunday excluded


def test_parse_when_weekday_list_different_times():
    # "Tue, Thu & Fri at 20.00 — Wed at 17.00 — Sat at 16.00"
    result = parse_when("Tue, Thu & Fri at 20.00 — Wed at 17.00 — Sat at 16.00")
    assert result is not None
    assert result[1] == [datetime.time(20, 0)]  # Tue
    assert result[3] == [datetime.time(20, 0)]  # Thu
    assert result[4] == [datetime.time(20, 0)]  # Fri
    assert result[2] == [datetime.time(17, 0)]  # Wed
    assert result[5] == [datetime.time(16, 0)]  # Sat


def test_parse_when_empty_returns_none():
    assert parse_when("") is None


def test_parse_when_unrecognised_returns_none():
    assert parse_when("See link") is None


# ── build_records ─────────────────────────────────────────────────────────────


def _make_range_event(date_from: str, date_to: str, **overrides) -> dict:
    """Helper to create event with explicit date range."""
    base = _make_event(
        dateFrom=f"{date_from}T07:00:00+00:00",
        dateTo=f"{date_to}T07:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_build_records_single_day_no_schedule():
    records = build_records(_make_event())
    assert len(records) == 1
    assert records[0]["title"] == "Test Event"
    assert records[0]["source_url"] == "https://sydhavnteater.dk/event/test-event"
    assert records[0]["venue_name"] == "Kapelscenen"
    assert records[0]["category"] == "performance"
    assert records[0]["is_free"] is True
    assert records[0]["external_source"] == "sydhavnteater"
    assert records[0]["image_url"] == "https://cms.sydhavnteater.dk/assets/img.jpg"


def test_build_records_missing_title_returns_empty():
    assert build_records(_make_event(title="")) == []


def test_build_records_missing_uri_returns_empty():
    assert build_records(_make_event(uri="")) == []


def test_build_records_missing_date_returns_empty():
    assert build_records(_make_event(dateFrom=None)) == []


def test_build_records_is_free_no_ticket_link():
    records = build_records(_make_event(ticketLink=None))
    assert records[0]["is_free"] is True


def test_build_records_is_free_with_ticket_link():
    records = build_records(_make_event(ticketLink="https://teaterbilletter.dk/123"))
    assert records[0]["is_free"] is False


def test_build_records_default_venue():
    records = build_records(_make_event(stage=[]))
    assert records[0]["venue_name"] == "Sydhavn Teater"


def test_build_records_where_overrides_stage():
    sections = [{"data": [{"titleEnglish": "Where", "textEnglish": "Valbyparken"}]}]
    records = build_records(_make_event(sections=sections))
    assert records[0]["venue_name"] == "Valbyparken"


def test_extract_where_returns_empty_when_missing():
    assert _extract_where(_make_event()) == ""


def test_extract_where_case_insensitive():
    sections = [{"data": [{"titleEnglish": "WHERE", "textEnglish": "Somewhere"}]}]
    assert _extract_where(_make_event(sections=sections)) == "Somewhere"


def test_build_records_unknown_category_defaults_to_other():
    records = build_records(_make_event(category=[{"title": "Unknown"}]))
    assert records[0]["category"] == "other"


def test_build_records_three_day_range_no_schedule():
    d0 = datetime.date.today() + datetime.timedelta(days=30)
    d2 = d0 + datetime.timedelta(days=2)
    records = build_records(_make_range_event(d0.isoformat(), d2.isoformat()))
    assert len(records) == 3


def test_build_records_five_day_range_with_simple_time():
    # "at 20.00" on every day → 5 records each at 20:00 CPH
    d0 = datetime.date.today() + datetime.timedelta(days=30)
    d4 = d0 + datetime.timedelta(days=4)
    sections = [{"data": [{"titleEnglish": "When", "textEnglish": "at 20.00"}]}]
    event = _make_range_event(d0.isoformat(), d4.isoformat(), sections=sections)
    records = build_records(event)
    assert len(records) == 5
    # All start times should have hour=20 in the isoformat
    for r in records:
        # start_datetime is UTC ISO string; CPH is UTC+1 or UTC+2
        dt = datetime.datetime.fromisoformat(r["start_datetime"])
        assert dt.hour in (
            18,
            19,
            20,
        )  # 20:00 CPH = 18:00 or 19:00 UTC depending on DST


def test_build_records_two_times_same_day():
    # "at 16.00 & 18.00" → 1 record per day, start_datetime uses the first time
    sections = [{"data": [{"titleEnglish": "When", "textEnglish": "at 16.00 & 18.00"}]}]
    records = build_records(_make_event(sections=sections))
    assert len(records) == 1
    start = datetime.datetime.fromisoformat(records[0]["start_datetime"])
    assert start.astimezone(CPH_TZ).hour == 16


def test_build_records_weekly_schedule_filters_days():
    # Build a Mon–Sun week starting next Monday
    today = datetime.date.today()
    # Find next Monday
    days_until_monday = (7 - today.weekday()) % 7 or 7
    monday = today + datetime.timedelta(days=days_until_monday)
    sunday = monday + datetime.timedelta(days=6)

    sections = [
        {"data": [{"titleEnglish": "When", "textEnglish": "Tue — Sat at 20.00"}]}
    ]
    event = _make_range_event(monday.isoformat(), sunday.isoformat(), sections=sections)
    records = build_records(event)
    # Tue=1, Wed=2, Thu=3, Fri=4, Sat=5 → 5 records
    assert len(records) == 5
    for r in records:
        dt = datetime.datetime.fromisoformat(r["start_datetime"])
        # Convert back to CPH to check weekday
        import zoneinfo

        cph_dt = dt.astimezone(zoneinfo.ZoneInfo("Europe/Copenhagen"))
        assert cph_dt.weekday() in (1, 2, 3, 4, 5)


def test_build_records_isnatter_schedule():
    # "Tue, Thu & Fri at 20.00 — Wed at 17.00 — Sat at 16.00"
    # Over a Mon–Sun range → Tue/Thu/Fri at 20, Wed at 17, Sat at 16 = 5 records
    today = datetime.date.today()
    days_until_monday = (7 - today.weekday()) % 7 or 7
    monday = today + datetime.timedelta(days=days_until_monday)
    sunday = monday + datetime.timedelta(days=6)

    when = "Tue, Thu & Fri at 20.00 — Wed at 17.00 — Sat at 16.00"
    sections = [{"data": [{"titleEnglish": "When", "textEnglish": when}]}]
    event = _make_range_event(monday.isoformat(), sunday.isoformat(), sections=sections)
    records = build_records(event)
    assert len(records) == 5

    import zoneinfo

    cph_tz = zoneinfo.ZoneInfo("Europe/Copenhagen")
    by_wd: dict[int, list] = {}
    for r in records:
        dt = datetime.datetime.fromisoformat(r["start_datetime"]).astimezone(cph_tz)
        by_wd.setdefault(dt.weekday(), []).append(dt.hour)

    assert by_wd[1] == [20]  # Tue
    assert by_wd[2] == [17]  # Wed
    assert by_wd[3] == [20]  # Thu
    assert by_wd[4] == [20]  # Fri
    assert by_wd[5] == [16]  # Sat
