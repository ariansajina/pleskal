"""Generate list-card thumbnails for events whose image has none yet.

Event.save() keeps thumbnails in sync for new and changed images; this picks
up events that predate thumbnails, or whose thumbnail failed to generate. Runs
as a step of run_scrapers, so gaps are retried daily.

Rows are updated with QuerySet.update(), so updated_at (the feeds'
LAST-MODIFIED and the sitemap's lastmod) is left alone: the event itself
didn't change.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from events.models import Event, thumbnail_for_image


class Command(BaseCommand):
    help = "Generate thumbnails for event images that don't have one yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of distinct images to process.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be generated without writing anything.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)

        missing = (
            Event.objects.exclude(Q(image="") | Q(image__isnull=True))
            .filter(Q(thumbnail="") | Q(thumbnail__isnull=True))
            .order_by("created_at")
        )
        # Scraped events of one production share an image file; generate each
        # thumbnail once and attach it to every event using that image.
        image_names = list(dict.fromkeys(missing.values_list("image", flat=True)))
        if limit:
            image_names = image_names[:limit]

        generated = 0
        failed = 0
        for image_name in image_names:
            events = missing.filter(image=image_name)
            if dry_run:
                self.stdout.write(f"[would generate] {image_name}")
                continue
            event = events.first()
            if event is None:  # pragma: no cover - raced with a delete
                continue
            thumbnail_name = thumbnail_for_image(event.image)
            if thumbnail_name is None:
                failed += 1
                self.stderr.write(f"[failed] {image_name}")
                continue
            count = events.update(thumbnail=thumbnail_name)
            generated += 1
            self.stdout.write(f"[ok] {image_name} -> {thumbnail_name} ({count} events)")

        verb = "Would generate" if dry_run else "Generated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {len(image_names) if dry_run else generated} thumbnail(s); "
                f"{failed} failed."
            )
        )
