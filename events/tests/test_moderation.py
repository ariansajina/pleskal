import pytest
from django.utils import timezone

from accounts.tests.factories import UserFactory

from ..models import EventStatus
from .factories import EventFactory


@pytest.mark.django_db
class TestModerationFlow:
    def test_unapproved_user_event_is_pending(self):
        user = UserFactory.create(is_approved=False)
        event = EventFactory.create(submitted_by=user)
        assert event.status == EventStatus.PENDING

    def test_approved_user_event_is_auto_approved(self):
        user = UserFactory.create(is_approved=True)
        event = EventFactory.create(submitted_by=user)
        assert event.status == EventStatus.APPROVED

    def test_approve_event_sets_status(self):
        event = EventFactory.create()
        event.approve()
        event.refresh_from_db()
        assert event.status == EventStatus.APPROVED

    def test_approve_event_approves_user(self):
        user = UserFactory.create(is_approved=False)
        event = EventFactory.create(submitted_by=user)
        event.approve()
        user.refresh_from_db()
        assert user.is_approved is True

    def test_approve_clears_rejection_note(self):
        event = EventFactory.create()
        event.reject("Bad content")
        event.approve()
        event.refresh_from_db()
        assert event.rejection_note == ""

    def test_full_moderation_cycle(self):
        """Unapproved user → pending → approve → user approved → next auto."""
        user = UserFactory.create(is_approved=False)

        # First event: pending
        e1 = EventFactory.create(submitted_by=user)
        assert e1.status == EventStatus.PENDING

        # Moderator approves
        e1.approve()
        user.refresh_from_db()
        assert user.is_approved is True

        # Second event: auto-approved
        e2 = EventFactory.create(submitted_by=user)
        assert e2.status == EventStatus.APPROVED


@pytest.mark.django_db
class TestRejectEvent:
    def test_reject_sets_status_and_note(self):
        event = EventFactory.create()
        event.reject("Content is inappropriate")
        event.refresh_from_db()
        assert event.status == EventStatus.REJECTED
        assert event.rejection_note == "Content is inappropriate"

    def test_reject_without_note_raises(self):
        event = EventFactory.create()
        with pytest.raises(ValueError, match="Rejection note is required"):
            event.reject("")

    def test_reject_whitespace_note_raises(self):
        event = EventFactory.create()
        with pytest.raises(ValueError, match="Rejection note is required"):
            event.reject("   ")


@pytest.mark.django_db
class TestResubmitEvent:
    def test_resubmit_sets_pending_and_clears_note(self):
        event = EventFactory.create()
        event.reject("Fix this")
        event.resubmit()
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING
        assert event.rejection_note == ""

    def test_resubmit_non_rejected_raises(self):
        event = EventFactory.create()
        with pytest.raises(ValueError, match="Only rejected events"):
            event.resubmit()

    def test_edit_rejected_event_resubmits(self):
        """Simulates editing a rejected event and resubmitting."""
        event = EventFactory.create()
        event.reject("Needs changes")
        event.title = "Updated Title"
        event.resubmit()
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING

    def test_scraper_event_no_submitted_by(self):
        """Events without a user (scraper) should default to pending."""
        event = EventFactory.create(submitted_by=None)
        assert event.status == EventStatus.PENDING


@pytest.mark.django_db
class TestAutoApprovalEdgeCases:
    def test_already_approved_user_stays_approved(self):
        user = UserFactory.create(is_approved=True)
        event = EventFactory.create(submitted_by=user)
        event.approve()
        user.refresh_from_db()
        assert user.is_approved is True

    def test_unapproved_user_set_back(self):
        """If user is un-approved, next event goes to pending."""
        user = UserFactory.create(is_approved=True)
        e1 = EventFactory.create(submitted_by=user)
        assert e1.status == EventStatus.APPROVED

        user.is_approved = False
        user.save()

        e2 = EventFactory.create(submitted_by=user)
        assert e2.status == EventStatus.PENDING

    def test_status_not_overridden_on_update(self):
        """Saving an existing event doesn't re-trigger auto-approval."""
        user = UserFactory.create(is_approved=False)
        event = EventFactory.create(submitted_by=user)
        assert event.status == EventStatus.PENDING

        # Approve the user separately
        user.is_approved = True
        user.save()

        # Updating the event should NOT change its status
        event.title = "Updated"
        event.save()
        event.refresh_from_db()
        assert event.status == EventStatus.PENDING

    def test_event_with_future_start(self):
        """Auto-approval works with future start datetime."""
        user = UserFactory.create(is_approved=True)
        event = EventFactory.create(
            submitted_by=user,
            start_datetime=timezone.now() + timezone.timedelta(days=30),
        )
        assert event.status == EventStatus.APPROVED
