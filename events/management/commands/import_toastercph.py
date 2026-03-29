"""Management command to ingest toastercph.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/toastercph.py --output toastercph_events.json
    uv run python manage.py import_toastercph toastercph_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from toastercph but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest toastercph.dk events from a JSON file produced by "
        "scrapers/toastercph.py"
    )
    external_source = "toastercph"
    default_json_file = "toastercph_events.json"
    default_venue_name = "Toaster CPH"
