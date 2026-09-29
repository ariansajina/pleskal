import datetime

import pytest
from django.utils import timezone

from ..forms import EventForm
from .factories import EventFactory


def make_form_data(title, date, start_time, **overrides):
    data = {
        "title": title,
        "date": date.strftime("%Y-%m-%d"),
        "start_time": start_time.strftime("%H:%M"),
        "venue_name": "Dance Hall",
        "category": "social",
        "is_free": False,
        "is_wheelchair_accessible": False,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestEventFormUniqueness:
    def _future_date_and_time(self):
        # Fixed time of day: tests add hours to it, which must not wrap past midnight.
        future = timezone.localtime(timezone.now() + timezone.timedelta(days=7))
        return future.date(), datetime.time(18, 0)

    def test_duplicate_title_and_start_datetime_is_invalid(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        EventFactory.create(title="Salsa Night", start_datetime=start_dt)

        form = EventForm(
            data=make_form_data("Salsa Night", date, start_time), creation=True
        )
        assert not form.is_valid()
        assert any("already exists at this venue" in e for e in form.non_field_errors())

    def test_same_title_different_time_is_valid(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        EventFactory.create(title="Salsa Night", start_datetime=start_dt)

        other_time = (
            datetime.datetime.combine(date, start_time) + datetime.timedelta(hours=2)
        ).time()
        form = EventForm(
            data=make_form_data("Salsa Night", date, other_time), creation=True
        )
        assert form.is_valid(), form.errors

    def test_same_time_different_title_is_valid(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        EventFactory.create(title="Salsa Night", start_datetime=start_dt)

        form = EventForm(
            data=make_form_data("Bachata Night", date, start_time), creation=True
        )
        assert form.is_valid(), form.errors

    def test_same_title_and_time_at_another_venue_is_valid(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        EventFactory.create(
            title="Open Practice", start_datetime=start_dt, venue_name="Studio A"
        )

        form = EventForm(
            data=make_form_data(
                "Open Practice", date, start_time, venue_name="Studio B"
            ),
            creation=True,
        )
        assert form.is_valid(), form.errors

    def test_editing_own_event_does_not_trigger_duplicate_error(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        event = EventFactory.create(title="Salsa Night", start_datetime=start_dt)

        form = EventForm(
            data=make_form_data("Salsa Night", date, start_time),
            instance=event,
            creation=False,
        )
        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestEventFormMultiDay:
    def _future_date_and_time(self):
        # Fixed time of day: tests add hours to it, which must not wrap past midnight.
        future = timezone.localtime(timezone.now() + timezone.timedelta(days=7))
        return future.date(), datetime.time(18, 0)

    def test_end_date_defaults_to_start_date_when_blank(self):
        date, start_time = self._future_date_and_time()
        end_time = (
            datetime.datetime.combine(date, start_time) + datetime.timedelta(hours=2)
        ).time()
        form = EventForm(
            data=make_form_data(
                "Festival", date, start_time, end_time=end_time.strftime("%H:%M")
            ),
            creation=True,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["end_datetime"].date() == date

    def test_multi_day_end_date_after_start_is_valid(self):
        date, start_time = self._future_date_and_time()
        end_date = date + datetime.timedelta(days=2)
        form = EventForm(
            data=make_form_data(
                "Festival",
                date,
                start_time,
                end_time="18:00",
                end_date=end_date.strftime("%Y-%m-%d"),
            ),
            creation=True,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["end_datetime"].date() == end_date

    def test_end_date_before_start_date_is_invalid(self):
        date, start_time = self._future_date_and_time()
        end_date = date - datetime.timedelta(days=1)
        form = EventForm(
            data=make_form_data(
                "Festival",
                date,
                start_time,
                end_time="18:00",
                end_date=end_date.strftime("%Y-%m-%d"),
            ),
            creation=True,
        )
        assert not form.is_valid()
        assert "end_time" in form.errors

    def test_editing_multi_day_event_prefills_end_date(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        end_dt = start_dt + datetime.timedelta(days=3)
        event = EventFactory.create(
            title="Festival", start_datetime=start_dt, end_datetime=end_dt
        )
        form = EventForm(instance=event, creation=False)
        assert form.initial["end_date"] == end_dt.date()


@pytest.mark.django_db
class TestEndTimeError:
    def _form(self, **overrides):
        day = timezone.localdate() + datetime.timedelta(days=7)
        data = make_form_data(
            "Night Party", day, datetime.time(22, 0), end_time="03:00"
        )
        data.update(overrides)
        return EventForm(data=data, creation=True)

    def test_end_before_start_without_end_date_points_to_checkbox(self):
        form = self._form()
        assert not form.is_valid()
        assert "Ends on a later day" in form.errors["end_time"][0]

    def test_end_on_the_next_day_is_valid(self):
        day = timezone.localdate() + datetime.timedelta(days=8)
        form = self._form(end_date=day.strftime("%Y-%m-%d"))
        assert form.is_valid(), form.errors

    def test_end_before_start_with_end_date_keeps_plain_message(self):
        day = timezone.localdate() + datetime.timedelta(days=7)
        form = self._form(end_date=day.strftime("%Y-%m-%d"))
        assert form.errors["end_time"] == ["End time must be after start time."]
