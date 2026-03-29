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
from scrapers.sydhavnteater import scrape as scrape_sydhavnteater
from scrapers.toastercph import scrape as scrape_toastercph

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
]


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
                "hautscene, kbhdanser, sydhavnteater, toastercph."
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
