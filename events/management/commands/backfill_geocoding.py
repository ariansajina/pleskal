"""Backfill latitude/longitude for existing events that predate geocoding.

One-shot command. Respects Nominatim's rate limit via events.geocoding.
"""

from django.core.management.base import BaseCommand

from events.geocoding import geocode
from events.models import Event


class Command(BaseCommand):
    help = "Geocode venues of existing events that have no coordinates yet."

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
            help="Print resolved coordinates without saving to the database.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)

        qs = Event.objects.filter(latitude__isnull=True).exclude(venue_name="")
        qs = qs.order_by("created_at")
        if limit:
            qs = qs[:limit]

        total = 0
        resolved = 0
        for event in qs:
            total += 1
            query = event._build_geocode_query()
            result = geocode(query)
            if result is None:
                self.stdout.write(f"[miss] {event.venue_name!r} ({event.pk})")
                continue

            lat, lon = result
            resolved += 1
            self.stdout.write(
                f"[ok]   {event.venue_name!r} ({event.pk}) -> {lat:.5f}, {lon:.5f}"
            )
            if not dry_run:
                Event.objects.filter(pk=event.pk).update(latitude=lat, longitude=lon)

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {total} event(s); resolved {resolved}; "
                f"missed {total - resolved}."
            )
        )
