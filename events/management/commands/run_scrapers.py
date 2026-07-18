"""Unified management command to scrape all sources and import events.

Runs each registered scraper's ``scrape()`` function (see
``scrapers/registry.py``), writes the results to a temporary JSON file, then
invokes the generic ``import_events`` management command for that source.
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

import sentry_sdk
from django.core.management import call_command
from django.core.management.base import BaseCommand

from scrapers.registry import SOURCES

log = logging.getLogger(__name__)

# Per-scraper auto-disable dates (inclusive cutoff). Past this date the
# scraper stops running, any events it previously imported are purged (via the
# importer's stale-deletion path), and its system account is deactivated
# (is_active=False) so it drops off the subscribe page. Use this to retire
# one-off / festival sources that go stale after their run.
#
# Note: this differs from SCRAPER_<NAME>_ENABLED=false, which only pauses
# scraping and leaves existing events and the account untouched (so it can be
# re-enabled).
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
                f"Choices: {', '.join(sorted(SOURCES))}."
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
            unknown = only - set(SOURCES)
            if unknown:
                self.stderr.write(
                    self.style.ERROR(
                        f"Unknown source(s): {', '.join(sorted(unknown))}. "
                        f"Valid: {', '.join(sorted(SOURCES))}"
                    )
                )
                sys.exit(1)

        results: list[tuple[str, bool, str]] = []

        for name, cfg in SOURCES.items():
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
                self._cleanup_source(name, dry_run)
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
                events = cfg.scrape(**cfg.scrape_kwargs)
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
                self.stdout.write(f"Importing {len(events)} events from {name} ...")
                import_kwargs: dict = {"json_file": tmp_path}
                if dry_run:
                    import_kwargs["dry_run"] = True
                if skip_images:
                    import_kwargs["skip_images"] = True

                call_command("import_events", name, **import_kwargs)

                elapsed = time.monotonic() - t0
                msg = f"{len(events)} events, {elapsed:.1f}s"
                results.append((name, True, msg))
                self.stdout.write(self.style.SUCCESS(f"{name} done ({msg})"))

            except Exception as exc:
                elapsed = time.monotonic() - t0
                tb = traceback.format_exc()
                self._report_to_sentry(exc, name)
                self.stderr.write(self.style.ERROR(f"{name} FAILED ({elapsed:.1f}s):"))
                self.stderr.write(tb)
                results.append((name, False, f"error after {elapsed:.1f}s"))

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # ── Geocoding backfill ────────────────────────────────────────────
        # Recovery path for events that saved without coordinates (a transient
        # Nominatim failure, or a definitive miss that's since become
        # resolvable — e.g. a venue address typo fixed upstream). Runs on
        # every cron pass so gaps don't linger; failures are reported to
        # Sentry but never fail the overall run.
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Backfilling geocoding..."))
        try:
            backfill_kwargs: dict = {}
            if dry_run:
                backfill_kwargs["dry_run"] = True
            call_command("backfill_geocoding", **backfill_kwargs)
        except Exception as exc:
            self._report_to_sentry(exc, "backfill_geocoding")
            self.stderr.write(
                self.style.ERROR(
                    f"backfill_geocoding FAILED:\n{traceback.format_exc()}"
                )
            )

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

    @staticmethod
    def _report_to_sentry(exc: Exception, scraper_name: str) -> None:
        """Send a scraper failure to Sentry, tagged with the source name.

        No-op when Sentry is not initialized (SENTRY_DSN unset).
        """
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("scraper", scraper_name)
            sentry_sdk.capture_exception(exc)

    def _cleanup_source(self, name: str, dry_run: bool) -> None:
        """Retire a source: purge its events and deactivate its publisher account.

        Purging invokes ``import_events`` with an empty event list, triggering
        the importer's stale-deletion path (every event for that
        ``external_source`` is absent from the empty input and thus deleted).
        Deactivating sets the source's system account ``is_active=False`` so it
        drops off the subscribe page's publisher list while its past events keep
        their attribution. Both steps are idempotent, and failures are logged
        but never abort the overall run.
        """
        self.stdout.write(f"Purging stale events for {name} ...")
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix=f"{name}_cleanup_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([], f)
            # An empty event list always trips the importer's stale-deletion
            # sanity guard, so retirement must explicitly force it.
            import_kwargs: dict = {"json_file": tmp_path, "force_delete": True}
            if dry_run:
                import_kwargs["dry_run"] = True
            call_command("import_events", name, **import_kwargs)
        except Exception as exc:
            self._report_to_sentry(exc, name)
            self.stderr.write(
                self.style.ERROR(
                    f"Cleanup for {name} failed:\n{traceback.format_exc()}"
                )
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        self._deactivate_source_account(name, dry_run)

    def _deactivate_source_account(self, name: str, dry_run: bool) -> None:
        """Mark a retired source's system account inactive (hides it on subscribe)."""
        from django.contrib.auth import get_user_model

        external_source = SOURCES[name].external_source

        user_model = get_user_model()
        accounts = user_model.objects.filter(
            is_system_account=True,
            display_name_slug=external_source,
            is_active=True,
        )
        if dry_run:
            for acct in accounts:
                self.stdout.write(
                    self.style.WARNING(
                        f"  DEACTIVATE  {acct.display_name} ({external_source})"
                    )
                )
            return
        if accounts.update(is_active=False):
            self.stdout.write(
                self.style.WARNING(f"Deactivated source account for {external_source}")
            )
