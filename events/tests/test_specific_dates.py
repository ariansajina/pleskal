"""Tests for events on specific dates (a series without a rule, each date with
its own times) and for showing the end date of events that end on a later
day."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory

from ..forms import EventForm
from ..models import Event, EventSeries
from .factories import EventFactory
from .test_series import _create_data, _edit_data, _future_weekday, _local
from .test_series import series as series  # noqa: F401 (fixture)

DAY = datetime.timedelta(days=1)


def _aware(day, hour, minute=0):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, minute))
    )


def _dates(rows, initial=0):
    """Formset data for the specific-dates rows (day, start, end)."""
    data = {
        "dates-TOTAL_FORMS": str(len(rows)),
        "dates-INITIAL_FORMS": str(initial),
        "dates-MIN_NUM_FORMS": "0",
        "dates-MAX_NUM_FORMS": "1000",
    }
    for i, (day, start, end) in enumerate(rows):
        data[f"dates-{i}-date"] = day.isoformat() if day else ""
        data[f"dates-{i}-start_time"] = start
        data[f"dates-{i}-end_time"] = end
    return data


def _weekend_data(friday, rows=None, **overrides):
    """The weekend intensive: Fri 17–19, Sat 9:30–21, Sun 9:30–18."""
    if rows is None:
        rows = [(friday + DAY, "09:30", "21:00"), (friday + 2 * DAY, "09:30", "18:00")]
    data = _create_data(
        friday,
        title="Weekend intensive",
        start_time="17:00",
        end_time="19:00",
        repeat="dates",
        repeat_ends=None,
        repeat_count=None,
        **overrides,
    )
    data.update(_dates(rows))
    return data


def _spans(events):
    return [
        (
            _local(e.start_datetime).replace(tzinfo=None),
            _local(e.end_datetime).replace(tzinfo=None) if e.end_datetime else None,
        )
        for e in events
    ]


def _at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute))


@pytest.fixture
def owner(client):
    user = UserFactory.create()
    client.force_login(user)
    return user


@pytest.fixture
def friday():
    return _future_weekday(weekday=4)


@pytest.fixture
def weekend(client, owner, friday):
    resp = client.post(reverse("event_create"), _weekend_data(friday))
    assert resp.status_code == 302, resp.context and resp.context["form"].errors
    return list(Event.objects.order_by("start_datetime"))


@pytest.mark.django_db
class TestCreate:
    def test_each_date_keeps_its_own_times(self, client, owner, friday):
        resp = client.post(reverse("event_create"), _weekend_data(friday), follow=True)
        events = list(Event.objects.order_by("start_datetime"))
        assert _spans(events) == [
            (_at(friday, 17), _at(friday, 19)),
            (_at(friday + DAY, 9, 30), _at(friday + DAY, 21)),
            (_at(friday + 2 * DAY, 9, 30), _at(friday + 2 * DAY, 18)),
        ]
        series = EventSeries.objects.get()
        assert series.rrule == ""
        assert series.pattern is None
        assert series.dtstart == events[0].start_datetime
        assert {e.series_id for e in events} == {series.pk}
        assert {e.title for e in events} == {"Weekend intensive"}
        assert "3 dates were created." in resp.content.decode()

    def test_blank_rows_are_ignored(self, client, owner, friday):
        rows = [(friday + DAY, "10:00", ""), (None, "", ""), (None, "", "")]
        resp = client.post(reverse("event_create"), _weekend_data(friday, rows=rows))
        assert resp.status_code == 302
        events = list(Event.objects.order_by("start_datetime"))
        assert _spans(events)[1] == (_at(friday + DAY, 10), None)
        assert len(events) == 2

    def test_a_date_before_the_main_one_comes_first(self, client, owner, friday):
        rows = [(friday - DAY, "18:00", "20:00")]
        resp = client.post(reverse("event_create"), _weekend_data(friday, rows=rows))
        first = Event.objects.order_by("start_datetime").first()
        assert resp["Location"] == reverse("event_detail", args=[first.slug])
        assert _local(first.start_datetime).date() == friday - DAY
        assert EventSeries.objects.get().dtstart == first.start_datetime

    def test_end_before_start_ends_the_next_day(self, client, owner, friday):
        rows = [(friday + DAY, "22:00", "02:00")]
        client.post(reverse("event_create"), _weekend_data(friday, rows=rows))
        last = Event.objects.order_by("start_datetime").last()
        assert _spans([last]) == [(_at(friday + DAY, 22), _at(friday + 2 * DAY, 2))]

    def test_needs_another_date(self, client, owner, friday):
        rows = [(None, "", "")]
        resp = client.post(reverse("event_create"), _weekend_data(friday, rows=rows))
        assert resp.status_code == 200
        assert "Add at least one more date" in str(resp.context["form"].errors)
        assert not Event.objects.exists()

    @pytest.mark.parametrize(
        ("row", "error"),
        [
            ((1, "", "12:00"), "Enter the start time."),
            ((None, "10:00", ""), "Date: Enter the date."),
            ((-30, "10:00", ""), "This date is in the past."),
            ((400, "10:00", ""), "at most one year ahead"),
            ((1, "10:00", "10:00"), "The end time must differ from the start."),
            ((1, "25:00", ""), "Enter a valid time."),
        ],
    )
    def test_invalid_rows_are_errors(self, client, owner, friday, row, error):
        offset, start, end = row
        day = friday + offset * DAY if offset is not None else None
        resp = client.post(
            reverse("event_create"),
            _weekend_data(friday, rows=[(day, start, end)]),
        )
        assert resp.status_code == 200
        assert error in str(resp.context["form"].errors["repeat"])
        assert not Event.objects.exists()

    def test_row_error_names_the_date(self, client, owner, friday):
        resp = client.post(
            reverse("event_create"),
            _weekend_data(friday, rows=[(friday + DAY, "", "")]),
        )
        label = (friday + DAY).strftime("%a %-d %b")
        assert (
            f"{label}: Enter the start time." in resp.context["form"].errors["repeat"]
        )

    def test_same_date_twice_is_a_conflict(self, client, owner, friday):
        rows = [(friday, "17:00", "19:00")]
        resp = client.post(reverse("event_create"), _weekend_data(friday, rows=rows))
        assert "already exists at this venue" in str(resp.context["form"].errors)
        assert not Event.objects.exists()

    def test_over_the_account_limit_is_rejected_not_cut(
        self, client, owner, friday, settings
    ):
        settings.MAX_UPCOMING_EVENTS_PER_USER = 2
        resp = client.post(reverse("event_create"), _weekend_data(friday))
        assert "room for 2 more dates (3 listed)" in str(resp.context["form"].errors)
        assert not Event.objects.exists()

    def test_over_the_series_limit_is_rejected(self, client, owner, friday, settings):
        settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES = 2
        resp = client.post(reverse("event_create"), _weekend_data(friday))
        assert "at most 2 upcoming dates (3 listed)" in str(resp.context["form"].errors)

    def test_draft(self, client, owner, friday):
        client.post(
            reverse("event_create"), _weekend_data(friday, submit_action="draft")
        )
        assert set(Event.objects.values_list("is_draft", flat=True)) == {True}

    def test_rows_are_ignored_for_other_repeat_options(self, client, owner, friday):
        data = _create_data(friday, repeat="", repeat_ends=None, repeat_count=None)
        data.update(_dates([(None, "garbage", "")]))
        resp = client.post(reverse("event_create"), data)
        assert resp.status_code == 302
        assert Event.objects.count() == 1
        assert not EventSeries.objects.exists()

    def test_form_renders_the_option_and_rows(self, client, owner):
        content = client.get(reverse("event_create")).content.decode()
        assert '<option value="dates">On specific dates…</option>' in content
        assert 'name="dates-TOTAL_FORMS"' in content
        assert 'name="dates-0-date"' in content
        assert "data-date-template" in content
        assert 'name="dates-__prefix__-date"' in content


def _edit(client, event, rows, initial, **overrides):
    data = _edit_data(event, **overrides)
    data.update(_dates(rows, initial=initial))
    return client.post(reverse("event_edit", args=[event.slug]), data)


@pytest.mark.django_db
class TestEdit:
    def test_form_lists_the_other_upcoming_dates(self, client, weekend, friday):
        resp = client.get(reverse("event_edit", args=[weekend[0].slug]))
        form = resp.context["form"]
        assert form.initial["repeat"] == "dates"
        assert [f.initial for f in form.extra_dates.initial_forms] == [
            {"date": friday + DAY, "start_time": "09:30", "end_time": "21:00"},
            {"date": friday + 2 * DAY, "start_time": "09:30", "end_time": "18:00"},
        ]
        assert [value for value, _ in form.fields["scope"].choices] == ["this", "all"]

    def test_scraped_show_can_be_edited(self, client, owner):
        series = EventSeries.objects.create(
            source_key="x:https://example.com/show", dtstart=timezone.now()
        )
        day = _future_weekday()
        events = [
            EventFactory.create(
                submitted_by=owner,
                series=series,
                start_datetime=_aware(day + n * DAY, 20),
            )
            for n in range(2)
        ]
        resp = client.get(
            reverse("event_edit", args=[events[0].slug]) + "?scope=following"
        )
        assert resp.status_code == 200
        assert resp.context["form"]["scope"].value() == "this"

    def test_scope_all_moves_removes_and_adds_dates(self, client, weekend, friday):
        sat, sun = weekend[1], weekend[2]
        rows = [
            (friday + DAY, "10:00", "21:00"),  # Saturday starts later
            (None, "", ""),  # Sunday removed
            (friday + 7 * DAY, "17:00", "19:00"),  # a date the next week
        ]
        resp = _edit(client, weekend[0], rows, initial=2, scope="all")
        assert resp.status_code == 302, resp.context and resp.context["form"].errors
        events = list(Event.objects.order_by("start_datetime"))
        assert _spans(events) == [
            (_at(friday, 17), _at(friday, 19)),
            (_at(friday + DAY, 10), _at(friday + DAY, 21)),
            (_at(friday + 7 * DAY, 17), _at(friday + 7 * DAY, 19)),
        ]
        # Rows are reused, so the dates keep their URLs where possible.
        assert events[0].pk == weekend[0].pk
        assert {e.pk for e in events[1:]} == {sat.pk, sun.pk}
        assert EventSeries.objects.get().rrule == ""

    def test_unchanged_dates_keep_their_rows(self, client, weekend, friday):
        rows = [
            (friday + DAY, "09:30", "21:00"),
            (friday + 2 * DAY, "09:30", "18:00"),
        ]
        resp = _edit(client, weekend[0], rows, initial=2, scope="all", title="New")
        assert resp.status_code == 302
        events = list(Event.objects.order_by("start_datetime"))
        assert [e.pk for e in events] == [e.pk for e in weekend]
        assert _spans(events) == _spans(weekend)
        assert {e.title for e in events} == {"New"}

    def test_scope_this_edits_one_date(self, client, weekend, friday):
        rows = [(friday + 2 * DAY, "09:30", "18:00")]
        resp = _edit(
            client, weekend[1], rows, initial=1, scope="this", end_time="18:00"
        )
        assert resp.status_code == 302
        events = list(Event.objects.order_by("start_datetime"))
        assert _spans(events)[1] == (_at(friday + DAY, 9, 30), _at(friday + DAY, 18))
        assert _spans(events)[2] == _spans(weekend)[2]

    def test_single_event_gets_specific_dates(self, client, owner, friday):
        """The fix for an event entered as one block from Friday to Sunday."""
        event = EventFactory.create(
            submitted_by=owner,
            title="Weekend intensive",
            start_datetime=_aware(friday, 17),
            end_datetime=_aware(friday + 2 * DAY, 18),
        )
        rows = [
            (friday + DAY, "09:30", "21:00"),
            (friday + 2 * DAY, "09:30", "18:00"),
        ]
        resp = _edit(
            client,
            event,
            rows,
            initial=0,
            end_date="",
            end_time="19:00",
            repeat="dates",
        )
        assert resp.status_code == 302, resp.context and resp.context["form"].errors
        events = list(Event.objects.order_by("start_datetime"))
        assert events[0].pk == event.pk
        assert resp["Location"] == reverse("event_detail", args=[event.slug])
        assert _spans(events) == [
            (_at(friday, 17), _at(friday, 19)),
            (_at(friday + DAY, 9, 30), _at(friday + DAY, 21)),
            (_at(friday + 2 * DAY, 9, 30), _at(friday + 2 * DAY, 18)),
        ]
        assert EventSeries.objects.get().rrule == ""

    def test_rule_series_becomes_specific_dates(self, client, series):  # noqa: F811
        first = _local(series[0].start_datetime).date()
        rows = [(first + DAY, "10:00", "")]
        resp = _edit(client, series[0], rows, initial=0, scope="all", repeat="dates")
        assert resp.status_code == 302, resp.context and resp.context["form"].errors
        events = list(Event.objects.order_by("start_datetime"))
        assert len(events) == 2
        assert events[0].pk == series[0].pk
        assert EventSeries.objects.get().rrule == ""

    def test_rule_series_form_lists_its_dates(self, client, series):  # noqa: F811
        form = client.get(reverse("event_edit", args=[series[0].slug])).context["form"]
        assert len(form.extra_dates.initial_forms) == 5

    def test_scope_following_is_an_error(self, client, series):  # noqa: F811
        first = _local(series[2].start_datetime).date()
        resp = _edit(
            client,
            series[2],
            [(first + DAY, "10:00", "")],
            initial=0,
            scope="following",
            repeat="dates",
        )
        assert resp.status_code == 200
        assert "apply the changes to all events" in str(resp.context["form"].errors)
        assert Event.objects.count() == 6

    def test_removing_every_other_date_is_an_error(self, client, weekend, friday):
        rows = [(None, "", ""), (None, "", "")]
        resp = _edit(client, weekend[0], rows, initial=2, scope="all")
        assert "Add at least one more date" in str(resp.context["form"].errors)
        assert Event.objects.count() == 3

    def test_does_not_repeat_removes_the_other_dates(self, client, weekend, friday):
        rows = [(friday + DAY, "09:30", "21:00"), (friday + 2 * DAY, "09:30", "18:00")]
        resp = _edit(client, weekend[0], rows, initial=2, scope="all", repeat="")
        assert resp.status_code == 302
        assert list(Event.objects.all()) == [weekend[0]]
        assert not EventSeries.objects.exists()


@pytest.mark.django_db
class TestPreviewAndDisplay:
    def test_preview_lists_the_dates(self, client, owner, friday):
        resp = client.post(reverse("event_recurrence_preview"), _weekend_data(friday))
        assert b"3 dates" in resp.content

    def test_preview_shows_row_errors(self, client, owner, friday):
        resp = client.post(
            reverse("event_recurrence_preview"),
            _weekend_data(friday, rows=[(friday + DAY, "", "")]),
        )
        assert b"Enter the start time." in resp.content

    def test_detail_shows_the_date_range_and_edit_dates(self, client, weekend, friday):
        resp = client.get(reverse("event_detail", args=[weekend[1].slug]))
        content = resp.content.decode()
        assert "3 dates" in content
        assert content.count('class="date-tile') == 3
        assert "Edit dates" in content
        assert "Extend series" not in content

    def test_form_for_a_dates_series_has_no_crash_without_rows(self, owner, weekend):
        form = EventForm(
            data=_edit_data(weekend[0], scope="all"),
            instance=weekend[0],
            creation=False,
            user=owner,
        )
        assert not form.is_valid()
        assert "repeat" in form.errors


@pytest.mark.django_db
class TestEndsOnLaterDay:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            ((0, 17), (0, 19), False),
            ((0, 17), None, False),
            ((0, 22), (1, 2), False),  # a night out
            ((0, 22), (1, 6), False),
            ((0, 22), (1, 7), True),
            ((0, 17), (2, 18), True),
            ((0, 1), (2, 1), True),
        ],
    )
    def test_property(self, start, end, expected):
        day = _future_weekday()
        event = EventFactory.build(
            start_datetime=_aware(day + start[0] * DAY, start[1]),
            end_datetime=_aware(day + end[0] * DAY, end[1]) if end else None,
        )
        assert event.ends_on_later_day is expected

    def test_detail_and_card_show_the_end_date(self, client, friday):
        event = EventFactory.create(
            title="Weekend block",
            start_datetime=_aware(friday, 17),
            end_datetime=_aware(friday + 2 * DAY, 18),
        )
        sunday = friday + 2 * DAY
        detail = client.get(reverse("event_detail", args=[event.slug])).content.decode()
        assert f"<strong>Sunday, {sunday.day} {sunday:%B}</strong>" in detail
        card = client.get(reverse("event_list")).content.decode()
        assert f"Sun {sunday.day} {sunday:%b} · 18:00" in card

    def test_same_day_end_shows_only_the_time(self, client, friday):
        event = EventFactory.create(
            start_datetime=_aware(friday, 17), end_datetime=_aware(friday, 19)
        )
        detail = client.get(reverse("event_detail", args=[event.slug])).content.decode()
        assert f"<strong>Friday, {friday.day} {friday:%B}</strong>" not in detail
        assert "<span>19:00</span>" in detail

    def test_date_only_event_shows_end_date(self, client, friday):
        event = EventFactory.create(
            start_datetime=_aware(friday, 0), end_datetime=_aware(friday + 2 * DAY, 0)
        )
        sunday = friday + 2 * DAY
        detail = client.get(reverse("event_detail", args=[event.slug])).content.decode()
        assert f"<strong>Sunday, {sunday.day} {sunday:%B}</strong>" in detail
        card = client.get(reverse("event_list")).content.decode()
        assert f"Sun {sunday.day} {sunday:%b}</span>" in card
