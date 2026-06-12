"""Single registry of scraper sources for the import pipeline.

Each entry wires a scraper's ``scrape()`` function to its import
configuration. ``run_scrapers`` iterates this registry, and the generic
``import_events <source>`` management command resolves its per-source
configuration from it — adding or retiring a source happens here (plus
``scrapers/sources.json`` for the publisher account, which is keyed by
``external_source`` and shared between sources where applicable).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from scrapers.dansehallerne import scrape as scrape_dansehallerne
from scrapers.dansehallerne_workshops import (
    scrape as scrape_dansehallerne_workshops,
)
from scrapers.hautscene import scrape as scrape_hautscene
from scrapers.kbhdanser import scrape as scrape_kbhdanser
from scrapers.sort_hvid import scrape as scrape_sort_hvid
from scrapers.sydhavnteater import scrape as scrape_sydhavnteater
from scrapers.toastercph import scrape as scrape_toastercph
from scrapers.warehouse9 import scrape as scrape_warehouse9


@dataclass(frozen=True)
class ScraperSource:
    """Pipeline configuration for one scraped source.

    ``name`` is the registry key used by ``run_scrapers --only`` and as the
    ``import_events`` positional argument. ``external_source`` is the value
    stored on Event rows and may differ from ``name`` (e.g. the ``sort_hvid``
    scraper writes ``external_source="sort-hvid"``); two sources may also
    share one ``external_source`` with complementary ``category_scope`` lists
    (the dansehallerne pair), which keeps their stale-deletion mutually
    exclusive.
    """

    name: str
    scrape: Callable[..., list[dict]]
    external_source: str
    default_venue_name: str
    # Allowlist of domains from which images may be downloaded (SSRF
    # mitigation). Subdomains are accepted automatically.
    allowed_image_domains: frozenset[str]
    scrape_kwargs: dict = field(default_factory=dict)
    # Restrict upsert/delete to these categories when multiple sources share
    # the same external_source.
    category_scope: list[str] | None = None

    @property
    def default_json_file(self) -> str:
        return f"{self.name}_events.json"


_ALL_SOURCES = [
    ScraperSource(
        name="dansehallerne",
        scrape=scrape_dansehallerne,
        scrape_kwargs={"delay": 0.5},
        external_source="dansehallerne",
        default_venue_name="Dansehallerne",
        category_scope=["performance", "talk", "openpractice", "social", "other"],
        allowed_image_domains=frozenset({"dansehallerne.dk"}),
    ),
    ScraperSource(
        name="dansehallerne_workshops",
        scrape=scrape_dansehallerne_workshops,
        scrape_kwargs={"delay": 0.5},
        external_source="dansehallerne",
        default_venue_name="Dansehallerne",
        category_scope=["workshop"],
        allowed_image_domains=frozenset({"dansehallerne.dk"}),
    ),
    ScraperSource(
        name="hautscene",
        scrape=scrape_hautscene,
        scrape_kwargs={"delay": 0.5},
        external_source="hautscene",
        default_venue_name="HAUT scene",
        # hautscene.dk is built on Webflow, which serves images from
        # website-files.com.
        allowed_image_domains=frozenset({"hautscene.dk", "website-files.com"}),
    ),
    ScraperSource(
        name="sydhavnteater",
        scrape=scrape_sydhavnteater,
        external_source="sydhavnteater",
        default_venue_name="Sydhavn Teater",
        # Subdomain matching covers cms.sydhavnteater.dk (Craft CMS image CDN).
        allowed_image_domains=frozenset({"sydhavnteater.dk"}),
    ),
    ScraperSource(
        name="toastercph",
        scrape=scrape_toastercph,
        scrape_kwargs={"delay": 0.5},
        external_source="toastercph",
        default_venue_name="Toaster CPH",
        allowed_image_domains=frozenset({"toastercph.dk"}),
    ),
    ScraperSource(
        name="kbhdanser",
        scrape=scrape_kbhdanser,
        scrape_kwargs={"delay": 1.5},
        external_source="kbhdanser",
        default_venue_name="Østre Gasværk Teater",
        allowed_image_domains=frozenset({"kbhdanser.dk"}),
    ),
    ScraperSource(
        name="sort_hvid",
        scrape=scrape_sort_hvid,
        scrape_kwargs={"delay": 0.5},
        external_source="sort-hvid",
        default_venue_name="Sort/Hvid",
        allowed_image_domains=frozenset({"sort-hvid.dk"}),
    ),
    ScraperSource(
        name="warehouse9",
        scrape=scrape_warehouse9,
        external_source="warehouse9",
        default_venue_name="Warehouse9",
        # Poster images are served from the WordPress media library on
        # warehouse9.dk.
        allowed_image_domains=frozenset({"warehouse9.dk"}),
    ),
]

SOURCES: dict[str, ScraperSource] = {s.name: s for s in _ALL_SOURCES}
