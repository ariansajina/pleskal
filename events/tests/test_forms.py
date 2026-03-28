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
        future = timezone.localtime(timezone.now() + timezone.timedelta(days=7))
        return future.date(), future.replace(minute=0, second=0, microsecond=0).time()

    def test_duplicate_title_and_start_datetime_is_invalid(self):
        date, start_time = self._future_date_and_time()
        start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
        EventFactory.create(title="Salsa Night", start_datetime=start_dt)

        form = EventForm(
            data=make_form_data("Salsa Night", date, start_time), creation=True
        )
        assert not form.is_valid()
        assert any(
            "already exists at the same date and time" in e
            for e in form.non_field_errors()
        )

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
