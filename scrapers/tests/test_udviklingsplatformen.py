"""Unit tests for scrapers/udviklingsplatformen.py."""

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from events.management.commands.run_scrapers import SCRAPER_DISABLED_AFTER
from scrapers import udviklingsplatformen as up
from scrapers.registry import SOURCES

TODAY = datetime.date(2026, 10, 20)


def _item(
    *,
    item_id: str = "158590",
    dates: str = "23. October",
    type_: str = "Worksharing",
    title: str = "FENRIS: Worksharing and artist talk",
    link: str = '<a href="https://example.org/fenris/">Studio Nord</a>',
    content: str = "<p>A work-in-progress showing.</p>",
) -> str:
    """One calendar entry, as /en/getCalendarEvents returns it (trimmed)."""
    return f"""
    <div class="item accordion-row full-width" data-id="{item_id}">
      <div class="accordion-header">
        <div class="dates">
          {dates}
        </div>
        <div class="type">
          {type_}
        </div>
        <div class="sender">{title}</div>
        <div class="read-more">Read more</div>
      </div>
      <div class="accordion-content">
        <div class="links">
          <div>Read more at:</div>
          <ul><li>{link}</li></ul>
        </div>
        <div class="content">{content}</div>
      </div>
    </div>
    """


def _parse(html: str):
    return BeautifulSoup(html, "lxml").select_one("div.item[data-id]")


# ── parse_dates ───────────────────────────────────────────────────────────────


def test_parse_dates_current_year():
    assert up.parse_dates("23. October", TODAY) == (
        datetime.date(2026, 10, 23),
        datetime.date(2026, 10, 23),
    )


def test_parse_dates_explicit_year():
    assert up.parse_dates("28. February, 2027", TODAY) == (
        datetime.date(2027, 2, 28),
        datetime.date(2027, 2, 28),
    )


def test_parse_dates_range():
    assert up.parse_dates("08. December – 09. December", TODAY) == (
        datetime.date(2026, 12, 8),
        datetime.date(2026, 12, 9),
    )


def test_parse_dates_range_across_new_year():
    assert up.parse_dates("30. December – 02. January, 2027", TODAY) == (
        datetime.date(2026, 12, 30),
        datetime.date(2027, 1, 2),
    )
    assert up.parse_dates("30. December – 02. January", TODAY) == (
        datetime.date(2026, 12, 30),
        datetime.date(2027, 1, 2),
    )


def test_parse_dates_unparseable():
    assert up.parse_dates("Soon", TODAY) is None
    assert up.parse_dates("31. Smarch", TODAY) is None


# ── parse_times ───────────────────────────────────────────────────────────────

T = datetime.time


def test_parse_times_single():
    assert up.parse_times("Doors at 4:00 PM, then talk") == (T(16, 0), None)
    assert up.parse_times("from 6 p.m.") == (T(18, 0), None)
    assert up.parse_times("12 pm sharp") == (T(12, 0), None)
    assert up.parse_times("Starts 17:30") == (T(17, 30), None)
    assert up.parse_times("Visning kl. 17") == (T(17, 0), None)
    assert up.parse_times("Visning kl. 19.30") == (T(19, 30), None)


def test_parse_times_ranges():
    # Formats from UP's own (Tid i Rum) worksharing announcements.
    assert up.parse_times("When? August 14, 1:30–3:00 p.m.") == (T(13, 30), T(15))
    assert up.parse_times("1:45–2:30 PM: Workshop in White Lab") == (
        T(13, 45),
        T(14, 30),
    )
    assert up.parse_times("Friday, May 9, 13:00 - 13:45") == (T(13, 0), T(13, 45))
    assert up.parse_times("Visning kl. 13.00-13.45") == (T(13, 0), T(13, 45))
    assert up.parse_times("kl. 17-19") == (T(17, 0), T(19, 0))
    # The marker on the end only: an am start before a pm end.
    assert up.parse_times("11:30-1:00 p.m.") == (T(11, 30), T(13, 0))


def test_parse_times_programme_runs_to_last_slot():
    programme = (
        "Program: 1:00-1:45 p.m.: Worksharing in The Pit "
        "1:45-2:30 p.m.: Worksharing in White Lab "
        "2:30-3:00 p.m.: Coffee and tea in the foyer"
    )
    assert up.parse_times(programme) == (T(13, 0), T(15, 0))


def test_parse_times_takes_first_and_ignores_dates_and_prices():
    assert up.parse_times("4:00 PM showing. 6:00 p.m. dinner") == (T(16, 0), None)
    assert up.parse_times("On 23.10 it costs 50.00 kr.") == (None, None)
    assert up.parse_times("14-21 August, 23.10-24.10, 2025-2026") == (None, None)
    assert up.parse_times("No time given") == (None, None)


# ── venue / covered hosts ─────────────────────────────────────────────────────


def test_is_covered():
    assert up.is_covered("https://warehouse9.dk/da/begivenhed/fenris/")
    assert up.is_covered("https://www.dansehallerne.dk/en/x")
    assert up.is_covered("https://cms.sydhavnteater.dk/x")
    assert not up.is_covered("https://doks-dans.org/x")
    assert not up.is_covered("https://notwarehouse9.dk/x")


def test_determine_venue():
    assert up.determine_venue("Studio Nord", "https://example.org/x", "") == (
        "Studio Nord",
        "",
    )
    # Generic or domain-like labels fall back to the link's host.
    assert up.determine_venue("See more", "https://www.doks-dans.org/x", "") == (
        "doks-dans.org",
        "",
    )
    assert up.determine_venue("slks.dk", "https://slks.dk/x", "")[0] == "slks.dk"
    # UP's own pages, or a body naming its address, mean UP's studios.
    assert up.determine_venue(
        "Sign up", "https://www.udviklingsplatformen.dk/en/x", ""
    ) == (up.VENUE_NAME, up.VENUE_ADDRESS)
    for body in ("Held at Baldersgade 6", "Workshop in The Pit", "Tid i Rum"):
        assert up.determine_venue("Studio Nord", "", body) == (
            up.VENUE_NAME,
            up.VENUE_ADDRESS,
        )


def test_covered_hosts_match_active_scrapers():
    """Every venue another active scraper imports is skipped, so no duplicates."""
    sources = json.loads(
        (Path(up.__file__).parent / "sources.json").read_text(encoding="utf-8")
    )
    websites = {s["external_source"]: s["website"] for s in sources}
    for source in SOURCES.values():
        if (
            source.external_source == up.EXTERNAL_SOURCE
            or source.name in SCRAPER_DISABLED_AFTER
        ):
            continue
        assert up.is_covered(websites[source.external_source]), source.name


def test_registry_entry():
    source = SOURCES["udviklingsplatformen"]
    assert source.external_source == up.EXTERNAL_SOURCE
    assert source.default_venue_name == up.VENUE_NAME
    assert source.allowed_image_domains == frozenset({up.UP_HOST})


# ── build_records ─────────────────────────────────────────────────────────────


def test_build_record_fields():
    item = _parse(
        _item(content="<p>Showing at <strong>5:00 PM</strong>. Free admission.</p>")
    )
    (rec,) = up.build_records(item, TODAY)
    assert rec["title"] == "FENRIS: Worksharing and artist talk"
    assert rec["start_datetime"] == "2026-10-23T17:00:00+02:00"
    assert rec["end_datetime"] is None
    assert rec["category"] == "worksharing"
    assert rec["venue_name"] == "Studio Nord"
    assert rec["is_free"] is True
    assert rec["is_wheelchair_accessible"] is False
    assert rec["source_url"] == (
        "https://www.udviklingsplatformen.dk/en/calendar#event-158590"
    )
    assert rec["description"] == (
        "Showing at **5:00 PM**. Free admission.\n\n"
        "More information: [Studio Nord](https://example.org/fenris/)"
    )


def test_build_record_without_time_uses_midnight():
    (rec,) = up.build_records(_parse(_item()), TODAY)
    assert rec["start_datetime"] == "2026-10-23T00:00:00+02:00"
    assert rec["is_free"] is False


def test_build_record_tid_i_rum_worksharing():
    """A worksharing at UP, worded like its Tid i Rum announcements."""
    item = _parse(
        _item(
            dates="14. November",
            title="Tid i Rum: Worksharing with Inga Gerner Nielsen",
            link=(
                '<a href="https://www.udviklingsplatformen.dk/en/'
                'kom-til-worksharings-hos-up">See more</a>'
            ),
            content=(
                "<p><strong>When?</strong> November 14, 1:30–3:00 p.m.</p>"
                "<p><strong>Where?</strong> The Development Platform for "
                "Performing Arts, Baldersgade 6, Copenhagen N.</p>"
                "<p><strong>Registration?</strong> Register for free here</p>"
            ),
        )
    )
    (rec,) = up.build_records(item, TODAY)
    assert rec["start_datetime"] == "2026-11-14T13:30:00+01:00"
    assert rec["end_datetime"] == "2026-11-14T15:00:00+01:00"
    assert (rec["venue_name"], rec["venue_address"]) == (
        up.VENUE_NAME,
        up.VENUE_ADDRESS,
    )
    assert rec["is_free"] is True


def test_build_records_skips_covered_venue():
    item = _parse(
        _item(link='<a href="https://warehouse9.dk/da/begivenhed/x/">Warehouse9</a>')
    )
    assert up.build_records(item, TODAY) == []


def test_build_records_skips_other_types():
    item = _parse(_item(type_="Open Call", title="Open call: Tid i Rum 2027"))
    assert up.build_records(item, TODAY) == []


def test_build_records_up_event_titled_worksharing():
    item = _parse(
        _item(
            type_="UP event",
            title="Time in Space Worksharing: Out Of Office.arts:",
            link='<a href="https://www.udviklingsplatformen.dk/en/kom-til-worksharings-hos-up">'
            "Learn more about Tid i Rum worksharings</a>",
            content="<p>Worksharing at UP: Friday, October 23, 2:00–2:45 p.m.</p>"
            '<p><a href="https://billetto.dk/e/x">Book a free ticket</a></p>',
        )
    )
    (rec,) = up.build_records(item, TODAY)
    assert rec["title"] == "Time in Space Worksharing: Out Of Office.arts"
    assert rec["category"] == "worksharing"
    assert rec["venue_name"] == up.VENUE_NAME
    assert rec["start_datetime"].endswith("T14:00:00+02:00")
    assert rec["end_datetime"].endswith("T14:45:00+02:00")
    assert rec["is_free"] is True


def test_build_records_skips_other_up_events():
    item = _parse(_item(type_="UP event", title="UP's Christmas party"))
    assert up.build_records(item, TODAY) == []


def test_build_records_splits_short_range_and_drops_past_days():
    item = _parse(_item(dates="19. October – 21. October"))
    recs = up.build_records(item, TODAY)
    assert [r["start_datetime"][:10] for r in recs] == ["2026-10-20", "2026-10-21"]
    assert len({r["source_url"] for r in recs}) == 1


def test_build_records_long_range_listed_on_first_day():
    item = _parse(_item(dates="01. November – 30. November"))
    (rec,) = up.build_records(item, TODAY)
    assert rec["start_datetime"][:10] == "2026-11-01"


def test_build_records_without_link():
    item = _parse(_item(link=""))
    (rec,) = up.build_records(item, TODAY)
    assert rec["venue_name"] == up.VENUE_NAME
    assert "More information" not in rec["description"]


def test_build_records_unparseable_date():
    assert up.build_records(_parse(_item(dates="TBA")), TODAY) == []


# ── scrape ────────────────────────────────────────────────────────────────────


def test_scrape_requests_worksharing_and_up_event_filters():
    future = "23. October, 2099"
    worksharings = MagicMock(
        text=_item(dates=future)
        + _item(item_id="2", dates=future, type_="Deadline", title="Deadline")
    )
    up_events = MagicMock(
        text=_item(dates=future)  # also listed under Worksharing: kept once
        + _item(
            item_id="3",
            dates=future,
            type_="UP event",
            title="Time in Space Worksharing: RAVEN",
        )
        + _item(item_id="4", dates=future, type_="UP event", title="Party")
    )
    session = MagicMock()
    session.get.side_effect = [worksharings, up_events]
    with patch.object(up, "make_session", return_value=session):
        records = up.scrape()

    calls = session.get.call_args_list
    assert [c.args[0] for c in calls] == [up.EVENTS_URL, up.EVENTS_URL]
    assert [c.kwargs["params"] for c in calls] == [
        {"category": "worksharing"},
        {"category": "up-event"},
    ]
    assert all(
        c.kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest" for c in calls
    )
    assert [r["source_url"].rsplit("-", 1)[1] for r in records] == ["158590", "3"]


# ── images from the linked UP page ────────────────────────────────────────────

PAGE_URL = "https://www.udviklingsplatformen.dk/en/kom-til-worksharings-hos-up"
UPLOADS = "https://www.udviklingsplatformen.dk/assets/uploads"


def _block(image: str, heading: str) -> str:
    srcset = ",".join(f"{UPLOADS}/_x{w}/{image} {w}w" for w in (600, 1200, 1800, 2400))
    return f"""
    <div class="grid-item"><div class="inner">
      <figure class="image lazy"><img class="lazyload" data-srcset="{srcset}"></figure>
      <div class="text"><p><strong>{heading}</strong></p><p>About the work.</p></div>
    </div></div>
    """


def _page(*blocks: str) -> str:
    return f"""
    <html><head>
      <meta property="og:image" content="{UPLOADS}/_landscape1200/Worksharing.jpg">
    </head><body>
      <div class="featured-image"><img data-srcset="{UPLOADS}/_x600/Worksharing.jpg 600w"></div>
      <section class="module"><div class="grid-items">{"".join(blocks)}</div></section>
      <div class="inner"><img src="/assets/static/logo.svg"></div>
    </body></html>
    """


PAGE = _page(
    _block("Spiral.jpg", "Friday, December 11, at 2:00 p.m."),
    _block("Nøgensnegl.jpg", "Friday, January 22, at 1:00 p.m."),
    _block("161934/Arian-Šajina.jpg", "Friday, January 22, at 2:00 p.m."),
    _block("Flet.jpg", "Torsdag 28. januar kl. 14"),
)


def test_parse_page_images():
    images = up.parse_page_images(PAGE, PAGE_URL, TODAY)
    assert images.default == f"{UPLOADS}/_landscape1200/Worksharing.jpg"
    assert images.blocks == [
        (12, 11, datetime.time(14, 0), f"{UPLOADS}/_x1200/Spiral.jpg"),
        (1, 22, datetime.time(13, 0), f"{UPLOADS}/_x1200/N%C3%B8gensnegl.jpg"),
        (1, 22, datetime.time(14, 0), f"{UPLOADS}/_x1200/161934/Arian-%C5%A0ajina.jpg"),
        (1, 28, datetime.time(14, 0), f"{UPLOADS}/_x1200/Flet.jpg"),
    ]


def test_page_images_for_day():
    images = up.parse_page_images(PAGE, PAGE_URL, TODAY)
    jan22 = datetime.date(2027, 1, 22)
    assert images.for_day(datetime.date(2026, 12, 11), None).endswith("/Spiral.jpg")
    # Two worksharings that day: told apart by the start time.
    assert "N%C3%B8gensnegl" in images.for_day(jan22, datetime.time(13, 0))
    assert "Arian" in images.for_day(jan22, datetime.time(14, 0))
    # Neither time, or a day without a block: the page's own image.
    assert images.for_day(jan22, datetime.time(16, 0)) == images.default
    assert images.for_day(datetime.date(2027, 2, 1), None) == images.default


def test_parse_page_images_ignores_off_site_images():
    html = _page(_block("x.jpg", "Friday, December 11")).replace(
        "https://www.udviklingsplatformen.dk", "https://cdn.example.org"
    )
    images = up.parse_page_images(html, PAGE_URL, TODAY)
    assert images == up.PageImages()


def test_build_records_uses_page_image():
    item = _parse(_item(dates="22. January, 2027", content="<p>Kl. 14</p>"))
    images = up.parse_page_images(PAGE, PAGE_URL, TODAY)
    (rec,) = up.build_records(item, TODAY, images)
    assert rec["image_url"].endswith("/Arian-%C5%A0ajina.jpg")


def _up_item(item_id: str, dates: str, content: str) -> str:
    return _item(
        item_id=item_id,
        dates=dates,
        type_="UP event",
        title="Time in Space Worksharing: X",
        link=f'<a href="{PAGE_URL}">Learn more about Tid i Rum worksharings</a>',
        content=content,
    )


def test_scrape_fetches_linked_up_page_once():
    calendar = MagicMock(
        text=_up_item("1", "11. December, 2099", "<p>2:00 p.m.</p>")
        + _up_item("2", "22. January, 2100", "<p>1:00 p.m.</p>")
        + _item(item_id="3", dates="23. October, 2099")  # links off UP: no fetch
    )
    page = MagicMock(text=PAGE.replace("December 11", "December 11, 2099"))
    session = MagicMock()
    session.get.side_effect = [MagicMock(text=""), calendar, page]
    with patch.object(up, "make_session", return_value=session):
        records = up.scrape()

    assert [c.args[0] for c in session.get.call_args_list] == [
        up.EVENTS_URL,
        up.EVENTS_URL,
        PAGE_URL,
    ]
    assert [r["image_url"].rpartition("/")[2] for r in records] == [
        "Spiral.jpg",
        "N%C3%B8gensnegl.jpg",
        "",
    ]


def test_scrape_without_readable_page_has_no_image():
    calendar = MagicMock(text=_up_item("1", "11. December, 2099", "<p>2 p.m.</p>"))
    failing = MagicMock()
    failing.raise_for_status.side_effect = RuntimeError("503")
    session = MagicMock()
    session.get.side_effect = [MagicMock(text=""), calendar, failing]
    with patch.object(up, "make_session", return_value=session):
        (rec,) = up.scrape()
    assert rec["image_url"] == ""
