from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from django.db.models import Sum

from events.models import Event, EventCategory, FeedHit

User = get_user_model()


class Command(BaseCommand):
    help = "Email admins a weekly digest of site growth and activity stats."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the digest to stdout instead of sending email.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        week_ago = now - timezone.timedelta(days=7)

        new_users = User.objects.filter(date_joined__gte=week_ago).count()
        new_events = Event.objects.filter(created_at__gte=week_ago).count()
        total_users = User.objects.count()
        total_events = Event.objects.count()
        upcoming = Event.objects.filter(
            start_datetime__gte=now,
            start_datetime__lt=now + timezone.timedelta(days=7),
        ).count()

        week_ago_date = timezone.localdate() - timezone.timedelta(days=7)
        rss_hits = (
            FeedHit.objects.filter(feed_type=FeedHit.RSS, date__gte=week_ago_date)
            .aggregate(total=Sum("count"))["total"]
            or 0
        )
        ical_hits = (
            FeedHit.objects.filter(feed_type=FeedHit.ICAL, date__gte=week_ago_date)
            .aggregate(total=Sum("count"))["total"]
            or 0
        )

        category_lines = []
        for value, label in EventCategory.choices:
            count = Event.objects.filter(
                created_at__gte=week_ago, category=value
            ).count()
            if count:
                category_lines.append(f"  {label}: {count}")

        lines = [
            f"Weekly digest for pleskal — {now.strftime('%A, %d %B %Y')}",
            "",
            "=== This week ===",
            f"New signups:   {new_users}",
            f"New events:    {new_events}",
        ]
        if category_lines:
            lines.append("By category:")
            lines.extend(category_lines)
        lines += [
            "",
            f"RSS feed hits: {rss_hits}",
            f"iCal hits:     {ical_hits}",
            "",
            "=== All time ===",
            f"Total users:   {total_users}",
            f"Total events:  {total_events}",
            f"Upcoming (7d): {upcoming}",
        ]
        message = "\n".join(lines)
        subject = f"pleskal weekly digest — {now.strftime('%Y-%m-%d')}"

        if options["dry_run"]:
            self.stdout.write(message)
            return

        admin_emails = list(settings.ADMINS)
        if not admin_emails:
            self.stderr.write(
                self.style.WARNING("No ADMINS configured — skipping email.")
            )
            return

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.SERVER_EMAIL,
            recipient_list=admin_emails,
            fail_silently=False,
        )
        self.stderr.write(
            self.style.SUCCESS(f"Digest sent to {len(admin_emails)} admin(s).")
        )
