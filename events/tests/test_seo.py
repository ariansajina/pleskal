"""Tests for SEO features: sitemap, robots.txt, JSON-LD, canonical tags."""

import json

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from events.tests.factories import EventFactory


@pytest.mark.django_db
class TestSitemap:
    def test_sitemap_returns_xml(self, client):
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "application/xml" in resp["Content-Type"]

    def test_sitemap_includes_published_event(self, client):
        event = EventFactory.create()
        resp = client.get("/sitemap.xml")
        body = resp.content.decode()
        assert event.get_absolute_url() in body

    def test_sitemap_excludes_draft_event(self, client):
        draft = EventFactory.create(is_draft=True)
        resp = client.get("/sitemap.xml")
        assert draft.get_absolute_url() not in resp.content.decode()

    def test_sitemap_includes_static_pages(self, client):
        resp = client.get("/sitemap.xml")
        body = resp.content.decode()
        assert reverse("event_list") in body
        assert reverse("about") in body
        assert reverse("subscribe") in body

    def test_sitemap_includes_publisher_with_events(self, client):
        user = UserFactory.create()
        EventFactory.create(submitted_by=user)
        resp = client.get("/sitemap.xml")
        url = reverse("publisher_profile", kwargs={"slug": user.display_name_slug})
        assert url in resp.content.decode()

    def test_sitemap_excludes_publisher_without_events(self, client):
        user = UserFactory.create()
        resp = client.get("/sitemap.xml")
        url = reverse("publisher_profile", kwargs={"slug": user.display_name_slug})
        assert url not in resp.content.decode()


@pytest.mark.django_db
class TestRobotsTxt:
    def test_robots_returns_plain_text(self, client):
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/plain"

    def test_robots_references_sitemap(self, client):
        resp = client.get("/robots.txt")
        assert "Sitemap:" in resp.content.decode()
        assert "/sitemap.xml" in resp.content.decode()

    def test_robots_blocks_private_paths(self, client):
        body = client.get("/robots.txt").content.decode()
        assert "Disallow: /admin/" in body
        assert "Disallow: /accounts/login/" in body

    def test_robots_allows_publisher_profiles(self, client):
        body = client.get("/robots.txt").content.decode()
        # Must not blanket-block /accounts/, which would hide public profiles.
        assert "Disallow: /accounts/\n" not in body


@pytest.mark.django_db
class TestEventJsonLd:
    def _extract_jsonld(self, html):
        marker = '<script type="application/ld+json">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        return html[start:end]

    def test_detail_includes_event_jsonld(self, client):
        event = EventFactory.create()
        resp = client.get(event.get_absolute_url())
        html = resp.content.decode()
        assert '<script type="application/ld+json">' in html
        data = json.loads(self._extract_jsonld(html))
        assert data["@type"] == "Event"
        assert data["name"] == event.title
        assert data["location"]["name"] == event.venue_name

    def test_jsonld_escapes_html_in_title(self, client):
        event = EventFactory.create(title="Tap </script><script>alert(1)</script>")
        resp = client.get(event.get_absolute_url())
        html = resp.content.decode()
        # The injected closing tag must be escaped, not break out of the block.
        assert "</script><script>alert(1)" not in html
        assert "\\u003c/script\\u003e" in html

    def test_draft_detail_has_no_jsonld(self, client):
        owner = UserFactory.create()
        draft = EventFactory.create(submitted_by=owner, is_draft=True)
        client.force_login(owner)
        resp = client.get(draft.get_absolute_url())
        assert '<script type="application/ld+json">' not in resp.content.decode()

    def test_free_event_jsonld_has_offer(self, client):
        event = EventFactory.create(is_free=True)
        resp = client.get(event.get_absolute_url())
        data = json.loads(self._extract_jsonld(resp.content.decode()))
        assert data["offers"]["price"] == "0"
        assert data["offers"]["priceCurrency"] == "DKK"


@pytest.mark.django_db
class TestCanonical:
    def test_event_detail_has_canonical(self, client):
        event = EventFactory.create()
        resp = client.get(event.get_absolute_url())
        html = resp.content.decode()
        assert '<link rel="canonical"' in html

    def test_list_canonical_excludes_query_string(self, client):
        EventFactory.create()
        resp = client.get(reverse("event_list") + "?category=social&page=1")
        html = resp.content.decode()
        assert '<link rel="canonical"' in html
        assert "category=social" not in html.split('rel="canonical"')[1].split(">")[0]


@pytest.mark.django_db
def test_event_get_absolute_url():
    event = EventFactory.build(slug="my-event")
    assert event.get_absolute_url() == "/events/my-event/"


@pytest.mark.django_db
def test_event_card_thumbnail_is_lazy(client):
    EventFactory.create(image="events/example.webp")
    resp = client.get(reverse("event_list"))
    assert b'loading="lazy"' in resp.content
