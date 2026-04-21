import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from .factories import EventFactory


@pytest.mark.django_db
class TestEventModel:
    def test_uuid_primary_key(self):
        event = EventFactory.create()
        assert isinstance(event.pk, uuid.UUID)

    def test_str_returns_title(self):
        event = EventFactory.create(title="Summer Jam")
        assert str(event) == "Summer Jam"


@pytest.mark.django_db
class TestSlugGeneration:
    def test_slug_auto_generated(self):
        event = EventFactory.create(title="My Cool Event")
        assert event.slug == "my-cool-event"

    def test_slug_collision_appends_suffix(self):
        e1 = EventFactory.create(title="Same Title")
        e2 = EventFactory.create(title="Same Title")
        assert e1.slug == "same-title"
        assert e2.slug != e1.slug
        assert str(e2.slug).startswith("same-title-")

    def test_slug_immutable_on_save(self):
        event = EventFactory.create(title="Original Title")
        original_slug = event.slug
        event.title = "Changed Title"  # ty: ignore[invalid-assignment]
        event.save()
        assert event.slug == original_slug

    def test_empty_title_fallback_slug(self):
        event = EventFactory.create(title="---")  # slugify produces empty string
        assert event.slug == "event"


@pytest.mark.django_db
class TestEventValidation:
    def test_past_start_datetime_rejected_on_creation(self):
        event = EventFactory.build(
            start_datetime=timezone.now() - timezone.timedelta(hours=1)
        )
        with pytest.raises(ValidationError) as exc_info:
            event.full_clean()
        assert "start_datetime" in exc_info.value.message_dict

    def test_past_start_datetime_allowed_on_edit(self):
        event = EventFactory.create(
            start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        # Simulate the event's start_datetime being in the past now
        event.start_datetime = timezone.now() - timezone.timedelta(hours=1)
        # Should not raise - past date check only on creation
        event.full_clean()

    def test_start_more_than_one_year_future_rejected(self):
        event = EventFactory.build(
            start_datetime=timezone.now() + timezone.timedelta(days=400)
        )
        with pytest.raises(ValidationError) as exc_info:
            event.full_clean()
        assert "start_datetime" in exc_info.value.message_dict

    def test_end_before_start_rejected(self):
        start = timezone.now() + timezone.timedelta(days=7)
        event = EventFactory.build(
            start_datetime=start,
            end_datetime=start - timezone.timedelta(hours=1),
        )
        with pytest.raises(ValidationError) as exc_info:
            event.full_clean()
        assert "end_datetime" in exc_info.value.message_dict

    def test_end_after_start_accepted(self):
        start = timezone.now() + timezone.timedelta(days=7)
        event = EventFactory.build(
            start_datetime=start,
            end_datetime=start + timezone.timedelta(hours=2),
        )
        event.clean()  # Should not raise

    def test_title_too_short_rejected(self):
        event = EventFactory.build(title="Hi")
        with pytest.raises(ValidationError) as exc_info:
            event.full_clean()
        assert "title" in exc_info.value.message_dict

    def test_submitted_by_set_null_on_delete(self):
        event = EventFactory.create()
        user = event.submitted_by
        user.delete()  # type: ignore
        event.refresh_from_db()
        assert event.submitted_by is None
