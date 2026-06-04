"""Tests for the Guide page (static Markdown-rendered scene guide)."""

import pytest
from django.urls import reverse

from events.views import GUIDE_MARKDOWN_PATH


@pytest.mark.django_db
class TestGuideView:
    def test_guide_returns_200(self, client):
        resp = client.get(reverse("guide"))
        assert resp.status_code == 200

    def test_guide_uses_expected_template(self, client):
        resp = client.get(reverse("guide"))
        assert "guide.html" in [t.name for t in resp.templates]

    def test_guide_renders_hero_title(self, client):
        resp = client.get(reverse("guide"))
        assert "Guide" in resp.content.decode()

    def test_guide_renders_category_headings(self, client):
        html = client.get(reverse("guide")).content.decode()
        for category in (
            "Institutions",
            "Companies",
            "Cooperatives",
            "Festivals",
            "Spaces",
            "Blogs",
        ):
            assert category in html

    def test_guide_links_out_to_sources(self, client):
        html = client.get(reverse("guide")).content.decode()
        # Item titles are links to the original sources.
        assert 'href="https://dansehallerne.dk/en/about/"' in html
        assert 'href="https://bastard.blog/info/"' in html

    def test_guide_markdown_rendered_as_html(self, client):
        html = client.get(reverse("guide")).content.decode()
        # The raw Markdown heading syntax should be converted, not echoed.
        assert "## Institutions" not in html
        assert "<h2>Institutions</h2>" in html


def test_guide_markdown_file_exists_and_is_nonempty():
    text = GUIDE_MARKDOWN_PATH.read_text(encoding="utf-8")
    assert text.strip()
    # Every user-supplied category should be present in the source file.
    assert "## Festivals" in text


@pytest.mark.django_db
def test_guide_link_in_nav(client):
    html = client.get(reverse("event_list")).content.decode()
    assert reverse("guide") in html


@pytest.mark.django_db
def test_guide_in_sitemap(client):
    body = client.get("/sitemap.xml").content.decode()
    assert reverse("guide") in body
