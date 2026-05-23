"""schema.org/Event JSON-LD builder for event detail pages.

The output is escaped the same way Django's ``json_script`` escapes data so it
is safe to embed inside a ``<script type="application/ld+json">`` block even
when event fields contain ``<``, ``>`` or ``&``.
"""

import json

from django.urls import reverse
from django.utils.safestring import mark_safe

from .feeds import _plain_text
from .models import Event

_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}
_TYPE = "@type"


def event_jsonld(event: Event, request) -> str:
    """Return a CSP-safe JSON-LD string describing the event."""
    location: dict = {
        _TYPE: "Place",
        "name": event.venue_name,
    }
    if event.venue_address:
        location["address"] = event.venue_address
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
        "startDate": event.start_datetime.isoformat(),  # ty: ignore[unresolved-attribute]
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": location,
        "url": request.build_absolute_uri(event.get_absolute_url()),
    }

    if event.end_datetime:
        data["endDate"] = event.end_datetime.isoformat()  # ty: ignore[unresolved-attribute]

    description = _plain_text(str(event.get_display_description() or ""))
    if description:
        data["description"] = description[:500]

    if event.image:
        data["image"] = [
            request.build_absolute_uri(event.image.url)  # ty: ignore[unresolved-attribute]
        ]

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
            "url": request.build_absolute_uri(
                reverse(
                    "publisher_profile",
                    kwargs={"slug": publisher.display_name_slug},  # ty: ignore[unresolved-attribute]
                )
            ),
        }

    serialized = json.dumps(data, ensure_ascii=False)
    for char, replacement in _ESCAPES.items():
        serialized = serialized.replace(char, replacement)
    return mark_safe(serialized)  # noqa: S308 - escaped above for safe <script> embedding
