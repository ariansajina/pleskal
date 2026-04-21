"""Tests for the backfill_geocoding management command."""

import io
from unittest.mock import patch

import pytest
from django.core.management import call_command

from events.models import Event

from .factories import EventFactory


@pytest.mark.django_db
class TestBackfillGeocodingCommand:
    def test_resolves_missing_coords(self):
        event = EventFactory.create(
            venue_name="Dansehallerne", latitude=None, longitude=None
        )
        buf = io.StringIO()
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(55.6761, 12.5683),
        ):
            call_command("backfill_geocoding", stdout=buf)
        event.refresh_from_db()
        assert event.latitude == pytest.approx(55.6761)
        assert event.longitude == pytest.approx(12.5683)
        assert "resolved 1" in buf.getvalue()

    def test_dry_run_does_not_persist(self):
        event = EventFactory.create(
            venue_name="Dansehallerne", latitude=None, longitude=None
        )
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(55.6761, 12.5683),
        ):
            call_command("backfill_geocoding", "--dry-run", stdout=io.StringIO())
        event.refresh_from_db()
        assert event.latitude is None
        assert event.longitude is None

    def test_skips_events_that_already_have_coords(self):
        EventFactory.create(
            venue_name="HAUT",
            latitude=55.0,
            longitude=12.0,
        )
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(99.0, 99.0),
        ) as mock_geocode:
            call_command("backfill_geocoding", stdout=io.StringIO())
        mock_geocode.assert_not_called()

    def test_limit_caps_number_processed(self):
        EventFactory.create_batch(3, venue_name="HAUT", latitude=None, longitude=None)
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=(55.0, 12.0),
        ) as mock_geocode:
            call_command("backfill_geocoding", "--limit", "2", stdout=io.StringIO())
        assert mock_geocode.call_count == 2
        assert Event.objects.filter(latitude__isnull=False).count() == 2

    def test_miss_is_reported_and_coords_stay_null(self):
        event = EventFactory.create(venue_name="Nowhere", latitude=None)
        buf = io.StringIO()
        with patch(
            "events.management.commands.backfill_geocoding.geocode",
            return_value=None,
        ):
            call_command("backfill_geocoding", stdout=buf)
        event.refresh_from_db()
        assert event.latitude is None
        assert "missed 1" in buf.getvalue()
