"""Unit tests for scrapers/dansehallerne_workshops.py helper functions."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock

import requests

from scrapers.dansehallerne_workshops import (
    collect_workshop_urls,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


_MINIMAL_META_HTML = """
<html><body>
  <section class="event-meta-infos">
    <div class="meta-info table">
      <div class="row"><div class="key">Title</div><div class="value">Body Awareness Workshop</div></div>
      <div class="row"><div class="key">Date</div><div class="value">15.6.2026, 10:00</div></div>
      <div class="row"><div class="key">Venue</div><div class="value">Studio 4</div></div>
    </div>
  </section>
</body></html>
"""


# ── collect_workshop_urls ─────────────────────────────────────────────────────


def test_collect_workshop_urls_extracts_matching_hrefs():
    html = """
    <html><body>
      <a href="/en/professionals/workshop/101/">Workshop 1</a>
      <a href="/en/professionals/masterclass/202">Workshop 2</a>
      <a href="/en/about/">Not a workshop</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_workshop_urls(session)
    assert len(urls) == 2
    assert "https://dansehallerne.dk/en/professionals/workshop/101/" in urls
    assert "https://dansehallerne.dk/en/professionals/masterclass/202" in urls


def test_collect_workshop_urls_ignores_public_program_links():
    # Links under /en/public-program/ should NOT be picked up by the workshops scraper
    html = """
    <html><body>
      <a href="/en/public-program/workshop/456/">Public programme event</a>
      <a href="/en/professionals/workshop/789/">Professionals event</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_workshop_urls(session)
    assert len(urls) == 1
    assert "https://dansehallerne.dk/en/professionals/workshop/789/" in urls
    assert all("/en/public-program/" not in u for u in urls)


def test_collect_workshop_urls_deduplicates():
    html = """
    <html><body>
      <a href="/en/professionals/workshop/101/">First link</a>
      <a href="/en/professionals/workshop/101/">Duplicate link</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_workshop_urls(session)
    assert len(urls) == 1


# ── scrape_detail ─────────────────────────────────────────────────────────────


def test_scrape_detail_returns_records():
    session = _mock_session(_MINIMAL_META_HTML)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert len(results) == 1
    assert results[0]["title"] == "Body Awareness Workshop"
    assert results[0]["is_wheelchair_accessible"] is True


def test_scrape_detail_category_always_workshop():
    # Even if the meta table says "performance", workshops scraper always returns "workshop"
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Some Event</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 18:00</div></div>
          <div class="row"><div class="key">Type</div><div class="value">Performance</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert len(results) == 1
    assert results[0]["category"] == "workshop"


def test_scrape_detail_external_source_is_dansehallerne():
    session = _mock_session(_MINIMAL_META_HTML)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert results[0]["external_source"] == "dansehallerne"


def test_scrape_detail_http_error_returns_empty():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    assert (
        scrape_detail("https://dansehallerne.dk/en/professionals/workshop/1/", session)
        == []
    )


def test_scrape_detail_no_meta_returns_empty():
    session = _mock_session("<html><body><p>No meta here</p></body></html>")
    assert (
        scrape_detail("https://dansehallerne.dk/en/professionals/workshop/1/", session)
        == []
    )


def test_scrape_detail_no_title_returns_empty():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    assert (
        scrape_detail("https://dansehallerne.dk/en/professionals/workshop/1/", session)
        == []
    )


def test_scrape_detail_no_date_returns_empty():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">My Workshop</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    assert (
        scrape_detail("https://dansehallerne.dk/en/professionals/workshop/1/", session)
        == []
    )


def test_scrape_detail_free_admission_in_description():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Free Workshop</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 10:00</div></div>
        </div>
      </section>
      <div id="event-entry-content"><p>Free admission. Open to all.</p></div>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert results[0]["is_free"] is True
    assert results[0]["price_note"] == "Free admission"


def test_scrape_detail_ticket_button_means_not_free():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Paid Workshop</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 10:00</div></div>
        </div>
        <button class="basm_select">Buy tickets</button>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert results[0]["is_free"] is False


def test_scrape_detail_no_ticket_button_means_free():
    session = _mock_session(_MINIMAL_META_HTML)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert results[0]["is_free"] is True


def test_scrape_detail_ics_button_timestamps():
    import calendar

    start_ts = calendar.timegm(datetime.date(2030, 6, 1).timetuple())
    end_ts = start_ts + 5400  # 1.5 hours
    html = f"""
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Workshop</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2030, 10:00</div></div>
        </div>
      </section>
      <button class="js-download" data-start="{start_ts}" data-end="{end_ts}">ICS</button>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert len(results) == 1
    assert results[0]["end_datetime"] is not None


def test_scrape_detail_duration_sets_end_time():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Workshop</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 10:00</div></div>
          <div class="row"><div class="key">Duration</div><div class="value">3 hours</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail(
        "https://dansehallerne.dk/en/professionals/workshop/1/", session
    )
    assert results[0]["end_datetime"] is not None


def test_scrape_detail_source_url_preserved():
    session = _mock_session(_MINIMAL_META_HTML)
    url = "https://dansehallerne.dk/en/professionals/workshop/42/"
    results = scrape_detail(url, session)
    assert results[0]["source_url"] == url
