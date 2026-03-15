"""Tests for the dedicated moderation UI views."""

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from events.models import EventStatus
from events.tests.factories import EventFactory


def _moderator(**kwargs):
    return UserFactory.create(is_approved=True, is_moderator=True, **kwargs)


def _regular_user(**kwargs):
    return UserFactory.create(is_approved=True, **kwargs)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModeratorAccess:
    """All moderation pages require is_moderator=True."""

    urls = [
        "moderation_dashboard",
        "moderation_events",
        "moderation_history",
        "moderation_users",
    ]

    def test_anonymous_redirects_to_login(self, client):
        for url_name in self.urls:
            resp = client.get(reverse(url_name))
            assert resp.status_code == 302, f"{url_name} should redirect anon"
            assert "/accounts/login/" in resp["Location"]

    def test_non_moderator_gets_403(self, client):
        user = _regular_user()
        client.force_login(user)
        for url_name in self.urls:
            resp = client.get(reverse(url_name))
            assert resp.status_code == 403, f"{url_name} should deny non-moderator"

    def test_moderator_can_access(self, client):
        mod = _moderator()
        client.force_login(mod)
        for url_name in self.urls:
            resp = client.get(reverse(url_name))
            assert resp.status_code == 200, f"{url_name} should allow moderator"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationDashboard:
    def test_shows_pending_counts(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.PENDING)
        EventFactory.create(status=EventStatus.APPROVED)
        UserFactory.create(is_approved=False)

        client.force_login(mod)
        resp = client.get(reverse("moderation_dashboard"))
        assert resp.status_code == 200
        assert resp.context["stats"]["pending_events"] == 1
        assert resp.context["stats"]["pending_users"] >= 1

    def test_shows_pending_events(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.PENDING, title="Pending Salsa")
        EventFactory.create(status=EventStatus.APPROVED, title="Approved Bachata")

        client.force_login(mod)
        resp = client.get(reverse("moderation_dashboard"))
        events = resp.context["pending_events"]
        titles = [e.title for e in events]
        assert "Pending Salsa" in titles
        assert "Approved Bachata" not in titles


# ---------------------------------------------------------------------------
# Event approve
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationEventApprove:
    def test_approve_event(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.post(reverse("moderation_event_approve", args=[event.pk]))
        assert resp.status_code == 302
        event.refresh_from_db()
        assert event.status == EventStatus.APPROVED

    def test_approve_event_htmx(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_event_approve", args=[event.pk]),
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        event.refresh_from_db()
        assert event.status == EventStatus.APPROVED

    def test_approve_auto_approves_user(self, client):
        mod = _moderator()
        submitter = UserFactory.create(is_approved=False)
        event = EventFactory.create(status=EventStatus.PENDING, submitted_by=submitter)

        client.force_login(mod)
        client.post(reverse("moderation_event_approve", args=[event.pk]))
        submitter.refresh_from_db()
        assert submitter.is_approved is True


# ---------------------------------------------------------------------------
# Event reject
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationEventReject:
    def test_reject_event_with_note(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_event_reject", args=[event.pk]),
            {"rejection_note": "Duplicate event"},
        )
        assert resp.status_code == 302
        event.refresh_from_db()
        assert event.status == EventStatus.REJECTED
        assert event.rejection_note == "Duplicate event"

    def test_reject_without_note_fails(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        client.post(
            reverse("moderation_event_reject", args=[event.pk]),
            {"rejection_note": ""},
        )
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING

    def test_reject_without_note_htmx_returns_422(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_event_reject", args=[event.pk]),
            {"rejection_note": ""},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 422

    def test_reject_htmx_returns_updated_row(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_event_reject", args=[event.pk]),
            {"rejection_note": "Not a dance event"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        event.refresh_from_db()
        assert event.status == EventStatus.REJECTED


# ---------------------------------------------------------------------------
# Event delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationEventDelete:
    def test_delete_event(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)
        pk = event.pk

        client.force_login(mod)
        resp = client.post(reverse("moderation_event_delete", args=[pk]))
        assert resp.status_code == 302
        from events.models import Event

        assert not Event.objects.filter(pk=pk).exists()

    def test_delete_event_htmx_returns_empty(self, client):
        mod = _moderator()
        event = EventFactory.create(status=EventStatus.PENDING)
        pk = event.pk

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_event_delete", args=[pk]),
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert resp.content == b""

    def test_non_moderator_cannot_delete(self, client):
        user = _regular_user()
        event = EventFactory.create(status=EventStatus.PENDING)

        client.force_login(user)
        resp = client.post(reverse("moderation_event_delete", args=[event.pk]))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Event list (filtered)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationEventList:
    def test_lists_all_events(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.PENDING)
        EventFactory.create(status=EventStatus.APPROVED)
        EventFactory.create(status=EventStatus.REJECTED, rejection_note="bad")

        client.force_login(mod)
        resp = client.get(reverse("moderation_events"))
        assert len(resp.context["events"]) == 3

    def test_filter_by_status(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.PENDING)
        EventFactory.create(status=EventStatus.APPROVED)

        client.force_login(mod)
        resp = client.get(reverse("moderation_events"), {"status": "pending"})
        assert all(e.status == EventStatus.PENDING for e in resp.context["events"])

    def test_search_by_title(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.PENDING, title="Salsa Night")
        EventFactory.create(status=EventStatus.PENDING, title="Bachata Party")

        client.force_login(mod)
        resp = client.get(reverse("moderation_events"), {"q": "Salsa"})
        titles = [e.title for e in resp.context["events"]]
        assert "Salsa Night" in titles
        assert "Bachata Party" not in titles

    def test_htmx_returns_partial(self, client):
        mod = _moderator()
        client.force_login(mod)
        resp = client.get(reverse("moderation_events"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        # HTMX responses don't extend base template
        assert b"<!DOCTYPE html>" not in resp.content


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationHistory:
    def test_shows_approved_and_rejected(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.APPROVED)
        EventFactory.create(status=EventStatus.REJECTED, rejection_note="spam")
        EventFactory.create(status=EventStatus.PENDING)

        client.force_login(mod)
        resp = client.get(reverse("moderation_history"))
        # Should only show approved and rejected, not pending
        assert len(resp.context["events"]) == 2

    def test_filter_by_status(self, client):
        mod = _moderator()
        EventFactory.create(status=EventStatus.APPROVED)
        EventFactory.create(status=EventStatus.REJECTED, rejection_note="dup")

        client.force_login(mod)
        resp = client.get(reverse("moderation_history"), {"status": "approved"})
        assert all(e.status == EventStatus.APPROVED for e in resp.context["events"])


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestModerationUserList:
    def test_lists_users(self, client):
        mod = _moderator()
        UserFactory.create()
        UserFactory.create()

        client.force_login(mod)
        resp = client.get(reverse("moderation_users"))
        # At least 3 users (mod + 2 created)
        assert len(resp.context["users"]) >= 3

    def test_filter_pending(self, client):
        mod = _moderator()
        UserFactory.create(is_approved=False)

        client.force_login(mod)
        resp = client.get(reverse("moderation_users"), {"filter": "pending"})
        assert all(not u.is_approved for u in resp.context["users"])

    def test_search_by_username(self, client):
        mod = _moderator()
        UserFactory.create(username="salsa_king", is_approved=False)

        client.force_login(mod)
        resp = client.get(reverse("moderation_users"), {"q": "salsa_king"})
        usernames = [u.username for u in resp.context["users"]]
        assert "salsa_king" in usernames


@pytest.mark.django_db
class TestModerationUserApprove:
    def test_approve_user(self, client):
        mod = _moderator()
        user = UserFactory.create(is_approved=False)

        client.force_login(mod)
        resp = client.post(reverse("moderation_user_approve", args=[user.pk]))
        assert resp.status_code == 302
        user.refresh_from_db()
        assert user.is_approved is True

    def test_approve_user_htmx(self, client):
        mod = _moderator()
        user = UserFactory.create(is_approved=False)

        client.force_login(mod)
        resp = client.post(
            reverse("moderation_user_approve", args=[user.pk]),
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        user.refresh_from_db()
        assert user.is_approved is True


@pytest.mark.django_db
class TestModerationUserRevoke:
    def test_revoke_user(self, client):
        mod = _moderator()
        user = UserFactory.create(is_approved=True)

        client.force_login(mod)
        resp = client.post(reverse("moderation_user_revoke", args=[user.pk]))
        assert resp.status_code == 302
        user.refresh_from_db()
        assert user.is_approved is False


@pytest.mark.django_db
class TestModerationUserToggleModerator:
    def test_promote_user(self, client):
        mod = _moderator()
        user = UserFactory.create(is_approved=True)

        client.force_login(mod)
        resp = client.post(reverse("moderation_user_toggle_moderator", args=[user.pk]))
        assert resp.status_code == 302
        user.refresh_from_db()
        assert user.is_moderator is True
        assert user.is_approved is True

    def test_demote_user(self, client):
        mod = _moderator()
        user = UserFactory.create(is_approved=True, is_moderator=True)

        client.force_login(mod)
        resp = client.post(reverse("moderation_user_toggle_moderator", args=[user.pk]))
        assert resp.status_code == 302
        user.refresh_from_db()
        assert user.is_moderator is False

    def test_cannot_toggle_self(self, client):
        mod = _moderator()
        client.force_login(mod)
        client.post(reverse("moderation_user_toggle_moderator", args=[mod.pk]))
        # Should redirect with error, not actually change
        mod.refresh_from_db()
        assert mod.is_moderator is True

    def test_cannot_toggle_self_htmx_returns_422(self, client):
        mod = _moderator()
        client.force_login(mod)
        resp = client.post(
            reverse("moderation_user_toggle_moderator", args=[mod.pk]),
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 422
