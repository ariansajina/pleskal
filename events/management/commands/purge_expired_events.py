"""Delete scraped events that are past their retention period.

Scraped events are kept SCRAPED_EVENT_RETENTION_DAYS after they end (see
events.models.expired_events_q). User-published events are never deleted;
they are only hidden from the event list after USER_EVENT_HIDE_AFTER_DAYS.
Runs daily as a step of run_scrapers. Deleting through the ORM fires the
post_delete signal, so each event's image is removed from storage too unless
another event still uses it.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from events.models import Event, expired_events_q


class Command(BaseCommand):
    help = "Delete past scraped events older than their retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        expired = Event.objects.filter(expired_events_q())
        count = expired.count()
        summary = (
            f"{count} scraped event(s) older than "
            f"{settings.SCRAPED_EVENT_RETENTION_DAYS} days"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run — would delete {summary}."))
            return

        if count:
            expired.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {summary}."))
