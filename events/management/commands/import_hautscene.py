"""Management command to ingest hautscene.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/hautscene.py --output hautscene_events.json
    uv run python manage.py import_hautscene hautscene_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from hautscene but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest hautscene.dk events from a JSON file produced by scrapers/hautscene.py"
    )
    external_source = "hautscene"
    default_json_file = "hautscene_events.json"
    default_venue_name = "Haut Scene"
