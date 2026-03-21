"""Shared utilities for pleskal scrapers.

Provides common HTTP helpers and CLI utilities reused across scrapers.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pleskalScraper/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
}

log = logging.getLogger(__name__)


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Fetch *url* and return a BeautifulSoup parse tree."""
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def build_arg_parser(
    description: str,
    default_output: str,
    *,
    include_delay: bool = True,
) -> argparse.ArgumentParser:
    """
    Build a standard argument parser for a scraper CLI.

    Args:
        description:    Short description shown in --help.
        default_output: Default filename for --output.
        include_delay:  Whether to include the --delay argument
                        (HTML scrapers need it; API-based scrapers don't).
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--output",
        "-o",
        default=default_output,
        help=f"Output JSON file path (default: {default_output})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout instead of writing a file",
    )
    if include_delay:
        parser.add_argument(
            "--delay",
            type=float,
            default=0.5,
            help="Delay in seconds between detail page requests (default: 0.5)",
        )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def scrape_url_list(
    urls: list[str],
    session: requests.Session,
    scrape_detail: Callable[[str, requests.Session], dict | list[dict] | None],
    delay: float = 0.5,
) -> list[dict]:
    """
    Iterate over *urls*, call *scrape_detail* for each, and collect results.

    *scrape_detail* may return:
      - a single dict (hautscene style)
      - a list of dicts (dansehallerne style — one URL can yield multiple records)
      - None / empty list to signal a parse failure (silently skipped)
    """
    events: list[dict] = []
    for i, url in enumerate(urls, 1):
        log.info("[%d/%d] Scraping %s", i, len(urls), url)
        result = scrape_detail(url, session)
        if isinstance(result, list):
            events.extend(result)
        elif result is not None:
            events.append(result)
        if i < len(urls):
            time.sleep(delay)
    log.info("Scraped %d event records from %d pages", len(events), len(urls))
    return events


def write_output(events: list[dict], output_path: str, dry_run: bool) -> None:
    """Serialise *events* to JSON and either print or write to *output_path*."""
    output = json.dumps(events, indent=2, ensure_ascii=False)
    if dry_run:
        print(output)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {len(events)} events to {output_path}")
