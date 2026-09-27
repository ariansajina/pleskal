---
name: scraper-health
description: Check that every active pleskal scraper is still working — not gone stale, and producing events that match their source pages (working source link, image, English description, sensible times). Samples 1–3 scraped events per scraper from the live site, compares them with the venue's own page, and writes a one-row-per-scraper health table. Use when asked to check scraper health, audit scraped events, or when run as the weekly/monthly scraper-health routine.
---

# Scraper health check

Paths are relative to the repo root. Evidence comes from the **live public
site** (`https://pleskal.dk` by default) and the venues' own pages, so no
database access or secrets are needed.

## 1. Collect evidence

```bash
OUT="${CLAUDE_SCRATCHPAD:-/tmp}/scraper-health-$(date +%F)"   # any scratch dir works
uv run python .claude/skills/scraper-health/collect.py --out "$OUT"
```

Options: `--samples N` (events per scraper, default 3), `--only <name>`
(repeatable), `--seed N` (repeatable sample), `--base-url` (e.g. staging).

The script:

- takes the active scrapers from `scrapers/registry.py`, skipping those
  retired via `SCRAPER_DISABLED_AFTER` in
  `events/management/commands/run_scrapers.py` (listed as "Retired");
- reads each publisher profile (`/accounts/publishers/<external_source>/`,
  every upcoming event; the two dansehallerne scrapers are split by their
  `category_scope`) → `upcoming_count`, `upcoming_titles`, `last_listed`
  (the furthest-out event), `duplicate_cards`;
- picks up to N events with **distinct titles** at random and, per event,
  reads the pleskal detail page (JSON-LD times, venue, category, image,
  "Automatically translated from Danish" note, description), HEADs the
  image, GETs the "More info / tickets" source link and dumps the source
  page's text to `$OUT/sources/<slug>.txt`;
- pre-computes flags: HTTP errors, missing own image (publisher default /
  logo shown instead), empty description, Danish-looking description
  (crude stopword heuristic), mojibake, and odd times (00:00 start, 23:59
  end, start before 08:00 or from 23:00, off-5-minute starts, zero/negative,
  <15 min or >12 h durations, >1 year out).

It prints a short per-scraper summary; the full evidence is in
`$OUT/scraper_health.json`. Flags are **leads, not verdicts** — confirm each
one against the source before counting it.

## 2. Compare each sample with its source page

For every sampled event, read `$OUT/sources/<slug>.txt` (or fetch the
`source_url` with WebFetch when the text dump is thin — some venues render
dates with JavaScript: FÅR302 takes performance times from the
teaterbilletter.dk API, Sydhavn Teater from its CMS API, Warehouse9 from an
iCal feed; read the scraper module in `scrapers/` to see where a field
really comes from before calling it wrong). Check:

| Check | Healthy when |
|---|---|
| Source link | Returns 200 and is the page for *this* event (not a homepage, 404 page or another show) |
| Title | Matches the source (translation/casing differences are fine) |
| Date & time | The start date/time is one the source lists for this event; the end/duration agrees with the source's stated duration. For a multi-date run, pleskal should normally have one event per performance, not one event spanning weeks |
| Time plausibility | Not a 00:00 start, 23:59 end, multi-day or near-zero duration, or a 03:00-type hour — **unless the source itself says so** (an exhibition open for weeks is fine) |
| Venue | Matches the source (or the scraper's default venue when the source names none) |
| Image | Event has its own image (`has_own_image`); if not, check whether the source has one (`source_og_image` / the page) — missing only when the source has one is a problem |
| Language | Description on pleskal is English: either an English original (`machine_translated: false`) or a readable machine translation (`true`). Flag Danish text, mojibake (`â ¢`, `Ã¸`), or translations so garbled the meaning is lost (names mangled differently in each sentence is a minor issue) |
| Description | Present and about this event (not a cookie banner, menu text or another event's blurb) |

## 3. Check for staleness

- `upcoming_count` of 0, or a `last_listed` date only a few weeks out,
  while the source's programme runs further → stale.
- Open the scraper's `listing_url` (from the JSON; for Warehouse9 that is an
  iCal feed — `https://warehouse9.dk/events/` is the human listing) and pick
  1–2 upcoming events there. Each should appear in `upcoming_titles`
  (allow for translated titles and for events announced in the last day or
  two — the scrape cron runs daily). Several missing events → the scraper
  is missing part of the programme.
- A small `upcoming_count` is not stale on its own if the source's own
  programme is small; say which it is.
- `duplicate_cards` (same title and time listed twice) → needs work.

## 4. Grade and report

One grade per scraper:

- **Healthy** — every sampled check passes (a missing end time or a
  harmless oddity the source itself has is fine).
- **Needs work** — works overall but with a real defect: one wrong time or
  broken link among the samples, images missing where the source has them,
  poor translations, duplicates, a few programme events missing.
- **Unhealthy** — stale (no or clearly too few upcoming events), or the
  samples are systematically wrong: dates/times, titles, links, Danish or
  empty descriptions across most samples, or the collector crashed on it.

Write the report to `$OUT/report.md` and give it as the final reply, in
this shape (keep the comment to one line; name the event and the concrete
problem, e.g. "*Feerne*: one 00:00–23:59 event spanning 14 Aug–18 Sep; the
source lists individual 19:30 shows"):

```markdown
# Scraper health — YYYY-MM-DD

| Scraper | Status | Upcoming | Comment |
|---|---|---|---|
| dansehallerne | ✅ Healthy | 65 | 3/3 samples match the source |
| faar302 | ⚠️ Needs work | 63 | *Feerne*: … |
| some_scraper | ❌ Unhealthy | 1 | Source programme lists … upcoming events; only 1 on pleskal |

Retired (not checked): toastercph, taornby
```

Below the table, list the sampled events per scraper (pleskal URL → source
URL) so a human can re-check a verdict quickly. Don't fix scrapers as part
of this skill — it only reports.

## 5. File an issue (when asked)

If the prompt that invoked the skill asks for an issue, and **any** row is
Needs work or Unhealthy, open **one** GitHub issue in `ariansajina/pleskal`
covering every problem found — never one issue per scraper:

- Title: `Scraper health YYYY-MM-DD: N scraper(s) need attention`
- Body: the full table, then one `###` section per scraper that is not
  Healthy listing each concrete problem with the pleskal URL, the source
  URL and what differs (expected vs. found), then the sampled-events list.
- If an earlier scraper-health issue is still open, link it in the body
  ("Previous report: #…") so recurring problems are visible.
- End the body with the Claude Code attribution footer.

When every scraper is Healthy, open no issue; just give the report.
