"""Venue-centric views over ``Event.venue_name``.

This module provides the single source of truth for the ``venue_name -> slug``
mapping used by :mod:`events.views`, :mod:`events.feeds`, and the venue
templates. No ``Venue`` model exists yet — venues are derived at query time by
grouping events on a *canonicalized* venue name.

**Canonicalization rule (v1, exact-after-canonicalization only):**

1. Unicode NFKC normalize, then strip leading/trailing whitespace.
2. Collapse runs of internal whitespace to a single space.
3. Case-fold (``str.casefold``) for grouping / slug input.

No fuzzy matching: "Dansehallerne " and "dansehallerne" group together, but
"Dansehallerne " and "Dansehallerne (studio 1)" do not. Promote to a first-class
``Venue`` model (and migration) when fuzzy matching / merging is needed — see
issue #15 (claim-a-venue).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify

_WHITESPACE_RE = re.compile(r"\s+")


def canonical_name(name: str) -> str:
    """Return the canonical (grouping) form of a venue name.

    See module docstring for the rule.
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKC", name)
    collapsed = _WHITESPACE_RE.sub(" ", normalized).strip()
    return collapsed.casefold()


def canonical_slug(name: str) -> str:
    """Return the stable URL slug for ``name``.

    Derived deterministically from the canonical name: slugify first, then —
    if the result is empty or would collide with a different canonical name
    after slugifying — append a short hash of the canonical name to make it
    stable and unique.

    Slugs are stable across requests for the same canonical name. Two names
    that canonicalize to the same value always produce the same slug.
    """
    canonical = canonical_name(name)
    slug = slugify(canonical)
    suffix = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:6]
    if not slug:
        return f"venue-{suffix}"
    return f"{slug}-{suffix}"


class VenueEntry(NamedTuple):
    """One row of the venue index."""

    slug: str
    display_name: str
    canonical: str
    count: int


@dataclass(frozen=True)
class VenueDetail:
    """Details for a single venue page."""

    slug: str
    display_name: str
    canonical: str
    addresses: list[str]
    latitude: float | None
    longitude: float | None


def _upcoming_published_events():
    from .models import Event

    return Event.objects.filter(
        is_draft=False, start_datetime__gte=timezone.now()
    )


def list_venues() -> list[VenueEntry]:
    """Return venues with at least one upcoming, non-draft event.

    Results are sorted alphabetically by display name (case-insensitive).
    The display name is the most common raw ``venue_name`` spelling within
    each canonical group; ties are broken alphabetically for stability.
    """
    rows = (
        _upcoming_published_events()
        .values("venue_name")
        .annotate(count=Count("id"))
    )

    totals: dict[str, int] = {}
    spellings: dict[str, dict[str, int]] = {}
    for row in rows:
        raw = row["venue_name"] or ""
        canonical = canonical_name(raw)
        if not canonical:
            continue
        totals[canonical] = totals.get(canonical, 0) + row["count"]
        spellings.setdefault(canonical, {})[raw] = (
            spellings.get(canonical, {}).get(raw, 0) + row["count"]
        )

    entries: list[VenueEntry] = []
    for canonical, total in totals.items():
        display_name = sorted(
            spellings[canonical].items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        entries.append(
            VenueEntry(
                slug=canonical_slug(display_name),
                display_name=display_name,
                canonical=canonical,
                count=total,
            )
        )

    entries.sort(key=lambda e: e.display_name.casefold())
    return entries


def find_venue(slug: str) -> VenueDetail | None:
    """Look up a venue by slug across *all* events (including past/draftless).

    The canonical list only surfaces venues with upcoming events, but the
    detail page should still resolve if the user follows a link after the
    last event passed — we'll just render an empty list.

    Returns ``None`` if no venue matches the slug.
    """
    from .models import Event

    # Only consider non-draft events for public venue resolution.
    raw_names = (
        Event.objects.filter(is_draft=False)
        .values_list("venue_name", flat=True)
        .distinct()
    )

    best_match: tuple[str, str] | None = None  # (display_name, canonical)
    addresses: set[str] = set()
    latitude: float | None = None
    longitude: float | None = None

    canonical_match: str | None = None
    for raw in raw_names:
        if not raw:
            continue
        canonical = canonical_name(raw)
        if canonical_slug(raw) == slug:
            canonical_match = canonical
            best_match = (raw, canonical)
            break

    if canonical_match is None or best_match is None:
        return None

    # Collect all addresses and first-known coordinates across the canonical group.
    matching_events = Event.objects.filter(is_draft=False)
    for event in matching_events.only(
        "venue_name", "venue_address", "latitude", "longitude"
    ):
        if canonical_name(event.venue_name) != canonical_match:
            continue
        if event.venue_address:
            addresses.add(event.venue_address)
        if latitude is None and event.latitude is not None:
            latitude = event.latitude
            longitude = event.longitude

    return VenueDetail(
        slug=slug,
        display_name=best_match[0],
        canonical=canonical_match,
        addresses=sorted(addresses),
        latitude=latitude,
        longitude=longitude,
    )


def events_for_venue(canonical: str, *, include_past: bool = False):
    """Return a queryset of non-draft events whose venue canonicalizes to ``canonical``.

    Django can't filter by a canonicalization function at the database layer
    without a bespoke index, so this does the canonicalization in Python:
    fetch all distinct raw spellings that canonicalize to the target, then
    build an ``IN`` query on ``venue_name``. For a city-scale calendar the
    set of spellings per venue is tiny.
    """
    from .models import Event

    raw_spellings = {
        raw
        for raw in Event.objects.filter(is_draft=False)
        .values_list("venue_name", flat=True)
        .distinct()
        if canonical_name(raw) == canonical
    }

    qs = Event.objects.filter(is_draft=False, venue_name__in=raw_spellings)
    if not include_past:
        qs = qs.filter(start_datetime__gte=timezone.now())
    return qs
