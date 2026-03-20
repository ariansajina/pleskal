"""Management command to ingest dansehallerne.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/dansehallerne.py --output dansehallerne_events.json
    uv run python manage.py import_dansehallerne dansehallerne_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from dansehallerne but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest dansehallerne.dk events from a JSON file produced by "
        "scrapers/dansehallerne.py"
    )
    external_source = "dansehallerne"
    default_json_file = "dansehallerne_events.json"
    default_venue_name = "Dansehallerne"
