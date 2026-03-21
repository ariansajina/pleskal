from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import ClaimCode, generate_claim_code


class Command(BaseCommand):
    help = "Generate a batch of claim codes for invite-only registration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=1,
            help="Number of codes to generate (1–100).",
        )
        parser.add_argument(
            "--expires",
            type=str,
            required=True,
            help="Expiration date in YYYY-MM-DD format.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if not 1 <= count <= 100:
            raise CommandError("Count must be between 1 and 100.")

        try:
            expires_date = datetime.strptime(options["expires"], "%Y-%m-%d")
        except ValueError:
            raise CommandError("Expires must be in YYYY-MM-DD format.") from None

        expires_at = timezone.make_aware(
            expires_date.replace(hour=23, minute=59, second=59)
        )

        if expires_at <= timezone.now():
            raise CommandError("Expiration date must be in the future.")

        codes = []
        max_retries = count * 10
        attempts = 0
        while len(codes) < count and attempts < max_retries:
            attempts += 1
            code = generate_claim_code()
            try:
                ClaimCode.objects.create(code=code, expires_at=expires_at)
                codes.append(code)
            except IntegrityError:
                continue

        if len(codes) < count:
            raise CommandError(
                f"Could only generate {len(codes)} of {count} unique codes."
            )

        for code in codes:
            self.stdout.write(code)

        self.stderr.write(
            self.style.SUCCESS(
                f"Generated {len(codes)} claim codes expiring {expires_at.date()}."
            )
        )
