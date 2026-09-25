"""Search-engine metadata: schema.org JSON-LD and meta descriptions.

JSON-LD output is escaped the same way Django's ``json_script`` escapes data so
it is safe to embed inside a ``<script type="application/ld+json">`` block even
when event fields contain ``<``, ``>`` or ``&``.
"""

import json

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.safestring import mark_safe

from .feeds import _plain_text
from .models import Event
from .templatetags.markdown_filters import plain_excerpt

_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}
_TYPE = "@type"


def _script_json(data: dict) -> str:
    serialized = json.dumps(data, ensure_ascii=False)
    for char, replacement in _ESCAPES.items():
        serialized = serialized.replace(char, replacement)
    return mark_safe(serialized)  # noqa: S308 - escaped above for safe <script> embedding


def event_meta_description(event: Event) -> str:
    """What/where/when first, so search snippets answer the searcher at a glance."""
    start = date_format(timezone.localtime(event.start_datetime), "l j F Y, H:i")
    summary = f"{event.get_category_display()} at {event.venue_name}, {start}."  # ty: ignore[unresolved-attribute]
    excerpt = plain_excerpt(str(event.description), 160)
    return f"{summary} {excerpt}" if excerpt else summary


def event_jsonld(event: Event, request) -> str:
    """Return a CSP-safe JSON-LD string describing the event."""
    origin = f"https://{settings.SITE_DOMAIN}"
    location: dict = {
        _TYPE: "Place",
        "name": event.venue_name,
    }
    # Google requires an address for Event rich results; fall back to the city
    # this calendar covers when the venue has none on record.
    location["address"] = event.venue_address or {
        _TYPE: "PostalAddress",
        "addressLocality": "Copenhagen",
        "addressCountry": "DK",
    }
    if event.has_map_location:
        location["geo"] = {
            _TYPE: "GeoCoordinates",
            "latitude": event.latitude,
            "longitude": event.longitude,
        }

    data: dict = {
        "@context": "https://schema.org",
        _TYPE: "Event",
        "name": event.title,
        "startDate": timezone.localtime(event.start_datetime).isoformat(),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": location,
        "url": origin + event.get_absolute_url(),
    }

    if event.end_datetime:
        data["endDate"] = timezone.localtime(event.end_datetime).isoformat()

    # The scraped-event disclaimer is for readers of the page; leaving it out
    # keeps it from becoming the event summary in search results.
    description = _plain_text(str(event.description or ""))
    if description:
        data["description"] = description[:500]

    data["image"] = [request.build_absolute_uri(event.display_image_url)]

    if event.is_free or event.price_note or event.source_url:
        offer: dict = {
            _TYPE: "Offer",
            "availability": "https://schema.org/InStock",
        }
        if event.is_free:
            offer["price"] = "0"
            offer["priceCurrency"] = "DKK"
        offer["url"] = event.source_url or data["url"]
        data["offers"] = offer

    publisher = event.submitted_by
    if publisher:
        data["organizer"] = {
            _TYPE: "Organization",
            "name": publisher.public_name,  # ty: ignore[unresolved-attribute]
            "url": origin
            + reverse(
                "publisher_profile",
                kwargs={"slug": publisher.display_name_slug},  # ty: ignore[unresolved-attribute]
            ),
        }

    return _script_json(data)


def publisher_jsonld(publisher) -> str:
    """schema.org/ProfilePage for a publisher, tying the page to their website."""
    origin = f"https://{settings.SITE_DOMAIN}"
    entity: dict = {_TYPE: "Organization", "name": publisher.public_name}
    if publisher.website:
        entity["sameAs"] = [publisher.website]
    bio = plain_excerpt(publisher.bio, 300)
    if bio:
        entity["description"] = bio
    return _script_json(
        {
            "@context": "https://schema.org",
            _TYPE: "ProfilePage",
            "url": origin
            + reverse(
                "publisher_profile", kwargs={"slug": publisher.display_name_slug}
            ),
            "mainEntity": entity,
        }
    )
