"""Tests for the /subscribe/ page, including a CSS regression guard.

Regression: `.filter-panel` is used by two unrelated UIs — the collapsible
"More filters" panel in the event list/map quickbar (hidden until the
<details> disclosure opens) and the always-visible "Filter your feed" block
on this page (no <details> involved at all). A CSS rule like
`.filter-panel { display: none; }` with no ancestor scope hides both,
silently breaking this page's filters. The hide rule must stay scoped to an
ancestor (`.filter-quickbar .filter-panel`), never the bare class alone.
"""

import re
from pathlib import Path

import pytest
from django.urls import reverse

BASE_TEMPLATE = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "base.html"
)


def _inline_css():
    html = BASE_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert match, "expected an inline <style> block in base.html"
    return match.group(1)


def test_bare_filter_panel_selector_is_never_hidden_by_default():
    """No unscoped `.filter-panel { display: none }` rule may exist — it
    would hide every standalone usage of the class, not just the
    collapsible quickbar panel."""
    css = _inline_css()
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [s.strip() for s in selector_group.split(",")]
        if ".filter-panel" in selectors:
            body_compact = re.sub(r"\s+", "", body)
            assert "display:none" not in body_compact, (
                "found an unscoped '.filter-panel { display: none }' rule in "
                "base.html — this hides the subscribe page's always-visible "
                "filter block too; scope it to an ancestor instead, e.g. "
                "'.filter-quickbar .filter-panel'"
            )


@pytest.mark.django_db
class TestSubscribeView:
    def test_page_loads_with_filter_panel(self, client):
        resp = client.get(reverse("subscribe"))
        assert resp.status_code == 200
        assert b"Filter your feed" in resp.content
        assert b"filter-panel" in resp.content
        assert b"PERFORMANCE".lower() in resp.content.lower()

    def test_filter_panel_is_not_inside_the_quickbar_disclosure(self, client):
        """Structural precondition the CSS scoping fix relies on: this
        page's .filter-panel must never be nested under .filter-quickbar
        (that component is specific to the event list/map filter UI), or
        the collapsible hide/show rule would apply here too."""
        resp = client.get(reverse("subscribe"))
        # Search for the class as an HTML attribute value, not a bare
        # substring — the shared base.html stylesheet mentions these class
        # names in CSS selectors on every page regardless of this one's markup.
        assert b'class="filter-quickbar"' not in resp.content
        assert b'class="filter-disclosure"' not in resp.content
