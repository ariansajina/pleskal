"""Tests for the PWA endpoints (manifest, service worker, offline page)."""

from __future__ import annotations

import json

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestManifestView:
    def test_returns_200(self, client):
        response = client.get(reverse("pwa_manifest"))
        assert response.status_code == 200

    def test_content_type_is_manifest(self, client):
        response = client.get(reverse("pwa_manifest"))
        assert response["Content-Type"].startswith("application/manifest+json")

    def test_served_at_root(self, client):
        response = client.get("/manifest.webmanifest")
        assert response.status_code == 200

    def test_is_valid_json(self, client):
        response = client.get(reverse("pwa_manifest"))
        data = json.loads(response.content)
        assert data["name"]
        assert data["short_name"] == "pleskal"
        assert data["start_url"] == "/?source=pwa"
        assert data["display"] == "standalone"
        assert data["theme_color"]
        assert data["background_color"]

    def test_includes_required_icons(self, client):
        response = client.get(reverse("pwa_manifest"))
        data = json.loads(response.content)
        sizes = {icon["sizes"] for icon in data["icons"]}
        assert "192x192" in sizes
        assert "512x512" in sizes
        purposes = {icon["purpose"] for icon in data["icons"]}
        assert "maskable" in purposes

    def test_cache_token_is_templated_into_icon_urls(self, client, settings):
        settings.APP_VERSION = "abc123"
        response = client.get(reverse("pwa_manifest"))
        data = json.loads(response.content)
        for icon in data["icons"]:
            assert "v=abc123" in icon["src"]


@pytest.mark.django_db
class TestServiceWorkerView:
    def test_returns_200(self, client):
        response = client.get(reverse("pwa_service_worker"))
        assert response.status_code == 200

    def test_content_type_is_javascript(self, client):
        response = client.get(reverse("pwa_service_worker"))
        assert response["Content-Type"].startswith("application/javascript")

    def test_served_at_origin_root(self, client):
        """SW must be reachable at /service-worker.js for site-wide scope."""
        response = client.get("/service-worker.js")
        assert response.status_code == 200

    def test_service_worker_allowed_header(self, client):
        response = client.get(reverse("pwa_service_worker"))
        assert response["Service-Worker-Allowed"] == "/"

    def test_no_cache_control(self, client):
        response = client.get(reverse("pwa_service_worker"))
        assert "no-cache" in response["Cache-Control"]

    def test_cache_token_is_embedded(self, client, settings):
        settings.APP_VERSION = "deadbeef"
        response = client.get(reverse("pwa_service_worker"))
        body = response.content.decode()
        assert "deadbeef" in body
        assert 'CACHE_VERSION = "deadbeef"' in body

    def test_cache_token_falls_back_to_dev_when_unset(self, client, settings):
        settings.APP_VERSION = ""
        response = client.get(reverse("pwa_service_worker"))
        assert 'CACHE_VERSION = "dev"' in response.content.decode()

    def test_precache_lists_offline_fallback(self, client):
        response = client.get(reverse("pwa_service_worker"))
        body = response.content.decode()
        assert "/offline/" in body

    def test_authenticated_paths_are_network_only(self, client):
        response = client.get(reverse("pwa_service_worker"))
        body = response.content.decode()
        for prefix in ("/accounts/", "/claim/", "/admin/"):
            assert prefix in body


@pytest.mark.django_db
class TestOfflineView:
    def test_returns_200(self, client):
        response = client.get(reverse("pwa_offline"))
        assert response.status_code == 200

    def test_renders_html(self, client):
        response = client.get(reverse("pwa_offline"))
        assert b"offline" in response.content.lower()


@pytest.mark.django_db
class TestBaseTemplateIntegration:
    def test_manifest_link_present(self, client):
        response = client.get("/")
        assert b'rel="manifest"' in response.content

    def test_theme_color_meta_present(self, client):
        response = client.get("/")
        assert b'name="theme-color"' in response.content

    def test_sw_registration_script_loaded(self, client):
        response = client.get("/")
        assert b"pwa.js" in response.content
