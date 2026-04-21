import uuid
from unittest.mock import patch

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
        event.title = "Changed Title"
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


@pytest.mark.django_db
class TestGeocodingOnSave:
    """Event.save() geocodes the venue when the address changes (or on insert)."""

    def test_geocoding_disabled_skips_call(self, settings):
        settings.GEOCODING_ENABLED = False
        with patch("events.geocoding.geocode") as mock_geocode:
            event = EventFactory.create(venue_name="Dansehallerne")
        mock_geocode.assert_not_called()
        assert event.latitude is None
        assert event.longitude is None

    def test_insert_triggers_geocode_and_stores_coords(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch(
            "events.geocoding.geocode", return_value=(55.6761, 12.5683)
        ) as mock_geocode:
            event = EventFactory.create(
                venue_name="Dansehallerne", venue_address="Pasteursvej 20"
            )
        mock_geocode.assert_called_once()
        query = mock_geocode.call_args[0][0]
        assert "Dansehallerne" in query
        assert "Pasteursvej 20" in query
        assert "Copenhagen" in query
        assert event.latitude == pytest.approx(55.6761)
        assert event.longitude == pytest.approx(12.5683)

    def test_insert_without_address_uses_venue_only_in_query(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch(
            "events.geocoding.geocode", return_value=(55.0, 12.0)
        ) as mock_geocode:
            EventFactory.create(venue_name="HAUT", venue_address="")
        query = mock_geocode.call_args[0][0]
        assert query.startswith("HAUT,")
        assert "Copenhagen" in query

    def test_update_without_address_change_does_not_regeocode(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch(
            "events.geocoding.geocode", return_value=(55.0, 12.0)
        ) as mock_geocode:
            event = EventFactory.create(venue_name="HAUT", venue_address="Skindergade")
            assert mock_geocode.call_count == 1
            event.title = "Renamed title"  # ty: ignore[invalid-assignment]
            event.save()
        assert mock_geocode.call_count == 1

    def test_update_with_venue_address_change_regeocodes(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch(
            "events.geocoding.geocode", return_value=(55.0, 12.0)
        ) as mock_geocode:
            event = EventFactory.create(venue_name="HAUT", venue_address="Skindergade")
            mock_geocode.return_value = (56.1, 13.2)
            event.venue_address = "Nørrebrogade 1"  # ty: ignore[invalid-assignment]
            event.save()
        assert mock_geocode.call_count == 2
        assert event.latitude == pytest.approx(56.1)
        assert event.longitude == pytest.approx(13.2)

    def test_update_with_venue_name_change_regeocodes(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch(
            "events.geocoding.geocode", return_value=(55.0, 12.0)
        ) as mock_geocode:
            event = EventFactory.create(venue_name="HAUT")
            event.venue_name = "Dansehallerne"  # ty: ignore[invalid-assignment]
            event.save()
        assert mock_geocode.call_count == 2

    def test_geocode_returning_none_leaves_coords_unset(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch("events.geocoding.geocode", return_value=None):
            event = EventFactory.create(venue_name="Unresolvable Place XYZ")
        assert event.latitude is None
        assert event.longitude is None

    def test_geocode_raising_does_not_break_save(self, settings):
        settings.GEOCODING_ENABLED = True
        with patch("events.geocoding.geocode", side_effect=RuntimeError("boom")):
            event = EventFactory.create(venue_name="Whatever")
        assert event.pk is not None
        assert event.latitude is None

    def test_has_map_location_property(self):
        event = EventFactory.build(latitude=None, longitude=None)
        assert event.has_map_location is False
        event.latitude = 55.0  # ty: ignore[invalid-assignment]
        assert event.has_map_location is False
        event.longitude = 12.0  # ty: ignore[invalid-assignment]
        assert event.has_map_location is True
