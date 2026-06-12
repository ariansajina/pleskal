"""Generic management command to ingest scraped events for any registered source.

Typical workflow:
    uv run python scrapers/hautscene.py --output hautscene_events.json
    uv run python manage.py import_events hautscene hautscene_events.json

Each run upserts events keyed on (source_url, start_datetime):
  - New events are created.
  - Existing events (same key) are updated in place.
  - Events previously imported from the source but absent from the current
    JSON are deleted (stale removal), unless --no-delete is passed.

Per-source configuration (external_source, venue fallback, image-domain
allowlist, category scope) lives in ``scrapers/registry.py``.
"""

from events.management.commands.base_import import BaseEventImportCommand
from scrapers.registry import SOURCES


class Command(BaseEventImportCommand):
    help = (
        "Ingest scraped events for a registered source from a JSON file "
        "produced by its scraper (see scrapers/registry.py)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            choices=sorted(SOURCES),
            help="Name of the scraper source to import.",
        )
        super().add_arguments(parser)

    def handle(self, *args, **options):
        cfg = SOURCES[options["source"]]
        self.external_source = cfg.external_source
        self.default_json_file = cfg.default_json_file
        self.default_venue_name = cfg.default_venue_name
        self.category_scope = cfg.category_scope
        self.allowed_image_domains = cfg.allowed_image_domains
        super().handle(*args, **options)
