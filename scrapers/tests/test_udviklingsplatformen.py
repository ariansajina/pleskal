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


# ── parse_time ────────────────────────────────────────────────────────────────


def test_parse_time_formats():
    assert up.parse_time("Doors at 4:00 PM, then talk") == datetime.time(16, 0)
    assert up.parse_time("from 6 p.m.") == datetime.time(18, 0)
    assert up.parse_time("12 pm sharp") == datetime.time(12, 0)
    assert up.parse_time("Starts 17:30") == datetime.time(17, 30)
    assert up.parse_time("Visning kl. 17") == datetime.time(17, 0)
    assert up.parse_time("Visning kl. 19.30") == datetime.time(19, 30)


def test_parse_time_takes_first_and_ignores_bare_dots():
    assert up.parse_time("4:00 PM showing. 6:00 p.m. dinner") == datetime.time(16, 0)
    assert up.parse_time("On 23.10 it costs 50.00 kr.") is None
    assert up.parse_time("No time given") is None


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
    assert up.determine_venue("Studio Nord", "", "Held at Baldersgade 6") == (
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


def test_build_records_skips_covered_venue():
    item = _parse(
        _item(link='<a href="https://warehouse9.dk/da/begivenhed/x/">Warehouse9</a>')
    )
    assert up.build_records(item, TODAY) == []


def test_build_records_skips_other_types():
    assert up.build_records(_parse(_item(type_="Open Call")), TODAY) == []


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


def test_scrape_requests_worksharing_filter():
    future = "23. October, 2099"
    response = MagicMock(
        text=_item(dates=future) + _item(item_id="2", dates=future, type_="Deadline")
    )
    session = MagicMock()
    session.get.return_value = response
    with patch.object(up, "make_session", return_value=session):
        records = up.scrape()

    args, kwargs = session.get.call_args
    assert args[0] == up.EVENTS_URL
    assert kwargs["params"] == {"category": "worksharing"}
    assert kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert [r["source_url"].rsplit("-", 1)[1] for r in records] == ["158590"]
