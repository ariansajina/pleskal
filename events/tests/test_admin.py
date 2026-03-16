"""Tests for event admin."""

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from events.tests.factories import EventFactory


def _make_superuser():
    return UserFactory.create(is_staff=True, is_superuser=True, password="adminpass")


@pytest.mark.django_db
class TestEventAdmin:
    def test_changelist_accessible(self, client):
        superuser = _make_superuser()
        client.force_login(superuser)
        resp = client.get(reverse("admin:events_event_changelist"))
        assert resp.status_code == 200

    def test_change_view_accessible(self, client):
        superuser = _make_superuser()
        event = EventFactory.create()
        client.force_login(superuser)
        resp = client.get(reverse("admin:events_event_change", args=[event.pk]))
        assert resp.status_code == 200
