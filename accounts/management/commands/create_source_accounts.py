"""Create (or update) system user accounts for scraped event sources.

Each scraped source (dansehallerne, hautscene, sydhavnteater) gets a User
with an unusable password and is_system_account=True.  The display_name_slug
is set to match the external_source identifier used by the import commands,
so that base_import.py can look up the user by slug.

Run once after initial deploy and again if source metadata changes:

    uv run python manage.py create_source_accounts
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

SOURCES = [
    {
        "external_source": "dansehallerne",
        "display_name": "Dansehallerne",
        "email": "system.dansehallerne@pleskal.internal",
        "bio": (
            "Dansehallerne is Copenhagen's primary venue for contemporary dance, "
            "presenting Danish and international artists across performances, "
            "workshops, and open practices."
        ),
        "website": "https://dansehallerne.dk",
    },
    {
        "external_source": "hautscene",
        "display_name": "Haut Scène",
        "email": "system.hautscene@pleskal.internal",
        "bio": (
            "Haut Scène is a Copenhagen venue hosting contemporary dance, "
            "performance, and movement-based events."
        ),
        "website": "https://www.hautscene.dk",
    },
    {
        "external_source": "sydhavnteater",
        "display_name": "Sydhavn Teater",
        "email": "system.sydhavnteater@pleskal.internal",
        "bio": (
            "Sydhavn Teater is a Copenhagen theatre producing and presenting "
            "contemporary performance and dance work."
        ),
        "website": "https://sydhavnteater.dk",
    },
]


class Command(BaseCommand):
    help = "Create or update system user accounts for scraped event sources."

    def handle(self, *args, **options):
        User = get_user_model()

        for source in SOURCES:
            slug = source["external_source"]
            user, created = User.objects.get_or_create(
                email=source["email"],
                defaults={
                    "display_name": source["display_name"],
                    "display_name_slug": slug,
                    "bio": source["bio"],
                    "website": source["website"],
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
                # Keep metadata in sync if it changes in this file.
                user.display_name = source["display_name"]
                user.bio = source["bio"]
                user.website = source["website"]
                user.is_system_account = True
                # Only set slug if it doesn't already match, to avoid slug
                # uniqueness issues if the slug is already taken by something else.
                if user.display_name_slug != slug:
                    user.display_name_slug = slug
                user.save(
                    update_fields=[
                        "display_name",
                        "display_name_slug",
                        "bio",
                        "website",
                        "is_system_account",
                    ]
                )
                self.stdout.write(f"  UPDATED  {source['display_name']} ({slug})")

        self.stdout.write(self.style.SUCCESS("Done."))
