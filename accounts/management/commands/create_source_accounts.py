"""Create (or update) system user accounts for scraped event sources.

Source metadata is read from scrapers/sources.json.  Each entry gets a User
with an unusable password and is_system_account=True.  The display_name_slug
is set to match the external_source identifier used by the import commands,
so that base_import.py can look up the user by slug.

Run once after initial deploy and again if source metadata changes:

    uv run python manage.py create_source_accounts
"""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

SOURCES_FILE = Path(__file__).resolve().parents[3] / "scrapers" / "sources.json"


class Command(BaseCommand):
    help = "Create or update system user accounts for scraped event sources."

    def handle(self, *args, **options):
        if not SOURCES_FILE.exists():
            raise CommandError(f"Sources file not found: {SOURCES_FILE}")

        try:
            sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {SOURCES_FILE}: {exc}") from exc

        User = get_user_model()

        for source in sources:
            slug = source["external_source"]
            user, created = User.objects.get_or_create(
                email=source["email"],
                defaults={
                    "display_name": source["display_name"],
                    "display_name_slug": slug,
                    "bio": "",
                    "website": source.get("website", ""),
                    "is_system_account": True,
                    "is_active": True,
                },
            )

            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
                self.stdout.write(
                    self.style.SUCCESS(f"  CREATED  {source['display_name']} ({slug})")
                )
            else:
                user.display_name = source["display_name"]
                user.website = source.get("website", "")
                user.is_system_account = True
                if user.display_name_slug != slug:
                    user.display_name_slug = slug
                user.save(
                    update_fields=[
                        "display_name",
                        "display_name_slug",
                        "website",
                        "is_system_account",
                    ]
                )
                self.stdout.write(f"  UPDATED  {source['display_name']} ({slug})")

        self.stdout.write(self.style.SUCCESS("Done."))
