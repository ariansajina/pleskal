"""Unit tests for scrapers/base.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from scrapers.base import build_arg_parser, get_soup, scrape_url_list, write_output

# ── get_soup ──────────────────────────────────────────────────────────────────


def test_get_soup_returns_parsed_html():
    session = MagicMock()
    resp = MagicMock()
    resp.text = "<html><body><p>Hello</p></body></html>"
    session.get.return_value = resp

    soup = get_soup("https://example.com", session)

    assert soup.find("p").get_text() == "Hello"
    resp.raise_for_status.assert_called_once()


def test_get_soup_raises_on_http_error():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")

    with pytest.raises(requests.HTTPError):
        get_soup("https://example.com/missing", session)


# ── build_arg_parser ──────────────────────────────────────────────────────────


def test_build_arg_parser_defaults():
    parser = build_arg_parser("Test scraper", "out.json")
    args = parser.parse_args([])
    assert args.output == "out.json"
    assert args.dry_run is False
    assert args.verbose is False
    assert args.delay == 0.5


def test_build_arg_parser_flags():
    parser = build_arg_parser("Test scraper", "out.json")
    args = parser.parse_args(["--output", "custom.json", "--dry-run", "--verbose", "--delay", "1.5"])
    assert args.output == "custom.json"
    assert args.dry_run is True
    assert args.verbose is True
    assert args.delay == 1.5


def test_build_arg_parser_no_delay():
    parser = build_arg_parser("Test scraper", "out.json", include_delay=False)
    args = parser.parse_args([])
    assert not hasattr(args, "delay")


# ── scrape_url_list ───────────────────────────────────────────────────────────


def test_scrape_url_list_single_dict_result():
    session = MagicMock()
    scrape_detail = MagicMock(return_value={"title": "Event A"})

    results = scrape_url_list(["https://example.com/1"], session, scrape_detail, delay=0)

    assert results == [{"title": "Event A"}]
    scrape_detail.assert_called_once_with("https://example.com/1", session)


def test_scrape_url_list_list_result():
    session = MagicMock()
    scrape_detail = MagicMock(return_value=[{"title": "A"}, {"title": "B"}])

    results = scrape_url_list(["https://example.com/1"], session, scrape_detail, delay=0)

    assert results == [{"title": "A"}, {"title": "B"}]


def test_scrape_url_list_none_result_skipped():
    session = MagicMock()
    scrape_detail = MagicMock(return_value=None)

    results = scrape_url_list(["https://example.com/1"], session, scrape_detail, delay=0)

    assert results == []


def test_scrape_url_list_empty_list_result_skipped():
    session = MagicMock()
    scrape_detail = MagicMock(return_value=[])

    results = scrape_url_list(["https://example.com/1"], session, scrape_detail, delay=0)

    assert results == []


def test_scrape_url_list_multiple_urls():
    session = MagicMock()
    scrape_detail = MagicMock(side_effect=[{"title": "A"}, {"title": "B"}])

    with patch("scrapers.base.time.sleep") as mock_sleep:
        results = scrape_url_list(
            ["https://example.com/1", "https://example.com/2"],
            session,
            scrape_detail,
            delay=0.5,
        )

    assert results == [{"title": "A"}, {"title": "B"}]
    # sleep called between requests but not after the last one
    mock_sleep.assert_called_once_with(0.5)


def test_scrape_url_list_no_sleep_after_last_url():
    session = MagicMock()
    scrape_detail = MagicMock(return_value={"title": "Only"})

    with patch("scrapers.base.time.sleep") as mock_sleep:
        scrape_url_list(["https://example.com/1"], session, scrape_detail, delay=1.0)

    mock_sleep.assert_not_called()


# ── write_output ──────────────────────────────────────────────────────────────


def test_write_output_dry_run_prints(capsys):
    events = [{"title": "Test"}]
    write_output(events, "ignored.json", dry_run=True)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == events


def test_write_output_writes_file(tmp_path):
    events = [{"title": "Test"}]
    out = tmp_path / "out.json"
    write_output(events, str(out), dry_run=False)

    assert out.exists()
    assert json.loads(out.read_text()) == events


def test_write_output_prints_count(tmp_path, capsys):
    events = [{"title": "A"}, {"title": "B"}]
    out = tmp_path / "out.json"
    write_output(events, str(out), dry_run=False)

    captured = capsys.readouterr()
    assert "2" in captured.out
