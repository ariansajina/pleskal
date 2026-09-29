"""Gather evidence for the scraper-health skill from the live site.

For every active scraper in ``scrapers/registry.py`` this reads the
publisher's public profile page (all upcoming events), samples a few events
at random, and for each sample fetches the pleskal detail page and the
source page it links to. Mechanical checks (source link status, own image,
translation note, language heuristic, mojibake, odd times) are computed
here; the side-by-side comparison with the source page is left to the agent
running the skill, using the source-page text dumps written to ``--out``.

Only public pages are read — no database or secrets needed — and the
User-Agent contains "bot", so the analytics middleware ignores the visits.
The event feeds are deliberately not used: every feed request increments the
FeedHit counters reported in the weekly digest.

Usage (from the repo root):
    uv run python .claude/skills/scraper-health/collect.py --out DIR
"""

from __future__ import annotations

import argparse
import ast
import datetime
import importlib
import json
import random
import re
import sys
import zoneinfo
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from scrapers.registry import SOURCES, ScraperSource  # noqa: E402

USER_AGENT = "pleskal-scraper-health-bot/1.0 (+https://pleskal.dk/about/)"
TIMEOUT = 20

# Listing-page constants the scraper modules define, most specific first.
LISTING_ATTRS = (
    "PROGRAM_URL",
    "CALENDAR_URL",
    "WORKSHOPS_URL",
    "HOME_URL",
    "ICAL_URL",
    "BASE_URL",
)

DANISH_MARKERS = (
    "og", "er", "det", "af", "på", "til", "med", "som", "der", "ikke",
    "en", "et", "den", "har", "vi", "jeg", "fra", "kan", "også", "forestilling",
)  # fmt: skip
ENGLISH_MARKERS = (
    "the", "and", "of", "to", "is", "in", "with", "for", "this", "that",
    "are", "on", "by", "from", "it", "as", "an", "be", "you", "performance",
)  # fmt: skip
MOJIBAKE_RE = re.compile(r"Ã.|â€|Â[^A-Za-z]|â [^\w\s]|�")

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
# A clock time on a source page: "20:00", "kl. 20.00". Dates such as
# "09.09.26" don't match (a time must not touch another digit, dot or colon).
CLOCK_RE = re.compile(r"(?<![\d.:])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d.:])")
TICKETING_API_URL = "https://teaterbilletter.dk/api/events"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    s.headers["Accept-Language"] = "en,da;q=0.8"
    return s


def disabled_after() -> dict[str, datetime.date]:
    """Read SCRAPER_DISABLED_AFTER from run_scrapers.py without importing Django."""
    path = REPO_ROOT / "events/management/commands/run_scrapers.py"
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        target = getattr(node, "target", None) or (
            node.targets[0] if isinstance(node, ast.Assign) else None
        )
        if isinstance(target, ast.Name) and target.id == "SCRAPER_DISABLED_AFTER":
            value = node.value  # ty: ignore[unresolved-attribute]
            result = {}
            for key, call in zip(value.keys, value.values, strict=True):
                args = [a.value for a in call.args]
                result[key.value] = datetime.date(*args)
            return result
    return {}


def listing_url(source: ScraperSource) -> str | None:
    module = importlib.import_module(source.scrape.__module__)
    for attr in LISTING_ATTRS:
        if hasattr(module, attr):
            return getattr(module, attr)
    return None


def _attr(tag, name: str) -> str:
    """A single-valued HTML attribute as a string ("" when absent)."""
    value = tag.get(name)
    return value if isinstance(value, str) else ""


def parse_cards(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for a in soup.select('a.card[href^="/events/"]'):
        title = a.select_one(".event-title")
        meta = a.select_one(".event-meta")
        badges = [
            cls.removeprefix("badge--")
            for b in a.select(".badge")
            for cls in b.get_attribute_list("class")
            if cls.startswith("badge--")
        ]
        cards.append(
            {
                "url": urljoin(base_url, _attr(a, "href")),
                "title": title.get_text(strip=True) if title else "",
                "when": " ".join(meta.get_text(" ", strip=True).split())
                if meta
                else "",
                "badges": badges,
            }
        )
    return cards


def language_heuristic(text: str) -> dict:
    words = re.findall(r"[a-zæøå]+", text.lower())
    da = sum(w in DANISH_MARKERS for w in words)
    en = sum(w in ENGLISH_MARKERS for w in words)
    if not words:
        guess = "empty"
    elif da > en * 1.5 and da >= 5:
        guess = "danish"
    elif en > da * 1.5 and en >= 5:
        guess = "english"
    else:
        guess = "unclear"
    return {"guess": guess, "danish_markers": da, "english_markers": en}


def time_flags(start: datetime.datetime, end: datetime.datetime | None) -> list[str]:
    """Heuristics for implausible times; each flag needs checking against the source."""
    flags = []
    now = datetime.datetime.now(tz=start.tzinfo)
    if start.hour == 0 and start.minute == 0:
        flags.append("starts at 00:00 (source probably gave a date without a time)")
    elif start.hour < 8 or start.hour >= 23:
        flags.append(f"unusual start hour {start:%H:%M}")
    if start.minute % 5:
        flags.append(f"start minute not on a 5-minute mark ({start:%H:%M})")
    if start - now > datetime.timedelta(days=365):
        flags.append("starts more than a year from now")
    if end is None:
        return flags  # common and fine for many sources; the report shows it
    duration = end - start
    if duration <= datetime.timedelta(0):
        flags.append(f"end is not after start (duration {duration})")
    elif duration < datetime.timedelta(minutes=15):
        flags.append(f"very short duration ({duration})")
    elif duration > datetime.timedelta(hours=12):
        flags.append(
            f"long duration ({duration}); fine for a multi-day run/exhibition, "
            "suspicious for a single performance"
        )
    if end.hour == 23 and end.minute == 59:
        flags.append("ends at 23:59 (source probably gave a date without a time)")
    return flags


def clock_shift_flags(start: datetime.datetime, source_text: str) -> list[str]:
    """Flag a start time that the source page doesn't list but lists 1-2 h off.

    That offset is what a time-zone bug produces (a UTC time stored as
    Copenhagen time, or the reverse): the page says "kl. 20.00", pleskal 18:00.
    """
    local = start.astimezone(CPH_TZ)
    times = {(int(h), int(m)) for h, m in CLOCK_RE.findall(source_text)}
    if not times or (local.hour, local.minute) in times:
        return []
    shifted = sorted(
        f"{h:02d}:{m:02d}"
        for h, m in times
        if m == local.minute and abs(h - local.hour) in (1, 2)
    )
    if not shifted:
        return []
    return [
        (
            f"time zone? pleskal starts at {local:%H:%M} (Copenhagen), which the "
            f"source page doesn't list, but it lists {', '.join(shifted)}"
        )
    ]


def ticketing_venue_codes(source: ScraperSource) -> tuple[str, ...]:
    """Venue codes of a scraper built on scrapers/teaterbilletter.py, else ()."""
    module = importlib.import_module(source.scrape.__module__)
    return tuple(getattr(getattr(module, "VENUE", None), "venue_codes", ()) or ())


def fetch_ticketing_events(
    session: requests.Session, venue_codes: tuple[str, ...]
) -> list[dict]:
    events: list[dict] = []
    page = 1
    while True:
        resp = session.get(
            TICKETING_API_URL,
            params={"page": page, "pageSize": 30, "venueCodes": ",".join(venue_codes)},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        events += data.get("items") or []
        if page >= ((data.get("pagination") or {}).get("pageCount") or 1):
            return events
        page += 1


def ticketing_flags(
    start: datetime.datetime, title: str, api_events: list[dict]
) -> list[str]:
    """Check a start time against the teaterbilletter.dk API, independently.

    The API's times are UTC without an offset. This converts them here rather
    than through the scraper's own code, so a conversion bug there can't hide
    itself; a start that equals the API's UTC time read as Copenhagen time is
    reported as exactly that bug.
    """

    def norm(text: str) -> str:
        return " ".join(text.casefold().split())

    matches = [e for e in api_events if norm(e.get("title") or "") == norm(title)]
    if not matches:
        return [f"'{title}' is not in the teaterbilletter.dk API for this venue"]
    naive = set()
    for event in matches:
        values = [s.get("dateTime") for s in event.get("scheduledShows") or []]
        values += [s.get("showTime") for s in event.get("shows") or []]
        for value in values:
            try:
                naive.add(datetime.datetime.fromisoformat(value).replace(tzinfo=None))
            except TypeError, ValueError:
                continue
    utc_as_local = {t.replace(tzinfo=datetime.UTC).astimezone(CPH_TZ) for t in naive}
    if start in utc_as_local:
        return []
    local = start.astimezone(CPH_TZ)
    if local in {t.replace(tzinfo=CPH_TZ) for t in naive}:
        return [
            (
                f"TIME-ZONE BUG: start {local:%Y-%m-%d %H:%M} is the API's UTC "
                "time read as Copenhagen time (the real start is 1-2 h later)"
            )
        ]
    return [
        (
            f"start {local:%Y-%m-%d %H:%M} (Copenhagen) is not a performance "
            "time in the teaterbilletter.dk API"
        )
    ]


def inspect_event(
    session: requests.Session,
    card: dict,
    out_dir: Path,
    ticketing_events: list[dict] | None = None,
) -> dict:
    result: dict = {"pleskal_url": card["url"], "card": card, "problems": []}
    resp = session.get(card["url"], timeout=TIMEOUT)
    result["pleskal_status"] = resp.status_code
    if resp.status_code != 200:
        result["problems"].append(f"pleskal detail page returned {resp.status_code}")
        return result
    soup = BeautifulSoup(resp.text, "html.parser")

    data: dict = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if parsed.get("@type") == "Event":
            data = parsed
            break

    start = datetime.datetime.fromisoformat(data["startDate"])
    end = (
        datetime.datetime.fromisoformat(data["endDate"])
        if data.get("endDate")
        else None
    )
    prose = soup.select_one(".prose-content")
    description = prose.get_text("\n", strip=True) if prose else ""
    source_link = next(
        (
            _attr(a, "href")
            for a in soup.select("a.btn--primary[href]")
            if "More info" in a.get_text()
        ),
        None,
    )
    og_image = soup.select_one('meta[property="og:image"]')
    image_url = _attr(og_image, "content") if og_image else None
    category = soup.select_one(".event-tags .badge")

    result.update(
        {
            "title": data.get("name"),
            "category": category.get_text(strip=True) if category else None,
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "duration": str(end - start) if end else None,
            "venue": data.get("location", {}).get("name"),
            "address": data.get("location", {}).get("address"),
            "source_url": source_link,
            "image_url": image_url,
            "machine_translated": "Automatically translated from Danish" in resp.text,
            "description": description,
            "time_flags": time_flags(start, end),
            "language": language_heuristic(description),
            "mojibake": sorted(set(MOJIBAKE_RE.findall(description)))[:10],
        }
    )

    # Own image vs. the publisher default / logo fallback (served from /static/).
    if not image_url or "/static/" in urlparse(image_url).path:
        result["has_own_image"] = False
    else:
        result["has_own_image"] = True
        img = session.head(image_url, timeout=TIMEOUT, allow_redirects=True)
        result["image_status"] = img.status_code
        if img.status_code != 200:
            result["problems"].append(f"image URL returned {img.status_code}")

    if not description:
        result["problems"].append("empty description")
    if result["language"]["guess"] == "danish":
        result["problems"].append("description looks Danish (heuristic)")
    if result["mojibake"]:
        result["problems"].append(f"mojibake in description: {result['mojibake']}")
    if ticketing_events is not None:
        result["problems"] += ticketing_flags(
            start, data.get("name") or "", ticketing_events
        )

    if not source_link:
        result["problems"].append("no source link")
        return result
    try:
        src = session.get(source_link, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        result["source_status"] = f"error: {exc.__class__.__name__}: {exc}"
        result["problems"].append("source link unreachable")
        return result
    result["source_status"] = src.status_code
    result["source_final_url"] = src.url
    if src.status_code != 200:
        result["problems"].append(f"source link returned {src.status_code}")
    src_soup = BeautifulSoup(src.text, "html.parser")
    og_src_image = src_soup.select_one('meta[property="og:image"]')
    result["source_og_image"] = _attr(og_src_image, "content") if og_src_image else None
    for tag in src_soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(
        line for line in src_soup.get_text("\n", strip=True).splitlines() if line
    )
    slug = urlparse(card["url"]).path.strip("/").split("/")[-1]
    dump = out_dir / "sources" / f"{slug}.txt"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(text)
    result["source_text_file"] = str(dump)
    result["problems"] += clock_shift_flags(start, text)
    return result


def check_scraper(
    session: requests.Session,
    source: ScraperSource,
    base_url: str,
    samples: int,
    rng: random.Random,
    out_dir: Path,
) -> dict:
    slug = source.external_source
    profile = f"{base_url}/accounts/publishers/{slug}/"
    report: dict = {
        "scraper": source.name,
        "external_source": slug,
        "publisher_page": profile,
        "listing_url": listing_url(source),
        "category_scope": source.category_scope,
        "problems": [],
    }
    resp = session.get(profile, timeout=TIMEOUT)
    report["publisher_status"] = resp.status_code
    if resp.status_code != 200:
        report["problems"].append(f"publisher page returned {resp.status_code}")
        report["upcoming_count"] = 0
        report["samples"] = []
        return report

    cards = parse_cards(resp.text, base_url)
    if source.category_scope:
        cards = [c for c in cards if set(c["badges"]) & set(source.category_scope)]
    report["upcoming_count"] = len(cards)
    report["upcoming_titles"] = sorted({c["title"] for c in cards})
    report["last_listed"] = cards[-1]["when"] if cards else None

    seen: dict[tuple[str, str], int] = {}
    for c in cards:
        seen[(c["title"], c["when"])] = seen.get((c["title"], c["when"]), 0) + 1
    report["duplicate_cards"] = [
        f"{title} @ {when} (x{n})" for (title, when), n in seen.items() if n > 1
    ]
    if not cards:
        report["problems"].append("no upcoming events on pleskal")

    # One sample per distinct title where possible, so a long run of one show
    # doesn't crowd out the rest of the programme.
    by_title: dict[str, list[dict]] = {}
    for c in cards:
        by_title.setdefault(c["title"], []).append(c)
    titles = rng.sample(sorted(by_title), k=min(samples, len(by_title)))

    # Scrapers built on the teaterbilletter.dk API get their times checked
    # against it (the source pages of some of them don't show times).
    ticketing_events = None
    venue_codes = ticketing_venue_codes(source)
    report["ticketing_venue_codes"] = list(venue_codes)
    if venue_codes:
        try:
            ticketing_events = fetch_ticketing_events(session, venue_codes)
        except (requests.RequestException, ValueError) as exc:
            report["problems"].append(f"teaterbilletter.dk API unreachable: {exc}")
    report["samples"] = [
        inspect_event(session, rng.choice(by_title[t]), out_dir, ticketing_events)
        for t in titles
    ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://pleskal.dk")
    parser.add_argument("--samples", type=int, default=3, help="events per scraper")
    parser.add_argument("--only", action="append", help="limit to these scrapers")
    parser.add_argument("--seed", type=int, help="make the random sample repeatable")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)  # noqa: S311 - sampling, not security
    session = _session()
    base_url = args.base_url.rstrip("/")
    today = datetime.date.today()
    retired = {n: d for n, d in disabled_after().items() if today > d}

    results = {
        "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "base_url": base_url,
        "retired": {n: d.isoformat() for n, d in retired.items()},
        "scrapers": [],
    }
    for name, source in SOURCES.items():
        if name in retired or (args.only and name not in args.only):
            continue
        print(f"checking {name} ...", file=sys.stderr)
        try:
            report = check_scraper(
                session, source, base_url, args.samples, rng, args.out
            )
        except Exception as exc:  # keep going: one broken source isn't all
            report = {
                "scraper": name,
                "problems": [f"collector crashed: {exc.__class__.__name__}: {exc}"],
            }
        results["scrapers"].append(report)

    out_file = args.out / "scraper_health.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    for r in results["scrapers"]:
        problems = list(r.get("problems", []))
        for s in r.get("samples", []):
            problems += [f"{s.get('title')}: {p}" for p in s["problems"]]
            problems += [f"{s.get('title')}: {f}" for f in s.get("time_flags", [])]
            if "start" in s and not s.get("end"):
                problems.append(f"{s.get('title')}: (info) no end time")
        if r.get("duplicate_cards"):
            problems.append(f"duplicate cards: {r['duplicate_cards']}")
        print(f"\n## {r['scraper']}  upcoming={r.get('upcoming_count', '?')}")
        for p in problems or ["no automated flags"]:
            print(f"  - {p}")
    print(f"\nRetired (skipped): {', '.join(retired) or 'none'}")
    print(f"Full evidence: {out_file}")


if __name__ == "__main__":
    main()
