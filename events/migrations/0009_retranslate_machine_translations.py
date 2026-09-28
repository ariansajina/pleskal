"""Queue machine-translated descriptions for re-translation.

Translations made before punctuation was normalized and escaped for the model
contain ``â ¢`` mojibake wherever the Danish original had quotes or dashes
(issue #165). Marking them unprocessed makes the next backfill_translations run
(a step of run_scrapers) translate them again; until then the Danish original
is shown, as for any event not yet translated.
"""

from django.db import migrations


def queue_retranslation(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(description_en_is_machine=True).update(
        description_language="",
        description_en="",
        description_en_is_machine=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0008_event_thumbnail"),
    ]

    operations = [
        migrations.RunPython(queue_retranslation, migrations.RunPython.noop),
    ]
