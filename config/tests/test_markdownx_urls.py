import pytest
from django.test import Client

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
class TestMarkdownxAuthGate:
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
        assert b"<strong>hi</strong>" in response.content


@pytest.mark.django_db
class TestMarkdownxPreviewSanitized:
    """The editor preview must be as sanitized as the published page."""

    def test_preview_strips_script_and_event_handlers(self):
        user = UserFactory.create()
        client = Client()
        client.force_login(user)
        content = (
            "<script>alert(1)</script>\n\n"
            '<img src="x" onerror="alert(1)">\n\n'
            "[link](javascript:alert(1))"
        )
        response = client.post("/markdownx/markdownify/", {"content": content})
        assert response.status_code == 200
        body = response.content.decode()
        assert "<script" not in body
        assert "<img" not in body
        assert "onerror" not in body
        assert "javascript:" not in body


@pytest.mark.django_db
class TestMarkdownxUploadNotMounted:
    """Rendered Markdown strips <img>, so the upload endpoint is not routed."""

    def test_anonymous_upload_is_404(self):
        response = Client().post("/markdownx/upload/")
        assert response.status_code == 404

    def test_authenticated_upload_is_404(self):
        client = Client()
        client.force_login(UserFactory.create())
        response = client.post("/markdownx/upload/")
        assert response.status_code == 404
