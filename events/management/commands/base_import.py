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
import hashlib
import io
import json
import os
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import (
    MAX_PRICE_NOTE_LENGTH,
    MAX_SOURCE_URL_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_VENUE_LENGTH,
    Event,
    EventCategory,
)


def _validate_field_lengths(rec: dict, title_for_log: str) -> tuple[bool, str | None]:
    """
    Validate that string fields don't exceed their max_length constraints.
    Returns (is_valid, error_message).
    """
    field_limits = {
        "title": MAX_TITLE_LENGTH,
        "venue_name": MAX_VENUE_LENGTH,
        "venue_address": MAX_VENUE_LENGTH,
        "price_note": MAX_PRICE_NOTE_LENGTH,
        "source_url": MAX_SOURCE_URL_LENGTH,
    }

    for field, max_length in field_limits.items():
        value = rec.get(field, "")
        if isinstance(value, str) and len(value) > max_length:
            return (
                False,
                f"Field '{field}' exceeds max length of {max_length} "
                f"({len(value)} chars): {value[:100]}...",
            )

    return True, None


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

    Subclasses should also define:
        allowed_image_domains – frozenset of hostnames (e.g. "example.dk") from
            which this importer is permitted to download images. Subdomains are
            accepted automatically (e.g. "example.dk" also allows
            "images.example.dk"). An empty frozenset blocks all image downloads.
    """

    external_source: str
    default_json_file: str
    default_venue_name: str
    # Optional: restrict upsert/delete to events whose category is in this set.
    # Use this when multiple importers share the same external_source but cover
    # different categories (e.g. dansehallerne vs dansehallerne_workshops).
    category_scope: list[str] | None = None
    # Allowlist of domains from which images may be downloaded (SSRF mitigation).
    # Subclasses must declare this explicitly; no downloads are performed when empty.
    allowed_image_domains: frozenset[str] = frozenset()

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

        # Build a lookup: (source_url, start_datetime_utc) → record
        # Normalize start_datetime to UTC so keys match regardless of the
        # timezone offset in the scraped JSON vs. what Django stores in the DB.
        incoming: dict[tuple[str, datetime.datetime], dict] = {}
        for rec in records:
            try:
                start_dt_utc = _parse_dt(rec["start_datetime"]).astimezone(datetime.UTC)
            except ValueError:
                continue  # malformed records are handled during upsert
            key = (rec["source_url"], start_dt_utc)
            incoming[key] = rec

        # Existing events for this source in DB, keyed the same way.
        existing_qs = Event.objects.filter(external_source=self.external_source)
        if self.category_scope is not None:
            category_values = [
                CATEGORY_MAP[c] for c in self.category_scope if c in CATEGORY_MAP
            ]
            existing_qs = existing_qs.filter(category__in=category_values)
        existing: dict[tuple[str, datetime.datetime], Event] = {
            (e.source_url, e.start_datetime.astimezone(datetime.UTC)): e
            for e in existing_qs
        }

        created = updated = deleted = skipped = 0

        with transaction.atomic():
            # ── Upsert ────────────────────────────────────────────────────────
            for key, rec in incoming.items():
                source_url, start_dt_utc = key
                event_title = rec.get("title", "?")

                # Validate field lengths first
                is_valid, validation_error = _validate_field_lengths(rec, event_title)
                if not is_valid:
                    self.stderr.write(
                        f"  SKIP (field length) {event_title}: {validation_error}"
                    )
                    skipped += 1
                    continue

                try:
                    start_dt = _parse_dt(rec["start_datetime"])
                    end_dt = (
                        _parse_dt(rec["end_datetime"])
                        if rec.get("end_datetime")
                        else None
                    )
                except ValueError as exc:
                    self.stderr.write(f"  SKIP (bad datetime) {event_title}: {exc}")
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
                            try:
                                with transaction.atomic():
                                    for k, v in fields.items():
                                        setattr(event, k, v)
                                    event.save()
                                    self._maybe_update_image(event, rec, skip_images)
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"  UPDATED  {rec['title'][:60]}"
                                    )
                                )
                            except Exception as exc:
                                self.stderr.write(
                                    f"  FAILED (update) {event_title}: {exc}"
                                )
                                skipped += 1
                                continue
                        updated += 1
                    else:
                        skipped += 1
                else:
                    if dry_run:
                        self.stdout.write(f"  CREATE  {rec['title'][:60]}")
                    else:
                        try:
                            with transaction.atomic():
                                event = Event(**fields)
                                event.save()
                                self._maybe_update_image(event, rec, skip_images)
                            self.stdout.write(
                                self.style.SUCCESS(f"  CREATED  {rec['title'][:60]}")
                            )
                        except Exception as exc:
                            self.stderr.write(f"  FAILED (create) {event_title}: {exc}")
                            skipped += 1
                            continue
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
        """Download and attach the event image if it isn't already set.

        Images are stored with content-addressed filenames (events/img_<sha256>.webp)
        so that multiple events importing the same source image share one file in
        storage rather than storing independent copies.
        """
        if skip_images:
            return
        image_url = rec.get("image_url", "")
        if not image_url:
            return
        # Don't re-download if the event already has an image
        if event.image.name:
            return

        # SSRF mitigation: only download from explicitly allowed domains.
        if self.allowed_image_domains:
            from urllib.parse import urlparse

            host = urlparse(image_url).hostname or ""
            if not any(
                host == d or host.endswith("." + d) for d in self.allowed_image_domains
            ):
                self.stderr.write(
                    f"    Blocked image from non-allowlisted domain '{host}': {image_url}"
                )
                return
        else:
            self.stderr.write(
                f"    No allowed_image_domains set for {self.external_source}; skipping image"
            )
            return

        result = _download_image(image_url)
        if result is None:
            self.stderr.write(f"    Could not download image: {image_url}")
            return

        _filename, data = result
        try:
            from django.core.files.base import ContentFile
            from django.core.files.storage import default_storage

            from events.images import validate_and_process

            processed = validate_and_process(io.BytesIO(data))
            content_bytes = processed.read()
            hash_hex = hashlib.sha256(content_bytes).hexdigest()
            storage_name = f"events/img_{hash_hex}.webp"

            if default_storage.exists(storage_name):
                event.image.name = storage_name
                event.save(update_fields=["image"])
            else:
                saved_name = default_storage.save(
                    storage_name, ContentFile(content_bytes, name=storage_name)
                )
                event.image.name = saved_name
                event.save(update_fields=["image"])
        except Exception as exc:
            self.stderr.write(
                f"    Image save failed for {str(event.title)[:40]}: {exc}"
            )
