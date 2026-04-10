"""Management command to ingest sort-hvid.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/sort_hvid.py --output sort_hvid_events.json
    uv run python manage.py import_sort_hvid sort_hvid_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from sort-hvid but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest sort-hvid.dk events from a JSON file produced by scrapers/sort_hvid.py"
    )
    external_source = "sort-hvid"
    default_json_file = "sort_hvid_events.json"
    default_venue_name = "Sort/Hvid"
    allowed_image_domains = frozenset({"sort-hvid.dk"})
