"""Management command to ingest dansehallerne.dk workshops from a scraped JSON file.

Typical workflow:
    uv run python scrapers/dansehallerne_workshops.py --output dansehallerne_workshops_events.json
    uv run python manage.py import_dansehallerne_workshops dansehallerne_workshops_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from dansehallerne but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.

Note: Both import_dansehallerne and import_dansehallerne_workshops share
external_source="dansehallerne". Stale deletion is scoped to category=workshop
so the two commands are mutually exclusive and --no-delete is not required.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest dansehallerne.dk workshops from a JSON file produced by "
        "scrapers/dansehallerne_workshops.py"
    )
    external_source = "dansehallerne"
    default_json_file = "dansehallerne_workshops_events.json"
    default_venue_name = "Dansehallerne"
    category_scope = ["workshop"]
