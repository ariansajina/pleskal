"""Wheelchair-access helpers shared by the scrapers.

``Event.is_wheelchair_accessible`` is a positive claim, so a scraper sets it
only on evidence. That evidence comes at two levels:

* **the venue**: a publisher that always plays in one building (Dansehallerne,
  Dansekapellet) gets a fixed value, and one that plays in several (KBH Danser,
  HAUT, Sydhavn Teater) gets a per-venue lookup. Unknown venues are not claimed;
* **the event**: some sources state access per event (Sydhavn Teater's
  "Accessibility" section, Warehouse9's "Access Information" note). Those
  statements are classified here by :func:`wheelchair_access_from_text`.
"""

from __future__ import annotations

import re

# Words that make a sentence a statement about wheelchair / step-free access.
_ACCESS_TERM = (
    r"wheelchair|kørestol\w*|step[- ]?free|level[- ]?free|niveau[- ]?fri\w*"
    r"|reduced\s+mobility|gangbesvær\w*"
)
_ACCESS_TERM_RE = re.compile(_ACCESS_TERM, re.IGNORECASE)
# A negation up to three words before an access term: "not wheelchair
# accessible", "ikke er kørestolsvenligt", "no step-free access". "no stairs"
# is not one, since no access term follows it.
_NEGATED_RE = re.compile(
    r"\b(?:not|no|cannot|can['’]?t|isn['’]?t|unfortunately"
    r"|ikke|ingen|desværre|uden)\s+(?:[\w'’-]+\s+){0,3}?(?:" + _ACCESS_TERM + r")",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def wheelchair_access_from_text(text: str) -> bool | None:
    """Classify a venue's or event's own statement about wheelchair access.

    Returns False when a sentence denies access ("not wheelchair accessible",
    "ikke kørestolsvenligt"), True when one affirms it ("accessible for
    wheelchair users", "level free entrance") and there is no denial, and None
    when the text says nothing about it (e.g. "Accessible for non-Danish
    speakers"). A denial wins over an affirmation. Only a denial that names an
    access term counts, so "no accessible toilet" doesn't turn a step-free
    entrance into "not accessible".
    """
    affirmed = False
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        if not _ACCESS_TERM_RE.search(sentence):
            continue
        if _NEGATED_RE.search(sentence):
            return False
        affirmed = True
    return True if affirmed else None
