from django.conf import settings
from django.db import migrations


def configure_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    domain = getattr(settings, "SITE_DOMAIN", "localhost")
    name = getattr(settings, "SITE_NAME", domain)
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": domain, "name": name},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(configure_site, migrations.RunPython.noop),
    ]
