"""Tests for Feature 11: Django admin moderation enhancements."""

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from events.models import EventStatus
from events.tests.factories import EventFactory


def _make_superuser():
    return UserFactory(is_staff=True, is_superuser=True, password="adminpass")


@pytest.mark.django_db
class TestApproveAction:
    def test_approve_action_sets_status(self, client):
        superuser = _make_superuser()
        event = EventFactory(status=EventStatus.PENDING)
        client.force_login(superuser)

        changelist_url = reverse("admin:events_event_changelist")
        resp = client.post(
            changelist_url,
            {
                "action": "approve_events",
                "_selected_action": [str(event.pk)],
            },
        )
        assert resp.status_code in (200, 302)
        event.refresh_from_db()
        assert event.status == EventStatus.APPROVED

    def test_approve_action_also_approves_user(self, client):
        superuser = _make_superuser()
        user = UserFactory(is_approved=False)
        event = EventFactory(status=EventStatus.PENDING, submitted_by=user)
        client.force_login(superuser)

        client.post(
            reverse("admin:events_event_changelist"),
            {
                "action": "approve_events",
                "_selected_action": [str(event.pk)],
            },
        )
        user.refresh_from_db()
        assert user.is_approved is True

    def test_reject_action_requires_note(self, client):
        superuser = _make_superuser()
        event = EventFactory(status=EventStatus.PENDING)
        client.force_login(superuser)

        # First POST triggers redirect to intermediate page
        resp = client.post(
            reverse("admin:events_event_changelist"),
            {
                "action": "reject_events",
                "_selected_action": [str(event.pk)],
            },
        )
        assert resp.status_code == 302

        # Follow redirect to intermediate page
        intermediate_url = reverse("admin:events_event_reject_intermediate")
        resp = client.get(intermediate_url)
        assert resp.status_code == 200

        # Submit with empty note — should re-render the form with errors
        resp = client.post(intermediate_url, {"rejection_note": ""})
        assert resp.status_code == 200
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING  # not changed

    def test_reject_action_with_note_rejects_event(self, client):
        superuser = _make_superuser()
        event = EventFactory(status=EventStatus.PENDING)
        client.force_login(superuser)

        # Trigger action to store IDs in session
        client.post(
            reverse("admin:events_event_changelist"),
            {
                "action": "reject_events",
                "_selected_action": [str(event.pk)],
            },
        )

        # Submit rejection with a note
        resp = client.post(
            reverse("admin:events_event_reject_intermediate"),
            {"rejection_note": "Insufficient detail"},
        )
        assert resp.status_code == 302
        event.refresh_from_db()
        assert event.status == EventStatus.REJECTED
        assert event.rejection_note == "Insufficient detail"


@pytest.mark.django_db
class TestAccountsAdmin:
    def test_promote_to_moderator_action(self, client):
        superuser = _make_superuser()
        user = UserFactory(is_moderator=False)
        client.force_login(superuser)

        resp = client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "promote_to_moderator",
                "_selected_action": [str(user.pk)],
            },
        )
        assert resp.status_code in (200, 302)
        user.refresh_from_db()
        assert user.is_moderator is True
