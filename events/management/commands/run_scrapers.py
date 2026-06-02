"""Unified management command to scrape all sources and import events.

Runs each scraper's ``scrape()`` function, writes the results to a temporary
JSON file, then invokes the corresponding ``import_*`` management command.
Each source is processed independently so a single failure does not block
the others.

Usage:
    python manage.py run_scrapers              # run all scrapers + imports
    python manage.py run_scrapers --dry-run    # preview without DB writes
    python manage.py run_scrapers --only hautscene --only sydhavnteater
"""

import datetime
import json
import logging
import os
import sys
import tempfile
import time
import traceback

from django.core.management import call_command
from django.core.management.base import BaseCommand

from scrapers.dansehallerne import scrape as scrape_dansehallerne
from scrapers.dansehallerne_workshops import (
    scrape as scrape_dansehallerne_workshops,
)
from scrapers.hautscene import scrape as scrape_hautscene
from scrapers.kbhdanser import scrape as scrape_kbhdanser
from scrapers.sort_hvid import scrape as scrape_sort_hvid
from scrapers.sydhavnteater import scrape as scrape_sydhavnteater
from scrapers.toastercph import scrape as scrape_toastercph
from scrapers.warehouse9 import scrape as scrape_warehouse9

log = logging.getLogger(__name__)

SCRAPERS = [
    (
        "dansehallerne",
        scrape_dansehallerne,
        {"delay": 0.5},
        "import_dansehallerne",
    ),
    (
        "dansehallerne_workshops",
        scrape_dansehallerne_workshops,
        {"delay": 0.5},
        "import_dansehallerne_workshops",
    ),
    (
        "hautscene",
        scrape_hautscene,
        {"delay": 0.5},
        "import_hautscene",
    ),
    (
        "sydhavnteater",
        scrape_sydhavnteater,
        {},
        "import_sydhavnteater",
    ),
    (
        "toastercph",
        scrape_toastercph,
        {"delay": 0.5},
        "import_toastercph",
    ),
    (
        "kbhdanser",
        scrape_kbhdanser,
        {"delay": 1.5},
        "import_kbhdanser",
    ),
    (
        "sort_hvid",
        scrape_sort_hvid,
        {"delay": 0.5},
        "import_sort_hvid",
    ),
    (
        "warehouse9",
        scrape_warehouse9,
        {},
        "import_warehouse9",
    ),
]

# Per-scraper auto-disable dates (inclusive cutoff). Past this date the
# scraper stops running and any events it previously imported are purged from
# the database (via the importer's stale-deletion path). Use this to retire
# one-off / festival sources that go stale after their run.
#
# Note: this differs from SCRAPER_<NAME>_ENABLED=false, which only pauses
# scraping and leaves existing events untouched (so it can be re-enabled).
SCRAPER_DISABLED_AFTER: dict[str, datetime.date] = {
    # Toaster retired 2026-05-03 — scraper off and its events removed.
    "toastercph": datetime.date(2026, 5, 3),
}


class Command(BaseCommand):
    help = "Run all scrapers and import events into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pass --dry-run to import commands (no DB writes).",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            help="Pass --skip-images to import commands.",
        )
        parser.add_argument(
            "--only",
            action="append",
            dest="only",
            metavar="SOURCE",
            help=(
                "Run only the named scraper(s). Can be repeated. "
                "Choices: dansehallerne, dansehallerne_workshops, "
                "hautscene, kbhdanser, sort_hvid, sydhavnteater, toastercph, "
                "warehouse9."
            ),
        )

    def handle(self, *args, **options):
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s %(message)s",
        )

        dry_run = options["dry_run"]
        skip_images = options["skip_images"]
        only = set(options["only"]) if options["only"] else None

        if only:
            valid = {name for name, *_ in SCRAPERS}
            unknown = only - valid
            if unknown:
                self.stderr.write(
                    self.style.ERROR(
                        f"Unknown source(s): {', '.join(sorted(unknown))}. "
                        f"Valid: {', '.join(sorted(valid))}"
                    )
                )
                sys.exit(1)

        results: list[tuple[str, bool, str]] = []

        for name, scrape_fn, scrape_kwargs, import_cmd in SCRAPERS:
            if only and name not in only:
                continue

            env_key = f"SCRAPER_{name.upper()}_ENABLED"
            if os.environ.get(env_key, "true").strip().lower() in {
                "false",
                "0",
                "no",
                "off",
            }:
                self.stdout.write(
                    self.style.WARNING(f"Skipping {name} ({env_key}=disabled)")
                )
                results.append((name, True, "disabled via env"))
                continue

            disabled_after = SCRAPER_DISABLED_AFTER.get(name)
            if disabled_after and datetime.date.today() > disabled_after:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {name} (disabled after {disabled_after.isoformat()})"
                    )
                )
                # Retired source: purge any events it left behind so they don't
                # linger in the database.
                self._cleanup_source(name, import_cmd, dry_run)
                results.append(
                    (name, True, f"disabled after {disabled_after.isoformat()}")
                )
                continue

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(f"{'=' * 60}"))
            self.stdout.write(self.style.HTTP_INFO(f"  {name}"))
            self.stdout.write(self.style.HTTP_INFO(f"{'=' * 60}"))

            t0 = time.monotonic()
            tmp_path = None

            try:
                # ── Scrape ─────────────────────────────────────────────
                self.stdout.write(f"Scraping {name} ...")
                events = scrape_fn(**scrape_kwargs)
                self.stdout.write(f"Scraped {len(events)} events from {name}")

                if not events:
                    self.stdout.write(
                        self.style.WARNING(f"No events from {name}, skipping import")
                    )
                    results.append((name, True, "0 events scraped"))
                    continue

                # ── Write temp JSON ────────────────────────────────────
                fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix=f"{name}_")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(events, f, ensure_ascii=False)

                # ── Import ─────────────────────────────────────────────
                self.stdout.write(
                    f"Importing {len(events)} events via {import_cmd} ..."
                )
                import_kwargs: dict = {"json_file": tmp_path}
                if dry_run:
                    import_kwargs["dry_run"] = True
                if skip_images:
                    import_kwargs["skip_images"] = True

                call_command(import_cmd, **import_kwargs)

                elapsed = time.monotonic() - t0
                msg = f"{len(events)} events, {elapsed:.1f}s"
                results.append((name, True, msg))
                self.stdout.write(self.style.SUCCESS(f"{name} done ({msg})"))

            except Exception:
                elapsed = time.monotonic() - t0
                tb = traceback.format_exc()
                self.stderr.write(self.style.ERROR(f"{name} FAILED ({elapsed:.1f}s):"))
                self.stderr.write(tb)
                results.append((name, False, f"error after {elapsed:.1f}s"))

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # ── Summary ────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Summary:"))
        failures = 0
        for name, ok, detail in results:
            status = self.style.SUCCESS("OK") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"  {name:30s} {status}  {detail}")
            if not ok:
                failures += 1

        if failures:
            self.stderr.write(self.style.ERROR(f"\n{failures} scraper(s) failed."))
            sys.exit(1)
        else:
            self.stdout.write(
                self.style.SUCCESS("\nAll scrapers completed successfully.")
            )

    def _cleanup_source(self, name: str, import_cmd: str, dry_run: bool) -> None:
        """Purge events left behind by a retired source.

        Invokes the source's import command with an empty event list, which
        triggers the importer's stale-deletion path: every event for that
        ``external_source`` is absent from the (empty) input and therefore
        deleted. Idempotent — once cleaned up, later runs find nothing to
        remove. Failures are logged but never abort the overall run.
        """
        self.stdout.write(f"Purging stale events for {name} via {import_cmd} ...")
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix=f"{name}_cleanup_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([], f)
            import_kwargs: dict = {"json_file": tmp_path}
            if dry_run:
                import_kwargs["dry_run"] = True
            call_command(import_cmd, **import_kwargs)
        except Exception:
            self.stderr.write(
                self.style.ERROR(
                    f"Cleanup for {name} failed:\n{traceback.format_exc()}"
                )
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
