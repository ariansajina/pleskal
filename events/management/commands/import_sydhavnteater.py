"""Management command to ingest sydhavnteater.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/sydhavnteater.py --output sydhavnteater_events.json
    uv run python manage.py import_sydhavnteater sydhavnteater_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from sydhavnteater but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest sydhavnteater.dk events from a JSON file produced by "
        "scrapers/sydhavnteater.py"
    )
    external_source = "sydhavnteater"
    default_json_file = "sydhavnteater_events.json"
    default_venue_name = "Sydhavn Teater"
