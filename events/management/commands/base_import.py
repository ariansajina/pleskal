"""Shared base class for event import management commands.

All scrapers produce a JSON file with the same schema.  This base class
handles loading that file, upserting events into the database, and stale
deletion.  The generic ``import_events`` command resolves the per-source
attributes (external_source, default_json_file, default_venue_name,
category_scope, allowed_image_domains) from ``scrapers.registry`` before
delegating to ``handle()``.
"""

import datetime
import hashlib
import io
import json
import math
import os
import urllib.request
from pathlib import Path

import sentry_sdk
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from events.geocoding import geocode
from events.models import (
    MAX_PRICE_NOTE_LENGTH,
    MAX_SOURCE_URL_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_VENUE_LENGTH,
    Event,
    EventCategory,
)

# If a scraper returns fewer than this fraction of a source's existing future
# events, stale deletion is skipped — a near-empty result is more likely a
# broken scraper than a real drop in events. Legitimate source retirement goes
# through --force-delete instead (see run_scrapers._cleanup_source).
STALE_DELETION_MIN_RATIO = 0.5
# Below this many existing future events, the ratio check is too noisy to be
# useful (a source with 2 events going to 0 is a normal, small event calendar
# emptying out, not evidence of scraper breakage) — skip the guard entirely.
STALE_DELETION_GUARD_MIN_EXISTING = 4


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


MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB; mirrors the image upload cap


def _host_allowed(host: str, allowed_domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect whose target host isn't in the allowlist.

    ``urllib.request.urlopen`` follows redirects transparently, which would
    otherwise let a compromised/misconfigured venue site redirect the scraper
    off the allowlisted domain (e.g. to an internal endpoint).
    """

    def __init__(self, allowed_domains: frozenset[str]):
        self.allowed_domains = allowed_domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse

        host = urlparse(newurl).hostname or ""
        if not _host_allowed(host, self.allowed_domains):
            raise OSError(f"Redirect to non-allowlisted host '{host}' blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_image(
    url: str, allowed_domains: frozenset[str] = frozenset()
) -> tuple[str, bytes] | None:
    """
    Download an image from *url* and return (filename, bytes).
    Returns None on any error. Redirects to hosts outside *allowed_domains*
    are refused (SSRF mitigation); an empty frozenset (the default) matches no
    host, so it blocks every redirect rather than skipping the check — pass
    the caller's real allowlist to permit redirects within it.
    """
    if not url or not url.startswith("https://"):
        return None
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; pleskalScraper/1.0)"},
        )
        opener = urllib.request.build_opener(
            _AllowlistedRedirectHandler(allowed_domains)
        )
        with opener.open(req, timeout=20) as resp:
            data = resp.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            return None
        filename = os.path.basename(url.split("?")[0]) or "image.jpg"
        return filename, data
    except Exception:
        return None


class BaseEventImportCommand(BaseCommand):
    """
    Base class for event import management commands.

    The following attributes must be set (by a subclass, or per-instance as
    ``import_events`` does from the scraper registry) before handle() runs:
        external_source   – the value stored in Event.external_source
        default_json_file – fallback for the positional json_file arg
        default_venue_name – fallback venue name when the record omits it
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
            default=None,
            help=(
                "Path to the JSON file produced by the scraper "
                "(default: the source's <name>_events.json)"
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
            "--force-delete",
            action="store_true",
            help=(
                "Bypass the sanity-threshold guard and delete all stale events "
                "even if the incoming set looks implausibly small (e.g. source "
                "retirement, which imports an empty event list on purpose)."
            ),
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

        json_path = Path(options["json_file"] or self.default_json_file)
        if not json_path.exists():
            raise CommandError(f"File not found: {json_path}")

        dry_run = options["dry_run"]
        no_delete = options["no_delete"]
        force_delete = options["force_delete"]
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

        # ── Resolve images up front, outside any DB transaction ─────────────
        # Downloading + uploading images is network I/O (up to 20s per image);
        # doing it before the transaction opens (rather than inside the
        # per-event atomic block) means a slow image never holds a Postgres
        # transaction open.
        image_names: dict[tuple[str, datetime.datetime], str | None] = {}
        if not dry_run:
            for key, rec in incoming.items():
                existing_event = existing.get(key)
                has_existing_image = bool(existing_event and existing_event.image.name)
                image_names[key] = self._resolve_image_storage_name(
                    rec, has_existing_image, skip_images
                )

        # ── Pre-resolve venue coordinates up front, outside any DB transaction ──
        # Event.save() geocodes synchronously via Nominatim (1.1s+ per call,
        # serialized by a global rate limit); doing that inline inside the
        # transaction below would hold a Postgres transaction open for the
        # whole import. Warming the shared geocode cache here — deduped by
        # query, since most records share a venue — means the per-event
        # save() inside the transaction hits the cache instead of the
        # network, mirroring the image pre-resolution above.
        if not dry_run and getattr(settings, "GEOCODING_ENABLED", True):
            geocode_queries: set[str] = set()
            for key, rec in incoming.items():
                existing_event = existing.get(key)
                venue_name = rec.get("venue_name", self.default_venue_name)
                venue_address = rec.get("venue_address", "")
                needs_geocode = existing_event is None or (
                    existing_event.venue_name != venue_name
                    or existing_event.venue_address != venue_address
                )
                if needs_geocode and venue_name:
                    probe = Event(venue_name=venue_name, venue_address=venue_address)
                    geocode_queries.add(probe._build_geocode_query())
            for query in geocode_queries:
                geocode(query)

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
                    # An unchanged event that's still missing an image (backfill
                    # case) needs to attach image_name too — otherwise the image
                    # resolved in the pre-pass above is downloaded/uploaded to
                    # storage every single import run and never attached to
                    # anything, wasting bandwidth and leaving an orphaned R2
                    # object each time.
                    image_name = image_names.get(key)

                    if changed or image_name:
                        if dry_run:
                            self.stdout.write(f"  UPDATE  {rec['title'][:60]}")
                        else:
                            try:
                                with transaction.atomic():
                                    for k, v in fields.items():
                                        setattr(event, k, v)
                                    if image_name:
                                        event.image.name = image_name
                                    event.save()
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
                                image_name = image_names.get(key)
                                if image_name:
                                    event.image.name = image_name
                                event.save()
                            self.stdout.write(
                                self.style.SUCCESS(f"  CREATED  {rec['title'][:60]}")
                            )
                        except Exception as exc:
                            self.stderr.write(f"  FAILED (create) {event_title}: {exc}")
                            skipped += 1
                            continue
                    created += 1

            # ── Stale deletion ────────────────────────────────────────────────
            if not no_delete and self._stale_deletion_is_safe(
                existing, incoming, force_delete
            ):
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

    def _stale_deletion_is_safe(
        self,
        existing: dict[tuple[str, datetime.datetime], Event],
        incoming: dict[tuple[str, datetime.datetime], dict],
        force_delete: bool,
    ) -> bool:
        """Guard against wiping a source's events on partial scraper failure.

        Compares *future* event counts only — past events naturally age out of
        the incoming set and shouldn't count against the scraper. Returns
        False (skip deletion, report to Sentry) when the incoming future
        count looks implausibly low vs. what's already in the DB.
        """
        if force_delete:
            return True

        now = timezone.now()
        existing_future_count = sum(
            1
            for key in existing
            if key[1] >= now  # key[1] is start_dt_utc
        )
        if existing_future_count < STALE_DELETION_GUARD_MIN_EXISTING:
            return True

        incoming_future_count = sum(1 for key in incoming if key[1] >= now)
        min_required = math.ceil(STALE_DELETION_MIN_RATIO * existing_future_count)

        if incoming_future_count < min_required:
            message = (
                f"Stale-deletion guard tripped for '{self.external_source}': "
                f"only {incoming_future_count} future events scraped vs. "
                f"{existing_future_count} existing in DB (need >= {min_required}). "
                "Skipping deletion; use --force-delete to override."
            )
            self.stderr.write(self.style.ERROR(f"  {message}"))
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("scraper", self.external_source)
                sentry_sdk.capture_message(message, level="warning")
            return False

        return True

    def _resolve_image_storage_name(
        self, rec: dict, has_existing_image: bool, skip_images: bool
    ) -> str | None:
        """Download, validate, and upload the record's image; return its storage name.

        Pure I/O — no DB writes here, deliberately: this is called *before* the
        per-event DB transaction opens so a slow/stalled image download (up to
        20s) or storage upload doesn't hold a Postgres transaction open. Images
        are stored with content-addressed filenames (events/img_<sha256>.webp)
        so that multiple events importing the same source image share one file
        in storage rather than storing independent copies. Returns None if no
        new image is available/needed; failures are logged, never raised.
        """
        if skip_images or has_existing_image:
            return None
        image_url = rec.get("image_url", "")
        if not image_url:
            return None

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
                return None
        else:
            self.stderr.write(
                f"    No allowed_image_domains set for {self.external_source}; skipping image"
            )
            return None

        result = _download_image(image_url, self.allowed_image_domains)
        if result is None:
            self.stderr.write(f"    Could not download image: {image_url}")
            return None

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
                return storage_name
            return default_storage.save(
                storage_name, ContentFile(content_bytes, name=storage_name)
            )
        except Exception as exc:
            self.stderr.write(f"    Image processing failed for {image_url}: {exc}")
            return None
