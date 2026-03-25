"""Shared base class for event import management commands.

All scrapers produce a JSON file with the same schema.  This base class
handles loading that file, upserting events into the database, and stale
deletion.  Subclasses only need to declare three class attributes:

    class Command(BaseEventImportCommand):
        help = "Ingest example.dk events ..."
        external_source = "example"
        default_json_file = "example_events.json"
        default_venue_name = "Example Venue"
"""

import datetime
import json
import os
import tempfile
import urllib.request
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import Event, EventCategory

# Map scraper category strings → EventCategory values (shared across all scrapers)
CATEGORY_MAP = {
    "performance": EventCategory.PERFORMANCE,
    "talk": EventCategory.TALK,
    "workshop": EventCategory.WORKSHOP,
    "worksharing": EventCategory.WORKSHARING,
    "openpractice": EventCategory.OPENPRACTICE,
    "social": EventCategory.SOCIAL,
    "other": EventCategory.OTHER,
}


def _parse_dt(iso_str: str) -> datetime.datetime:
    """Parse an ISO 8601 string (with timezone) into an aware datetime."""
    return datetime.datetime.fromisoformat(iso_str)


def _download_image(url: str) -> tuple[str, bytes] | None:
    """
    Download an image from *url* and return (filename, bytes).
    Returns None on any error.
    """
    if not url or not url.startswith("https://"):
        return None
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; pleskalScraper/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            data = resp.read()
        filename = os.path.basename(url.split("?")[0]) or "image.jpg"
        return filename, data
    except Exception:
        return None


class BaseEventImportCommand(BaseCommand):
    """
    Base class for import_<source> management commands.

    Subclasses must define:
        external_source   – the value stored in Event.external_source
        default_json_file – default argument for the positional json_file arg
        default_venue_name – fallback venue name when the record omits it
    """

    external_source: str
    default_json_file: str
    default_venue_name: str

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            nargs="?",
            default=self.default_json_file,
            help=(
                f"Path to the JSON file produced by the scraper "
                f"(default: {self.default_json_file})"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without writing to the database.",
        )
        parser.add_argument(
            "--no-delete",
            action="store_true",
            help="Do not delete stale events that are absent from the JSON.",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            help="Do not download or update event images.",
        )

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        system_user = user_model.objects.filter(
            is_system_account=True, display_name_slug=self.external_source
        ).first()

        json_path = Path(options["json_file"])
        if not json_path.exists():
            raise CommandError(f"File not found: {json_path}")

        dry_run = options["dry_run"]
        no_delete = options["no_delete"]
        skip_images = options["skip_images"]

        try:
            records = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {json_path}: {exc}") from exc

        if not isinstance(records, list):
            raise CommandError(
                "JSON file must contain a top-level list of event objects."
            )

        self.stdout.write(f"Loaded {len(records)} records from {json_path}")

        # Build a lookup: (source_url, start_datetime_isoformat) → record
        incoming: dict[tuple[str, str], dict] = {}
        for rec in records:
            key = (rec["source_url"], rec["start_datetime"])
            incoming[key] = rec

        # Existing events for this source in DB, keyed the same way
        existing_qs = Event.objects.filter(external_source=self.external_source)
        existing: dict[tuple[str, str], Event] = {
            (e.source_url, e.start_datetime.isoformat()): e for e in existing_qs
        }

        created = updated = deleted = skipped = 0

        with transaction.atomic():
            # ── Upsert ────────────────────────────────────────────────────────
            for key, rec in incoming.items():
                source_url, start_iso = key
                try:
                    start_dt = _parse_dt(start_iso)
                    end_dt = (
                        _parse_dt(rec["end_datetime"])
                        if rec.get("end_datetime")
                        else None
                    )
                except ValueError as exc:
                    self.stderr.write(
                        f"  SKIP (bad datetime) {rec.get('title', '?')}: {exc}"
                    )
                    skipped += 1
                    continue

                category = CATEGORY_MAP.get(
                    rec.get("category", ""), EventCategory.OTHER
                )

                fields = {
                    "title": rec["title"],
                    "description": rec.get("description", ""),
                    "start_datetime": start_dt,
                    "end_datetime": end_dt,
                    "venue_name": rec.get("venue_name", self.default_venue_name),
                    "venue_address": rec.get("venue_address", ""),
                    "category": category,
                    "is_free": rec.get("is_free", False),
                    "is_wheelchair_accessible": rec.get(
                        "is_wheelchair_accessible", False
                    ),
                    "price_note": rec.get("price_note", ""),
                    "source_url": source_url,
                    "external_source": self.external_source,
                    "submitted_by": system_user,
                }

                if key in existing:
                    event = existing[key]
                    changed = any(getattr(event, k) != v for k, v in fields.items())

                    if changed:
                        if dry_run:
                            self.stdout.write(f"  UPDATE  {rec['title'][:60]}")
                        else:
                            for k, v in fields.items():
                                setattr(event, k, v)
                            event.save()
                            self._maybe_update_image(event, rec, skip_images)
                            self.stdout.write(
                                self.style.SUCCESS(f"  UPDATED  {rec['title'][:60]}")
                            )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    if dry_run:
                        self.stdout.write(f"  CREATE  {rec['title'][:60]}")
                    else:
                        event = Event(**fields)
                        event.save()
                        self._maybe_update_image(event, rec, skip_images)
                        self.stdout.write(
                            self.style.SUCCESS(f"  CREATED  {rec['title'][:60]}")
                        )
                    created += 1

            # ── Stale deletion ────────────────────────────────────────────────
            if not no_delete:
                stale_keys = set(existing.keys()) - set(incoming.keys())
                for key in stale_keys:
                    event = existing[key]
                    title_str = str(event.title)
                    if dry_run:
                        self.stdout.write(
                            self.style.WARNING(f"  DELETE  {title_str[:60]}")
                        )
                    else:
                        event.delete()
                        self.stdout.write(
                            self.style.WARNING(f"  DELETED  {title_str[:60]}")
                        )
                    deleted += 1

            if dry_run:
                # Rollback everything — we're just previewing
                transaction.set_rollback(True)

        self.stdout.write("")
        summary = f"created={created}  updated={updated}  deleted={deleted}  skipped={skipped}"
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry run — no changes saved.  {summary}")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Done.  {summary}"))

    def _maybe_update_image(self, event: Event, rec: dict, skip_images: bool) -> None:
        """Download and attach the event image if it isn't already set."""
        if skip_images:
            return
        image_url = rec.get("image_url", "")
        if not image_url:
            return
        # Don't re-download if the event already has an image
        if event.image.name:
            return

        result = _download_image(image_url)
        if result is None:
            self.stderr.write(f"    Could not download image: {image_url}")
            return

        filename, data = result
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(filename).suffix
        ) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                event.image.save(filename, File(f), save=True)  # type: ignore[union-attr]
        except Exception as exc:
            self.stderr.write(
                f"    Image save failed for {str(event.title)[:40]}: {exc}"
            )
        finally:
            os.unlink(tmp_path)
