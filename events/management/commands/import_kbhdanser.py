"""Management command to ingest kbhdanser.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/kbhdanser.py --output kbhdanser_events.json
    uv run python manage.py import_kbhdanser kbhdanser_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from kbhdanser but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest kbhdanser.dk events from a JSON file produced by scrapers/kbhdanser.py"
    )
    external_source = "kbhdanser"
    default_json_file = "kbhdanser_events.json"
    default_venue_name = "Østre Gasværk Teater"
