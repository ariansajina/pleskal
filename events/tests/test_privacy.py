"""Tests for the privacy notice page."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestPrivacyPage:
    def test_url(self):
        assert reverse("privacy") == "/privacy/"

    def test_renders(self, client):
        response = client.get("/privacy/")
        assert response.status_code == 200
        content = response.content.decode()
        assert '<h1 class="page-hero__title">Privacy</h1>' in content
        assert "mailto:hello.pleskal@proton.me" in content
        assert "Datatilsynet" in content

    def test_linked_only_from_footer(self, client):
        content = client.get("/about/").content.decode()
        assert content.count('href="/privacy/"') == 1
        footer = content[content.index('<footer class="site-footer">') :]
        assert 'href="/privacy/"' in footer
