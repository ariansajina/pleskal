"""Tests for recurring events: creating, editing, extending, deleting and
displaying series (events/series.py and the views/forms that use it)."""

import calendar
import datetime
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory

from ..forms import EventForm
from ..models import Event, EventSeries
from .factories import EventFactory
from .test_views import _make_image_upload

WEEK = datetime.timedelta(weeks=1)


def _future_weekday(weekday=1, weeks=2) -> datetime.date:
    """A date *weeks* ahead on *weekday* (0 = Monday), in local time."""
    day = timezone.localdate() + datetime.timedelta(weeks=weeks)
    return day + datetime.timedelta(days=(weekday - day.weekday()) % 7)


def _create_data(day, **overrides):
    data = {
        "title": "Weekly Jam",
        "date": day.strftime("%Y-%m-%d"),
        "start_time": "19:00",
        "end_time": "21:00",
        "venue_name": "Dance Hall",
        "category": "social",
        "repeat": "weekly",
        "repeat_ends": "after",
        "repeat_count": "6",
        "submit_action": "publish",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def _edit_data(event, **overrides):
    """POST data for the edit form, unchanged from its initial values."""
    form = EventForm(instance=event, creation=False)
    data = {}
    for name, field in form.fields.items():
        value = form.initial.get(name, field.initial)
        if name == "image" or value is None or value is False:
            continue
        if value is True:
            value = "on"
        elif isinstance(value, list | tuple):
            value = [str(v) for v in value]
        elif isinstance(value, datetime.date):
            value = value.strftime("%Y-%m-%d")
        data[name] = value
    data["submit_action"] = "draft" if event.is_draft else "publish"
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def _local(dt):
    return timezone.localtime(dt)


def _occurrences(series_id=None, **filters):
    qs = Event.objects.filter(**filters)
    if series_id is not None:
        qs = qs.filter(series_id=series_id)
    return list(qs.order_by("start_datetime"))


@pytest.fixture
def owner(client):
    user = UserFactory.create()
    client.force_login(user)
    return user


@pytest.fixture
def series(client, owner):
    """Six weekly Tuesday 19:00–21:00 occurrences, starting two weeks ahead."""
    resp = client.post(reverse("event_create"), _create_data(_future_weekday()))
    assert resp.status_code == 302, resp.context and resp.context["form"].errors
    return _occurrences(submitted_by=owner)


@pytest.mark.django_db
class TestCreateSeries:
    def test_weekly_rule_creates_linked_occurrences(self, client, owner):
        day = _future_weekday()
        resp = client.post(reverse("event_create"), _create_data(day))
        events = _occurrences(submitted_by=owner)
        assert len(events) == 6
        assert resp["Location"] == reverse("event_detail", args=[events[0].slug])
        assert len({e.series_id for e in events}) == 1
        series = EventSeries.objects.get()
        assert (
            series.rrule
            == f"FREQ=WEEKLY;BYDAY={['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'][day.weekday()]}"
        )
        for i, event in enumerate(events):
            assert _local(event.start_datetime).date() == day + i * WEEK
            assert _local(event.start_datetime).time() == datetime.time(19)
            assert _local(event.end_datetime).time() == datetime.time(21)
            assert event.title == "Weekly Jam"
        assert len({e.slug for e in events}) == 6

    def test_no_repeat_creates_single_event(self, client, owner):
        client.post(reverse("event_create"), _create_data(_future_weekday(), repeat=""))
        event = Event.objects.get(submitted_by=owner)
        assert event.series is None
        assert not EventSeries.objects.exists()

    def test_never_ending_daily_rule_is_cut_at_series_limit(self, client, owner):
        resp = client.post(
            reverse("event_create"),
            _create_data(_future_weekday(), repeat="daily", repeat_ends="never"),
            follow=True,
        )
        assert Event.objects.filter(submitted_by=owner).count() == 110
        messages = [str(m) for m in resp.context["messages"]]
        assert any("at most 110 upcoming dates" in m for m in messages)

    def test_never_ending_weekly_rule_stops_one_year_ahead(self, client, owner):
        resp = client.post(
            reverse("event_create"),
            _create_data(_future_weekday(weeks=1), repeat_ends="never"),
            follow=True,
        )
        events = _occurrences(submitted_by=owner)
        assert 50 <= len(events) <= 52
        horizon = timezone.now() + datetime.timedelta(days=365)
        assert events[-1].start_datetime <= horizon
        messages = [str(m) for m in resp.context["messages"]]
        assert any("at most one year ahead" in m for m in messages)

    def test_account_limit_cuts_off_the_series(self, client, owner, settings):
        settings.MAX_UPCOMING_EVENTS_PER_USER = 8
        EventFactory.create_batch(5, submitted_by=owner)
        resp = client.post(
            reverse("event_create"),
            _create_data(_future_weekday(), title="Capped"),
            follow=True,
        )
        assert Event.objects.filter(title="Capped").count() == 3
        messages = [str(m) for m in resp.context["messages"]]
        assert any("at most 8 upcoming events" in m for m in messages)

    def test_system_account_is_not_capped_by_account_limit(self, client, settings):
        settings.MAX_UPCOMING_EVENTS_PER_USER = 2
        user = UserFactory.create(is_system_account=True)
        client.force_login(user)
        client.post(reverse("event_create"), _create_data(_future_weekday()))
        assert Event.objects.filter(submitted_by=user).count() == 6

    def test_conflicting_date_rejects_whole_series(self, client, owner):
        day = _future_weekday()
        clash = timezone.make_aware(
            datetime.datetime.combine(day + 2 * WEEK, datetime.time(19))
        )
        EventFactory.create(
            title="Weekly Jam", start_datetime=clash, venue_name="Dance Hall"
        )
        resp = client.post(reverse("event_create"), _create_data(day))
        assert resp.status_code == 200
        assert "already exists at this venue" in str(resp.context["form"].errors)
        assert not Event.objects.filter(submitted_by=owner).exists()
        assert not EventSeries.objects.exists()

    def test_end_date_before_start_is_an_error(self, client, owner):
        day = _future_weekday()
        resp = client.post(
            reverse("event_create"),
            _create_data(
                day,
                repeat_ends="on",
                repeat_until=(day - datetime.timedelta(days=1)).isoformat(),
            ),
        )
        assert resp.status_code == 200
        assert "repeat_until" in resp.context["form"].errors
        assert not Event.objects.exists()

    def test_missing_end_date_or_count_is_an_error(self, client, owner):
        day = _future_weekday()
        resp = client.post(reverse("event_create"), _create_data(day, repeat_ends="on"))
        assert "repeat_until" in resp.context["form"].errors
        resp = client.post(
            reverse("event_create"), _create_data(day, repeat_count=None)
        )
        assert "repeat_count" in resp.context["form"].errors

    def test_preset_not_fitting_the_date_is_an_error(self, client, owner):
        # The second week of a month is never the last of its weekday.
        day = _future_weekday()
        day = day.replace(day=8 + (day.weekday() - day.replace(day=8).weekday()) % 7)
        if day <= timezone.localdate():
            day = (day.replace(day=1) + datetime.timedelta(days=40)).replace(day=8)
        resp = client.post(
            reverse("event_create"), _create_data(day, repeat="monthly_last")
        )
        assert resp.status_code == 200
        assert "repeat" in resp.context["form"].errors

    def test_custom_rule_every_two_weeks_on_two_days(self, client, owner):
        day = _future_weekday(weekday=1)
        client.post(
            reverse("event_create"),
            _create_data(
                day,
                repeat="custom",
                repeat_interval="2",
                repeat_unit="week",
                repeat_weekdays=["1", "3"],
                repeat_count="4",
            ),
        )
        dates = [_local(e.start_datetime).date() for e in _occurrences()]
        thursday = datetime.timedelta(days=2)
        assert dates == [day, day + thursday, day + 2 * WEEK, day + 2 * WEEK + thursday]
        assert EventSeries.objects.get().rrule == "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH"

    def test_custom_monthly_on_nth_weekday(self, client, owner):
        day = _future_weekday()
        nth = (day.day - 1) // 7 + 1
        if nth > 4:
            day -= WEEK
            nth -= 1
        client.post(
            reverse("event_create"),
            _create_data(
                day,
                repeat="custom",
                repeat_unit="month",
                repeat_monthly="nth",
                repeat_count="3",
            ),
        )
        for event in _occurrences():
            local_day = _local(event.start_datetime).date()
            assert local_day.weekday() == day.weekday()
            assert (local_day.day - 1) // 7 + 1 == nth

    def test_keeps_local_time_across_daylight_saving_change(self, client, owner):
        # Find the next DST transition and start two weeks before it.
        day = timezone.localdate()
        noon = datetime.time(12)

        def offset(d):
            return timezone.make_aware(datetime.datetime.combine(d, noon)).utcoffset()

        while offset(day) == offset(day + datetime.timedelta(days=1)):
            day += datetime.timedelta(days=1)
        start = day - 2 * WEEK
        if start <= timezone.localdate():
            start += 4 * WEEK
            pytest.skip("DST transition too close to today")
        client.post(reverse("event_create"), _create_data(start))
        events = _occurrences()
        offsets = {
            e.start_datetime.astimezone(timezone.get_current_timezone()).utcoffset()
            for e in events
        }
        assert len(offsets) == 2
        for event in events:
            assert _local(event.start_datetime).time() == datetime.time(19)
            assert _local(event.end_datetime).time() == datetime.time(21)

    def test_draft_series(self, client, owner):
        client.post(
            reverse("event_create"),
            _create_data(_future_weekday(), submit_action="draft"),
        )
        assert all(e.is_draft for e in _occurrences())

    def test_image_is_shared_by_all_occurrences(
        self, client, owner, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        data = _create_data(_future_weekday(), repeat_count="3")
        data["image"] = _make_image_upload()
        client.post(reverse("event_create"), data)
        events = _occurrences()
        assert len(events) == 3
        assert events[0].image
        assert {e.image.name for e in events} == {events[0].image.name}
        assert len(list((tmp_path / "events").glob("*.webp"))) == 1

    def test_duplicate_can_repeat(self, client, owner):
        source = EventFactory.create(submitted_by=owner)
        resp = client.post(
            reverse("event_duplicate", args=[source.slug]),
            _create_data(_future_weekday(), title="Copied", repeat_count="3"),
        )
        assert resp.status_code == 302
        copies = _occurrences(title="Copied")
        assert len(copies) == 3
        assert copies[0].series_id is not None


@pytest.mark.django_db
class TestEditSeries:
    def _post(self, client, event, **overrides):
        return client.post(
            reverse("event_edit", args=[event.slug]), _edit_data(event, **overrides)
        )

    def test_edit_form_prefills_the_rule_and_last_date(self, client, series):
        resp = client.get(reverse("event_edit", args=[series[2].slug]))
        form = resp.context["form"]
        assert form.initial["repeat"] == "weekly"
        assert form.initial["repeat_ends"] == "on"
        assert form.initial["repeat_until"] == _local(series[-1].start_datetime).date()
        assert form["scope"].value() == "this"
        assert b"This event repeats" in resp.content

    def test_scope_query_parameter_preselects_scope(self, client, series):
        resp = client.get(reverse("event_edit", args=[series[0].slug]) + "?scope=all")
        assert resp.context["form"]["scope"].value() == "all"

    def test_scope_this_changes_one_occurrence(self, client, series):
        resp = self._post(client, series[2], title="Special", scope="this")
        assert resp.status_code == 302
        titles = [e.title for e in _occurrences(series[0].series_id)]
        assert titles == ["Weekly Jam"] * 2 + ["Special"] + ["Weekly Jam"] * 3

    def test_scope_this_ignores_repeat_fields(self, client, series):
        resp = self._post(
            client, series[2], title="Special", scope="this", repeat_interval="0"
        )
        assert resp.status_code == 302
        assert Event.objects.count() == 6

    def test_scope_following(self, client, series):
        self._post(client, series[2], title="Renamed", scope="following")
        titles = [e.title for e in _occurrences(series[0].series_id)]
        assert titles == ["Weekly Jam"] * 2 + ["Renamed"] * 4

    def test_scope_all_copies_only_changed_fields(self, client, series):
        self._post(client, series[3], description="Bring water", scope="this")
        series[1].refresh_from_db()
        self._post(client, series[1], title="Renamed", scope="all")
        events = _occurrences(series[0].series_id)
        assert [e.title for e in events] == ["Renamed"] * 6
        assert events[3].description == "Bring water"
        assert (
            events[0].description == "A great dance event."
            or events[0].description == ""
        )

    def test_time_change_moves_every_date_in_scope(self, client, series):
        self._post(client, series[1], start_time="20:00", end_time="22:30", scope="all")
        events = _occurrences(series[0].series_id)
        assert len(events) == 6
        for original, event in zip(series, events, strict=True):
            assert event.pk == original.pk
            assert (
                _local(event.start_datetime).date()
                == _local(original.start_datetime).date()
            )
            assert _local(event.start_datetime).time() == datetime.time(20)
            assert _local(event.end_datetime).time() == datetime.time(22, 30)

    def test_extend_series_with_later_end_date(self, client, series):
        self._post(client, series[1], title="Renamed", scope="all")
        series[0].refresh_from_db()
        last = _local(series[-1].start_datetime).date()
        until = (last + 3 * WEEK).isoformat()
        self._post(client, series[0], repeat_until=until, scope="all")
        events = _occurrences(series[0].series_id)
        assert len(events) == 9
        assert [e.pk for e in events[:6]] == [e.pk for e in series]
        assert _local(events[-1].start_datetime).date() == last + 3 * WEEK
        assert all(e.title == "Renamed" for e in events)
        assert all(_local(e.start_datetime).time() == datetime.time(19) for e in events)

    def test_extend_series_without_end_goes_to_the_limits(self, client, series):
        resp = self._post(client, series[0], repeat_ends="never", scope="all")
        assert resp.status_code == 302
        count = Event.objects.filter(series_id=series[0].series_id).count()
        assert 49 <= count <= 52

    def test_extend_counts_upcoming_dates_against_series_limit(
        self, client, series, settings
    ):
        settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES = 8
        self._post(client, series[0], repeat_ends="never", scope="all")
        assert Event.objects.filter(series_id=series[0].series_id).count() == 8

    def test_shorten_series(self, client, series):
        until = _local(series[3].start_datetime).date().isoformat()
        self._post(client, series[0], repeat_until=until, scope="all")
        remaining = _occurrences(series[0].series_id)
        assert [e.pk for e in remaining] == [e.pk for e in series[:4]]

    def test_end_date_before_edited_occurrence_is_an_error(self, client, series):
        until = _local(series[1].start_datetime).date().isoformat()
        resp = self._post(client, series[3], repeat_until=until, scope="all")
        assert resp.status_code == 200
        assert "repeat_until" in resp.context["form"].errors
        assert Event.objects.count() == 6

    def test_shortening_past_edited_occurrence_redirects_elsewhere(
        self, client, series
    ):
        resp = self._post(
            client, series[3], repeat_ends="after", repeat_count="2", scope="all"
        )
        assert resp.status_code == 302
        assert resp["Location"] == reverse("event_detail", args=[series[0].slug])
        assert not Event.objects.filter(pk=series[3].pk).exists()
        assert [e.pk for e in _occurrences()] == [series[0].pk, series[1].pk]

    def test_rule_change_following_splits_the_series(self, client, series):
        old_series = series[0].series_id
        new_day = _local(series[2].start_datetime).date() + datetime.timedelta(days=1)
        self._post(
            client,
            series[2],
            date=new_day.isoformat(),
            repeat="weekly",
            scope="following",
        )
        before = _occurrences(old_series)
        assert [e.pk for e in before] == [e.pk for e in series[:2]]
        moved = Event.objects.get(pk=series[2].pk)
        assert moved.series_id != old_series
        after = _occurrences(moved.series_id)
        assert len(after) == 4
        assert _local(after[0].start_datetime).date() == new_day
        assert all(
            _local(e.start_datetime).weekday() == new_day.weekday() for e in after
        )
        # Rows are reused, so existing links keep working.
        assert {e.pk for e in after} == {e.pk for e in series[2:]}

    def test_rule_change_all_shifts_the_whole_series(self, client, series):
        shift = datetime.timedelta(days=2)
        new_day = _local(series[3].start_datetime).date() + shift
        self._post(
            client, series[3], date=new_day.isoformat(), repeat="weekly", scope="all"
        )
        events = _occurrences(series[0].series_id)
        assert len(events) == 6
        for original, event in zip(series, events, strict=True):
            assert event.pk == original.pk
            assert (
                _local(event.start_datetime).date()
                == _local(original.start_datetime).date() + shift
            )
        assert EventSeries.objects.get().pattern.weekdays == (new_day.weekday(),)

    def test_rule_change_to_every_two_weeks(self, client, series):
        self._post(
            client,
            series[0],
            repeat="custom",
            repeat_interval="2",
            repeat_unit="week",
            repeat_weekdays=[str(_local(series[0].start_datetime).weekday())],
            repeat_ends="after",
            repeat_count="3",
            scope="all",
        )
        events = _occurrences(series[0].series_id)
        # Rows already on a remaining date keep it (and their links).
        assert [e.pk for e in events] == [series[0].pk, series[2].pk, series[4].pk]
        assert [e.start_datetime for e in events] == [
            series[0].start_datetime,
            series[2].start_datetime,
            series[4].start_datetime,
        ]

    def test_regeneration_leaves_past_occurrences_alone(self, client, series):
        past = timezone.now() - datetime.timedelta(days=3)
        Event.objects.filter(pk=series[0].pk).update(
            start_datetime=past, end_datetime=None
        )
        self._post(
            client,
            series[2],
            repeat="daily",
            repeat_ends="after",
            repeat_count="3",
            scope="all",
        )
        assert Event.objects.get(pk=series[0].pk).start_datetime == past
        assert Event.objects.filter(series_id=series[0].series_id).count() == 4

    def test_does_not_repeat_removes_other_upcoming_dates(self, client, series):
        self._post(client, series[2], repeat="", scope="following")
        remaining = _occurrences()
        assert [e.pk for e in remaining] == [e.pk for e in series[:3]]
        assert all(e.series_id == series[0].series_id for e in remaining)

    def test_does_not_repeat_for_all_ends_the_series(self, client, series):
        self._post(client, series[2], repeat="", scope="all")
        event = Event.objects.get()
        assert event.pk == series[2].pk
        assert event.series is None
        assert not EventSeries.objects.exists()

    def test_single_event_becomes_a_series(self, client, owner):
        start = timezone.make_aware(
            datetime.datetime.combine(_future_weekday(), datetime.time(18))
        )
        event = EventFactory.create(submitted_by=owner, start_datetime=start)
        resp = client.post(
            reverse("event_edit", args=[event.slug]),
            _edit_data(event, repeat="weekly", repeat_ends="after", repeat_count="3"),
        )
        assert resp.status_code == 302
        events = _occurrences(submitted_by=owner)
        assert len(events) == 3
        assert events[0].pk == event.pk
        assert events[0].series_id is not None
        assert {e.series_id for e in events} == {events[0].series_id}
        assert {e.title for e in events} == {event.title}

    def test_edit_single_event_without_repeat_stays_single(self, client, owner):
        event = EventFactory.create(submitted_by=owner)
        client.post(
            reverse("event_edit", args=[event.slug]), _edit_data(event, title="New")
        )
        event.refresh_from_db()
        assert event.title == "New"
        assert event.series is None

    def test_new_image_applies_to_scope(self, client, series, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        data = _edit_data(series[3], scope="following")
        data["image"] = _make_image_upload()
        client.post(reverse("event_edit", args=[series[3].slug]), data)
        events = _occurrences(series[0].series_id)
        assert not events[2].image
        names = {e.image.name for e in events[3:]}
        assert len(names) == 1
        assert names != {""}

    def test_publish_state_copied_only_when_changed(self, client, series):
        self._post(client, series[4], submit_action="draft", scope="this")
        self._post(client, series[1], title="Renamed", scope="all")
        assert [e.is_draft for e in _occurrences()] == [False] * 4 + [True, False]
        series[0].refresh_from_db()
        self._post(client, series[0], submit_action="draft", scope="all")
        assert all(e.is_draft for e in _occurrences())

    def test_edit_clashing_with_another_event_is_rejected(self, client, series):
        other_day = _local(series[4].start_datetime).date()
        EventFactory.create(
            title="Weekly Jam",
            venue_name="Dance Hall",
            start_datetime=timezone.make_aware(
                datetime.datetime.combine(other_day, datetime.time(20))
            ),
        )
        resp = self._post(client, series[1], start_time="20:00", scope="all")
        assert resp.status_code == 200
        assert "already exists at this venue" in str(resp.context["form"].errors)
        assert all(
            _local(e.start_datetime).time() == datetime.time(19)
            for e in _occurrences(series[0].series_id)
        )

    def test_other_users_cannot_edit(self, client, series):
        client.force_login(UserFactory.create())
        resp = self._post(client, series[1], title="Hijack", scope="all")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestDeleteAndToggle:
    def test_delete_confirmation_offers_scopes(self, client, series):
        resp = client.get(reverse("event_delete", args=[series[2].slug]))
        assert b"This and following dates (4)" in resp.content
        assert b"All dates, including past ones (6)" in resp.content

    @pytest.mark.parametrize(
        ("scope", "remaining"), [("this", 5), ("following", 2), ("all", 0), ("", 5)]
    )
    def test_delete_scopes(self, client, series, scope, remaining):
        client.post(reverse("event_delete", args=[series[2].slug]), {"scope": scope})
        assert Event.objects.count() == remaining
        assert EventSeries.objects.exists() == bool(remaining)

    def test_delete_single_event_ignores_scope(self, client, owner):
        event, other = EventFactory.create_batch(2, submitted_by=owner)
        client.post(reverse("event_delete", args=[event.slug]), {"scope": "all"})
        assert list(Event.objects.all()) == [other]

    def test_series_is_removed_with_its_last_occurrence(self, series):
        for event in series[:-1]:
            event.delete()
        assert EventSeries.objects.exists()
        series[-1].delete()
        assert not EventSeries.objects.exists()

    @pytest.mark.parametrize(
        ("scope", "drafts"),
        [
            ("this", [False, False, True, False, False, False]),
            ("following", [False, False, True, True, True, True]),
            ("all", [True] * 6),
        ],
    )
    def test_toggle_draft_scopes(self, client, series, scope, drafts):
        client.post(
            reverse("event_toggle_draft", args=[series[2].slug]), {"scope": scope}
        )
        assert [e.is_draft for e in _occurrences()] == drafts


@pytest.mark.django_db
class TestPreview:
    url = reverse("event_recurrence_preview")

    def test_lists_dates_for_a_new_event(self, client, owner):
        resp = client.post(self.url, _create_data(_future_weekday()))
        assert resp.status_code == 200
        assert b"6 dates" in resp.content

    def test_shows_cut_off_notice(self, client, owner):
        resp = client.post(
            self.url,
            _create_data(_future_weekday(), repeat="daily", repeat_ends="never"),
        )
        assert b"110 dates" in resp.content
        assert b"at most 110 upcoming dates" in resp.content

    def test_works_before_title_and_venue_are_filled_in(self, client, owner):
        resp = client.post(
            self.url, _create_data(_future_weekday(), title="", venue_name="")
        )
        assert b"6 dates" in resp.content

    def test_shows_errors(self, client, owner):
        resp = client.post(self.url, _create_data(_future_weekday(), repeat_ends="on"))
        assert b"Choose when the event stops repeating" in resp.content

    def test_empty_without_repeat(self, client, owner):
        resp = client.post(self.url, _create_data(_future_weekday(), repeat=""))
        assert resp.content.strip() == b""

    def test_edit_preview_counts_added_dates(self, client, series):
        last = _local(series[-1].start_datetime).date()
        data = _edit_data(
            series[0], scope="all", repeat_until=(last + 2 * WEEK).isoformat()
        )
        data["event"] = series[0].slug
        resp = client.post(self.url, data)
        assert b"8 dates" in resp.content
        assert b"2 added, 0 removed" in resp.content
        assert Event.objects.count() == 6

    def test_edit_preview_empty_for_scope_this(self, client, series):
        data = _edit_data(series[0], scope="this")
        data["event"] = series[0].slug
        resp = client.post(self.url, data)
        assert resp.content.strip() == b""

    def test_edit_preview_requires_owner(self, client, series):
        client.force_login(UserFactory.create())
        data = _edit_data(series[0], scope="all")
        data["event"] = series[0].slug
        assert client.post(self.url, data).status_code == 403

    def test_requires_login(self, client):
        resp = client.post(self.url, _create_data(_future_weekday()))
        assert resp.status_code == 302


@pytest.mark.django_db
class TestDisplay:
    def test_detail_shows_rule_and_other_dates(self, client, series):
        client.logout()
        resp = client.get(reverse("event_detail", args=[series[0].slug]))
        content = resp.content.decode()
        assert "Weekly on" in content
        last = _local(series[-1].start_datetime)
        assert f"until {last.day} {last:%B %Y}" in content
        assert "Other dates" in content
        for event in series[1:]:
            assert reverse("event_detail", args=[event.slug]) in content

    def test_other_dates_hide_drafts_from_the_public(self, client, series):
        Event.objects.filter(pk=series[3].pk).update(is_draft=True)
        resp = client.get(reverse("event_detail", args=[series[0].slug]))
        assert reverse("event_detail", args=[series[3].slug]) in resp.content.decode()
        client.logout()
        resp = client.get(reverse("event_detail", args=[series[0].slug]))
        assert (
            reverse("event_detail", args=[series[3].slug]) not in resp.content.decode()
        )

    def test_other_dates_are_capped(self, client, owner):
        client.post(
            reverse("event_create"), _create_data(_future_weekday(), repeat_count="12")
        )
        first = _occurrences()[0]
        resp = client.get(reverse("event_detail", args=[first.slug]))
        assert b"and 3 more" in resp.content

    def test_owner_sees_extend_and_scope_controls(self, client, series):
        resp = client.get(reverse("event_detail", args=[series[0].slug]))
        content = resp.content.decode()
        assert "Extend series" in content
        assert 'name="scope"' in content

    def test_single_event_has_no_series_block(self, client):
        event = EventFactory.create()
        resp = client.get(reverse("event_detail", args=[event.slug]))
        assert resp.context["series"] is None
        assert b"Other dates" not in resp.content

    def test_list_card_shows_repeat_badge(self, client, series):
        EventFactory.create(title="One-off")
        resp = client.get(reverse("event_list"))
        assert resp.content.count(b'class="badge badge--repeat"') == 6


@pytest.mark.django_db
def test_new_image_survives_removing_the_edited_occurrence(
    client, series, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    data = _edit_data(series[3], scope="all", repeat_ends="after", repeat_count="2")
    data["image"] = _make_image_upload()
    resp = client.post(reverse("event_edit", args=[series[3].slug]), data)
    assert resp.status_code == 302
    remaining = _occurrences()
    assert [e.pk for e in remaining] == [series[0].pk, series[1].pk]
    for event in remaining:
        assert event.image
        assert (tmp_path / event.image.name).exists()


def _last_weekday_date() -> datetime.date:
    """A future date in the last seven days of its month."""
    day = timezone.localdate() + datetime.timedelta(days=14)
    while day.day + 7 <= calendar.monthrange(day.year, day.month)[1]:
        day += datetime.timedelta(days=1)
    return day


@pytest.mark.django_db
class TestCustomRules:
    def _form(self, day, **overrides):
        data = _create_data(day, repeat="custom", **overrides)
        return EventForm(data=data, creation=True, user=UserFactory.create())

    def test_every_three_days(self):
        form = self._form(_future_weekday(), repeat_unit="day", repeat_interval="3")
        assert form.is_valid(), form.errors
        spans = form.cleaned_data["series_plan"].spans
        assert spans[1][0] - spans[0][0] == datetime.timedelta(days=3)

    def test_monthly_on_day_of_month(self):
        day = _future_weekday()
        form = self._form(day, repeat_unit="month", repeat_monthly="day")
        assert form.is_valid(), form.errors
        assert form.cleaned_data["pattern"].month_day == day.day

    def test_monthly_on_last_weekday(self):
        day = _last_weekday_date()
        form = self._form(day, repeat_unit="month", repeat_monthly="last")
        assert form.is_valid(), form.errors
        assert form.cleaned_data["pattern"].nth == -1

    def test_monthly_last_weekday_must_fit_the_date(self):
        day = _last_weekday_date() - datetime.timedelta(days=7)
        form = self._form(day, repeat_unit="month", repeat_monthly="last")
        assert not form.is_valid()
        assert "repeat_monthly" in form.errors
        # The option is rendered disabled for a date it doesn't fit.
        assert re.search(r'value="last"[^>]* disabled', str(form["repeat_monthly"]))

    def test_rule_without_dates_before_the_end_is_an_error(self):
        monday = _future_weekday(weekday=0)
        form = self._form(
            monday,
            repeat_unit="week",
            repeat_weekdays=["4"],
            repeat_ends="on",
            repeat_until=(monday + datetime.timedelta(days=1)).isoformat(),
        )
        assert not form.is_valid()
        assert form.errors["repeat"] == [
            "This repeat rule doesn't produce any upcoming dates."
        ]

    def test_edit_form_prefills_monthly_rule(self, client, owner):
        day = _last_weekday_date()
        client.post(
            reverse("event_create"),
            _create_data(
                day,
                repeat="custom",
                repeat_unit="month",
                repeat_monthly="last",
                repeat_count="3",
            ),
        )
        event = _occurrences()[0]
        form = EventForm(instance=event, creation=False)
        assert form.initial["repeat_unit"] == "month"
        assert form.initial["repeat_monthly"] == "last"
        assert form.initial["repeat"] in ("monthly_last", "custom")


@pytest.mark.django_db
def test_preview_does_not_repeat_date_errors(client, owner):
    data = _create_data(_future_weekday(), start_time="22:00", end_time="03:00")
    resp = client.post(reverse("event_recurrence_preview"), data)
    assert b"End time must be after start time" not in resp.content
    assert b"Fix the date and time above" in resp.content
