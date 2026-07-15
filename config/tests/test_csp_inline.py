"""Guards against re-introducing markup the site's CSP silently blocks.

The CSP (config/middleware.py) sends `script-src 'self'` with no
`'unsafe-inline'`/`'unsafe-hashes'`, so any inline `<script>` (without a
`src`) or inline event-handler attribute (`onclick=`, `onchange=`, ...) is
executed by the browser as-is but never actually runs. These regressions are
invisible in normal testing since the markup renders fine — only the browser
console shows the CSP violation.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from events.tests.factories import EventFactory

INLINE_HANDLER_RE = re.compile(rb'\son[a-z]+\s*=\s*["\']', re.IGNORECASE)
INLINE_SCRIPT_RE = re.compile(
    rb"<script(?![^>]*\bsrc=)(?![^>]*type=[\"']application/(ld\+json|json)[\"'])[^>]*>\s*\S",
    re.IGNORECASE,
)


def assert_no_inline_js(response):
    content = response.content
    assert not INLINE_HANDLER_RE.search(content), (
        "inline event-handler attribute (onclick=/onchange=/...) found; "
        "the CSP blocks it — move the logic to static/js/*.js"
    )
    assert not INLINE_SCRIPT_RE.search(content), (
        "inline <script> without src found; the CSP blocks it — "
        "move the code to static/js/*.js and load it with {% static %}"
    )


@pytest.mark.django_db
class TestNoInlineJavascript:
    def test_event_list(self, client):
        assert_no_inline_js(client.get(reverse("event_list")))

    def test_event_detail(self, client):
        event = EventFactory.create()
        assert_no_inline_js(client.get(event.get_absolute_url()))

    def test_event_form(self, client):
        user = UserFactory()
        client.force_login(user)
        assert_no_inline_js(client.get(reverse("event_create")))

    def test_login(self, client):
        assert_no_inline_js(client.get(reverse("login")))
