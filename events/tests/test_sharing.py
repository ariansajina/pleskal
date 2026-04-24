"""Tests for events.sharing — calendar deep-link URL builders."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from events.sharing import (
    apple_calendar_url,
    google_calendar_url,
    outlook_calendar_url,
)
from events.tests.factories import EventFactory


@pytest.mark.django_db
class TestGoogleCalendarURL:
    def test_has_google_calendar_host_and_action(self):
        event = EventFactory.build(
            title="Salsa Night",
            start_datetime=datetime(2026, 6, 15, 18, 30, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 21, 0, tzinfo=UTC),
            venue_name="Dansehallerne",
        )
        parsed = urlparse(google_calendar_url(event))
        assert parsed.netloc == "calendar.google.com"
        assert parsed.path == "/calendar/render"
        qs = parse_qs(parsed.query)
        assert qs["action"] == ["TEMPLATE"]

    def test_encodes_title_and_location(self):
        event = EventFactory.build(
            title="Tango & Swing",
            start_datetime=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 20, 0, tzinfo=UTC),
            venue_name="Dansehallerne",
            venue_address="Pasteursvej 20, 1778 Copenhagen",
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["text"] == ["Tango & Swing"]
        assert qs["location"] == ["Dansehallerne, Pasteursvej 20, 1778 Copenhagen"]

    def test_dates_are_utc_basic_format(self):
        event = EventFactory.build(
            start_datetime=datetime(2026, 6, 15, 18, 30, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 21, 45, tzinfo=UTC),
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["dates"] == ["20260615T183000Z/20260615T214500Z"]

    def test_converts_copenhagen_summer_time_to_utc(self):
        """CEST (UTC+2) in July — 20:00 local should become 18:00 UTC."""
        cph = ZoneInfo("Europe/Copenhagen")
        event = EventFactory.build(
            start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=cph),
            end_datetime=datetime(2026, 7, 15, 22, 0, tzinfo=cph),
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["dates"] == ["20260715T180000Z/20260715T200000Z"]

    def test_converts_copenhagen_winter_time_to_utc(self):
        """CET (UTC+1) in January — 20:00 local should become 19:00 UTC."""
        cph = ZoneInfo("Europe/Copenhagen")
        event = EventFactory.build(
            start_datetime=datetime(2026, 1, 15, 20, 0, tzinfo=cph),
            end_datetime=datetime(2026, 1, 15, 22, 0, tzinfo=cph),
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["dates"] == ["20260115T190000Z/20260115T210000Z"]

    def test_missing_end_datetime_uses_start(self):
        event = EventFactory.build(
            start_datetime=datetime(2026, 6, 15, 18, 30, tzinfo=UTC),
            end_datetime=None,
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["dates"] == ["20260615T183000Z/20260615T183000Z"]

    def test_markdown_in_description_is_stripped(self):
        event = EventFactory.build(
            description="Come to **our** [salsa](https://example.com) night!",
            start_datetime=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 20, 0, tzinfo=UTC),
        )
        qs = parse_qs(urlparse(google_calendar_url(event)).query)
        assert qs["details"] == ["Come to our salsa night!"]


@pytest.mark.django_db
class TestOutlookCalendarURL:
    def test_has_outlook_host_and_compose_path(self):
        event = EventFactory.build(
            start_datetime=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 20, 0, tzinfo=UTC),
        )
        parsed = urlparse(outlook_calendar_url(event))
        assert parsed.netloc == "outlook.live.com"
        assert parsed.path == "/calendar/0/deeplink/compose"
        qs = parse_qs(parsed.query)
        assert qs["path"] == ["/calendar/action/compose"]
        assert qs["rru"] == ["addevent"]

    def test_encodes_subject_body_and_location(self):
        event = EventFactory.build(
            title="Tango & Swing",
            description="Bring friends!",
            venue_name="Dansehallerne",
            venue_address="Pasteursvej 20",
            start_datetime=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 20, 0, tzinfo=UTC),
        )
        qs = parse_qs(urlparse(outlook_calendar_url(event)).query)
        assert qs["subject"] == ["Tango & Swing"]
        assert qs["body"] == ["Bring friends!"]
        assert qs["location"] == ["Dansehallerne, Pasteursvej 20"]

    def test_dates_are_utc_extended_iso(self):
        event = EventFactory.build(
            start_datetime=datetime(2026, 6, 15, 18, 30, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 21, 45, tzinfo=UTC),
        )
        qs = parse_qs(urlparse(outlook_calendar_url(event)).query)
        assert qs["startdt"] == ["2026-06-15T18:30:00Z"]
        assert qs["enddt"] == ["2026-06-15T21:45:00Z"]

    def test_converts_copenhagen_summer_time_to_utc(self):
        cph = ZoneInfo("Europe/Copenhagen")
        event = EventFactory.build(
            start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=cph),
            end_datetime=datetime(2026, 7, 15, 22, 0, tzinfo=cph),
        )
        qs = parse_qs(urlparse(outlook_calendar_url(event)).query)
        assert qs["startdt"] == ["2026-07-15T18:00:00Z"]
        assert qs["enddt"] == ["2026-07-15T20:00:00Z"]

    def test_missing_end_datetime_uses_start(self):
        event = EventFactory.build(
            start_datetime=datetime(2026, 6, 15, 18, 30, tzinfo=UTC),
            end_datetime=None,
        )
        qs = parse_qs(urlparse(outlook_calendar_url(event)).query)
        assert qs["enddt"] == ["2026-06-15T18:30:00Z"]

    def test_venue_without_address(self):
        event = EventFactory.build(
            venue_name="Dansehallerne",
            venue_address="",
            start_datetime=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            end_datetime=datetime(2026, 6, 15, 20, 0, tzinfo=UTC),
        )
        qs = parse_qs(urlparse(outlook_calendar_url(event)).query)
        assert qs["location"] == ["Dansehallerne"]


class TestAppleCalendarURL:
    def test_rewrites_https_to_webcal(self):
        assert (
            apple_calendar_url("https://pleskal.dk/events/abc/calendar.ics")
            == "webcal://pleskal.dk/events/abc/calendar.ics"
        )

    def test_rewrites_http_to_webcal(self):
        assert (
            apple_calendar_url("http://localhost:8000/events/abc/calendar.ics")
            == "webcal://localhost:8000/events/abc/calendar.ics"
        )

    def test_passes_through_other_schemes(self):
        assert apple_calendar_url("webcal://example.com/x.ics") == (
            "webcal://example.com/x.ics"
        )
