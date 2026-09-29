"""Tests for events.recurrence: repeat rules and their expansion (no DB)."""

import datetime

import pytest

from ..recurrence import (
    PRESET_MONTHLY_LAST,
    PRESET_MONTHLY_NTH,
    CutReason,
    Ends,
    Freq,
    Pattern,
    expand,
    is_last_weekday_of_month,
    nth_weekday_of,
    preset_patterns,
)

NOW = datetime.datetime(2026, 9, 29, 12, 0)
ANCHOR = datetime.datetime(2026, 10, 20, 19, 0)  # a Tuesday
TUESDAY = 1


def _expand(pattern, ends=Ends(), **kwargs):  # noqa: B008
    kwargs.setdefault("limit", 110)
    return expand(pattern, kwargs.pop("anchor", ANCHOR), ends=ends, now=NOW, **kwargs)


class TestPattern:
    @pytest.mark.parametrize(
        ("pattern", "rrule", "description"),
        [
            (Pattern(Freq.DAILY), "FREQ=DAILY", "Daily"),
            (Pattern(Freq.DAILY, 3), "FREQ=DAILY;INTERVAL=3", "Every 3 days"),
            (
                Pattern(Freq.WEEKLY, weekdays=(TUESDAY,)),
                "FREQ=WEEKLY;BYDAY=TU",
                "Weekly on Tuesday",
            ),
            (
                Pattern(Freq.WEEKLY, 2, weekdays=(0, 2, 4)),
                "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR",
                "Every 2 weeks on Monday, Wednesday and Friday",
            ),
            (
                Pattern(Freq.WEEKLY, weekdays=(0, 1, 2, 3, 4)),
                "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
                "Every weekday (Monday to Friday)",
            ),
            (
                Pattern(Freq.MONTHLY, month_day=29),
                "FREQ=MONTHLY;BYMONTHDAY=29",
                "Monthly on day 29",
            ),
            (
                Pattern(Freq.MONTHLY, nth=4, nth_weekday=TUESDAY),
                "FREQ=MONTHLY;BYDAY=4TU",
                "Monthly on the fourth Tuesday",
            ),
            (
                Pattern(Freq.MONTHLY, 2, nth=-1, nth_weekday=6),
                "FREQ=MONTHLY;INTERVAL=2;BYDAY=-1SU",
                "Every 2 months on the last Sunday",
            ),
        ],
    )
    def test_rrule_round_trip_and_description(self, pattern, rrule, description):
        assert pattern.to_rrule() == rrule
        assert Pattern.from_rrule(rrule) == pattern
        assert pattern.describe() == description

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"freq": Freq.DAILY, "interval": 0},
            {"freq": Freq.DAILY, "interval": 100},
            {"freq": Freq.WEEKLY},
            {"freq": Freq.MONTHLY},
            {"freq": Freq.MONTHLY, "month_day": 3, "nth": 1, "nth_weekday": 0},
        ],
    )
    def test_invalid_patterns_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            Pattern(**kwargs)


class TestPresets:
    def test_nth_weekday_and_last(self):
        assert nth_weekday_of(datetime.date(2026, 10, 20)) == 3
        assert nth_weekday_of(datetime.date(2026, 9, 29)) == 5
        assert is_last_weekday_of_month(datetime.date(2026, 10, 27))
        assert not is_last_weekday_of_month(datetime.date(2026, 10, 20))

    def test_mid_month_date_offers_nth_but_not_last(self):
        presets = preset_patterns(datetime.date(2026, 10, 13))
        assert presets[PRESET_MONTHLY_NTH] == Pattern(
            Freq.MONTHLY, nth=2, nth_weekday=TUESDAY
        )
        assert PRESET_MONTHLY_LAST not in presets

    def test_fourth_and_last_offers_both(self):
        presets = preset_patterns(datetime.date(2026, 10, 27))
        assert presets[PRESET_MONTHLY_NTH].nth == 4
        assert presets[PRESET_MONTHLY_LAST].nth == -1

    def test_fifth_weekday_offers_only_last(self):
        presets = preset_patterns(datetime.date(2026, 9, 29))
        assert PRESET_MONTHLY_NTH not in presets
        assert presets[PRESET_MONTHLY_LAST].nth == -1


class TestExpand:
    def test_never_ending_weekly_rule_stops_at_the_horizon(self):
        expansion = _expand(Pattern(Freq.WEEKLY, weekdays=(TUESDAY,)))
        assert expansion.cut == CutReason.HORIZON
        assert expansion.starts[0] == ANCHOR
        assert expansion.starts[-1] <= NOW + datetime.timedelta(days=365)
        assert expansion.starts[-1] + datetime.timedelta(weeks=1) > NOW + (
            datetime.timedelta(days=365)
        )
        assert all(start.time() == datetime.time(19) for start in expansion.starts)

    def test_daily_rule_is_cut_at_the_limit(self):
        expansion = _expand(Pattern(Freq.DAILY))
        assert len(expansion.starts) == 110
        assert expansion.cut == CutReason.SERIES_LIMIT

    def test_limit_reason_is_passed_through(self):
        expansion = _expand(
            Pattern(Freq.DAILY), limit=5, limit_reason=CutReason.ACCOUNT_LIMIT
        )
        assert len(expansion.starts) == 5
        assert expansion.cut == CutReason.ACCOUNT_LIMIT

    def test_count(self):
        expansion = _expand(Pattern(Freq.DAILY), Ends(count=3))
        assert [s.day for s in expansion.starts] == [20, 21, 22]
        assert expansion.cut is None

    def test_until_is_inclusive(self):
        expansion = _expand(
            Pattern(Freq.WEEKLY, weekdays=(TUESDAY,)),
            Ends(until=datetime.date(2026, 11, 3)),
        )
        assert [s.day for s in expansion.starts] == [20, 27, 3]
        assert expansion.cut is None

    def test_until_past_the_horizon_is_cut(self):
        expansion = _expand(
            Pattern(Freq.MONTHLY, month_day=20),
            Ends(until=datetime.date(2028, 1, 1)),
        )
        assert expansion.cut == CutReason.HORIZON

    def test_count_reached_exactly_at_the_limit_is_not_cut(self):
        expansion = _expand(Pattern(Freq.DAILY), Ends(count=3), limit=3)
        assert len(expansion.starts) == 3
        assert expansion.cut is None

    def test_anchor_not_matching_the_rule_starts_at_the_next_match(self):
        monday = datetime.datetime(2026, 10, 19, 19, 0)
        expansion = _expand(
            Pattern(Freq.WEEKLY, weekdays=(TUESDAY, 3)), Ends(count=3), anchor=monday
        )
        assert [s.day for s in expansion.starts] == [20, 22, 27]

    def test_interval_keeps_the_anchor_phase(self):
        expansion = _expand(
            Pattern(Freq.WEEKLY, 2, weekdays=(TUESDAY,)),
            Ends(count=3),
            start_from=datetime.datetime(2026, 10, 21),
        )
        assert [s.date() for s in expansion.starts] == [
            datetime.date(2026, 11, 3),
            datetime.date(2026, 11, 17),
            datetime.date(2026, 12, 1),
        ]

    def test_past_dates_count_but_are_not_returned(self):
        anchor = datetime.datetime(2026, 9, 27, 19, 0)
        expansion = _expand(Pattern(Freq.DAILY), Ends(count=4), anchor=anchor)
        # 27 and 28 September are before NOW (29 September, noon).
        assert [s.day for s in expansion.starts] == [29, 30]

    def test_monthly_day_31_skips_shorter_months(self):
        expansion = _expand(
            Pattern(Freq.MONTHLY, month_day=31),
            Ends(until=datetime.date(2027, 3, 31)),
        )
        assert [(s.month, s.day) for s in expansion.starts] == [
            (10, 31),
            (12, 31),
            (1, 31),
            (3, 31),
        ]

    def test_last_weekday_of_month(self):
        expansion = _expand(
            Pattern(Freq.MONTHLY, nth=-1, nth_weekday=TUESDAY), Ends(count=3)
        )
        assert [s.date() for s in expansion.starts] == [
            datetime.date(2026, 10, 27),
            datetime.date(2026, 11, 24),
            datetime.date(2026, 12, 29),
        ]

    def test_rule_with_nothing_before_the_horizon(self):
        expansion = _expand(
            Pattern(Freq.MONTHLY, 99, month_day=20),
            anchor=datetime.datetime(2026, 9, 20, 19, 0),
        )
        assert expansion.starts == []
        assert expansion.cut == CutReason.HORIZON
