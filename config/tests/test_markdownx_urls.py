import pytest
from django.test import Client

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
class TestMarkdownxAuthGate:
    def test_anonymous_upload_redirects_to_login(self):
        client = Client()
        response = client.post("/markdownx/upload/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_anonymous_markdownify_redirects_to_login(self):
        client = Client()
        response = client.post("/markdownx/markdownify/", {"content": "**hi**"})
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_authenticated_markdownify_succeeds(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        response = client.post("/markdownx/markdownify/", {"content": "**hi**"})
        assert response.status_code == 200
