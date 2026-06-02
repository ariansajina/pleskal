"""Management command to ingest warehouse9.dk events from a scraped JSON file.

Typical workflow:
    uv run python scrapers/warehouse9.py --output warehouse9_events.json
    uv run python manage.py import_warehouse9 warehouse9_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from warehouse9 but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.
"""

from events.management.commands.base_import import BaseEventImportCommand


class Command(BaseEventImportCommand):
    help = (
        "Ingest warehouse9.dk events from a JSON file produced by "
        "scrapers/warehouse9.py"
    )
    external_source = "warehouse9"
    default_json_file = "warehouse9_events.json"
    default_venue_name = "Warehouse9"
    # Poster images are served from the WordPress media library on warehouse9.dk.
    allowed_image_domains = frozenset({"warehouse9.dk"})
