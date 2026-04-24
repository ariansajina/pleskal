"""Tests for PWA routes: manifest, service worker, and offline page."""

import pytest
from django.conf import settings
from django.urls import reverse


@pytest.mark.django_db
class TestManifestView:
    def test_returns_200(self, client):
        resp = client.get(reverse("pwa_manifest"))
        assert resp.status_code == 200

    def test_content_type(self, client):
        resp = client.get(reverse("pwa_manifest"))
        assert resp["Content-Type"] == "application/manifest+json"

    def test_contains_required_fields(self, client):
        resp = client.get(reverse("pwa_manifest"))
        content = resp.content.decode()
        assert '"name"' in content
        assert '"short_name"' in content
        assert '"start_url"' in content
        assert '"display"' in content
        assert '"standalone"' in content
        assert '"icons"' in content

    def test_start_url_includes_pwa_source(self, client):
        resp = client.get(reverse("pwa_manifest"))
        assert "source=pwa" in resp.content.decode()

    def test_served_at_root(self, client):
        resp = client.get("/manifest.webmanifest")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestServiceWorkerView:
    def test_returns_200(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert resp.status_code == 200

    def test_content_type(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert resp["Content-Type"] == "application/javascript"

    def test_served_at_root(self, client):
        resp = client.get("/service-worker.js")
        assert resp.status_code == 200

    def test_contains_deploy_sha(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert settings.DEPLOY_SHA in resp.content.decode()

    def test_no_cache_header(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert "no-cache" in resp["Cache-Control"]

    def test_service_worker_allowed_header(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert resp["Service-Worker-Allowed"] == "/"

    def test_contains_offline_fallback(self, client):
        resp = client.get(reverse("pwa_service_worker"))
        assert "/offline/" in resp.content.decode()


@pytest.mark.django_db
class TestOfflineView:
    def test_returns_200(self, client):
        resp = client.get(reverse("pwa_offline"))
        assert resp.status_code == 200

    def test_content_type(self, client):
        resp = client.get(reverse("pwa_offline"))
        assert "text/html" in resp["Content-Type"]
