"""Detect the language of, and translate, scraped descriptions not yet processed.

Covers events imported before translation existed, imported with translation
disabled or skipped, or whose translation failed (process_description leaves
those unprocessed so they are retried here). Runs as a step of run_scrapers.
"""

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand

from events.models import Event
from events.translation import process_description


class Command(BaseCommand):
    help = "Detect the language of scraped descriptions and translate Danish ones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of events to process.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print detected languages without saving to the database.",
        )

    def handle(self, *args, **options):
        if not settings.TRANSLATION_ENABLED:
            self.stdout.write("Translation is disabled (TRANSLATION_ENABLED=false).")
            return
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)

        qs = (
            Event.objects.exclude(external_source="")
            .exclude(description="")
            .filter(description_language="")
            .order_by("created_at")
        )
        if limit:
            qs = qs[:limit]

        languages: Counter[str] = Counter()
        for event in qs:
            result = process_description(str(event.description))
            languages[result.language or "undetermined"] += 1
            self.stdout.write(f"[{result.language or '?':5}] {str(event.title)[:60]}")
            if not dry_run and result.language:
                Event.objects.filter(pk=event.pk).update(**result.as_fields())

        summary = ", ".join(f"{lang}={n}" for lang, n in sorted(languages.items()))
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {languages.total()} event(s)"
                + (f": {summary}" if summary else "")
                + (" (dry run, nothing saved)." if dry_run else ".")
            )
        )
