"""Recurrence rules for repeating events.

Pure date logic, no database access: turning the event form's repeat fields
into a `Pattern`, serializing it as an RFC 5545 RRULE, describing it in
words, and expanding it into occurrence start times within the limits
(EVENT_HORIZON ahead of now, MAX_UPCOMING_OCCURRENCES_PER_SERIES dates).

All datetimes here are naive and in local time (TIME_ZONE): rules are
expanded on the wall clock, so a 19:00 class stays at 19:00 across a
daylight-saving change. Callers make them aware afterwards.
"""

import calendar
import datetime
from dataclasses import dataclass
from enum import StrEnum

from dateutil import rrule as du

# How far ahead any event, recurring or not, may start.
EVENT_HORIZON = datetime.timedelta(days=365)
MAX_INTERVAL = 99

WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
WEEKDAY_NAMES = tuple(calendar.day_name)  # Monday first, matching date.weekday()
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", -1: "last"}
WEEKDAYS_MON_FRI = (0, 1, 2, 3, 4)


class Freq(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


_DU_FREQ = {Freq.DAILY: du.DAILY, Freq.WEEKLY: du.WEEKLY, Freq.MONTHLY: du.MONTHLY}
_UNIT_NAMES = {Freq.DAILY: "day", Freq.WEEKLY: "week", Freq.MONTHLY: "month"}


@dataclass(frozen=True)
class Pattern:
    """What repeats, without when it ends (see `Ends`).

    Monthly rules repeat either on a day of the month (`month_day`) or on the
    nth weekday of the month (`nth` 1-5, or -1 for the last, with
    `nth_weekday`).
    """

    freq: Freq
    interval: int = 1
    weekdays: tuple[int, ...] = ()  # WEEKLY: 0 = Monday … 6 = Sunday
    month_day: int | None = None
    nth: int | None = None
    nth_weekday: int | None = None

    def __post_init__(self):
        if not 1 <= self.interval <= MAX_INTERVAL:
            raise ValueError(f"interval out of range: {self.interval}")
        if self.freq == Freq.WEEKLY and not self.weekdays:
            raise ValueError("a weekly rule needs at least one weekday")
        if self.freq == Freq.MONTHLY and (self.month_day is None) == (
            self.nth is None or self.nth_weekday is None
        ):
            raise ValueError("a monthly rule needs a day of month or an nth weekday")

    def _nth(self) -> tuple[int, int]:
        """(nth, weekday) of an "nth weekday of the month" rule."""
        if self.nth is None or self.nth_weekday is None:
            raise ValueError("not an nth-weekday rule")
        return self.nth, self.nth_weekday

    def to_rrule(self) -> str:
        parts = [f"FREQ={self.freq}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.freq == Freq.WEEKLY:
            parts.append("BYDAY=" + ",".join(WEEKDAY_CODES[d] for d in self.weekdays))
        elif self.freq == Freq.MONTHLY:
            if self.month_day is not None:
                parts.append(f"BYMONTHDAY={self.month_day}")
            else:
                nth, weekday = self._nth()
                parts.append(f"BYDAY={nth}{WEEKDAY_CODES[weekday]}")
        return ";".join(parts)

    @classmethod
    def from_rrule(cls, value: str) -> Pattern:
        """Parse an RRULE written by `to_rrule` (only that subset)."""
        fields = dict(part.split("=", 1) for part in value.split(";"))
        freq = Freq(fields["FREQ"])
        interval = int(fields.get("INTERVAL", 1))
        if freq == Freq.WEEKLY:
            days = tuple(WEEKDAY_CODES.index(d) for d in fields["BYDAY"].split(","))
            return cls(freq, interval, weekdays=days)
        if freq == Freq.MONTHLY:
            if "BYMONTHDAY" in fields:
                return cls(freq, interval, month_day=int(fields["BYMONTHDAY"]))
            byday = fields["BYDAY"]
            return cls(
                freq,
                interval,
                nth=int(byday[:-2]),
                nth_weekday=WEEKDAY_CODES.index(byday[-2:]),
            )
        return cls(freq, interval)

    def describe(self) -> str:
        """Human-readable summary, e.g. "Every 2 weeks on Tuesday and Thursday"."""
        if self.interval == 1:
            every = {
                Freq.DAILY: "Daily",
                Freq.WEEKLY: "Weekly",
                Freq.MONTHLY: "Monthly",
            }[self.freq]
        else:
            every = f"Every {self.interval} {_UNIT_NAMES[self.freq]}s"
        if self.freq == Freq.WEEKLY:
            if self.interval == 1 and self.weekdays == WEEKDAYS_MON_FRI:
                return "Every weekday (Monday to Friday)"
            names = [WEEKDAY_NAMES[d] for d in self.weekdays]
            return f"{every} on {_join(names)}"
        if self.freq == Freq.MONTHLY:
            if self.month_day is not None:
                return f"{every} on day {self.month_day}"
            nth, weekday = self._nth()
            return f"{every} on the {ORDINALS[nth]} {WEEKDAY_NAMES[weekday]}"
        return every

    def _rrule(self, dtstart: datetime.datetime, until: datetime.datetime):
        kwargs = {}
        if self.freq == Freq.WEEKLY:
            kwargs["byweekday"] = self.weekdays
        elif self.freq == Freq.MONTHLY:
            if self.month_day is not None:
                kwargs["bymonthday"] = self.month_day
            else:
                nth, weekday = self._nth()
                kwargs["byweekday"] = du.weekday(weekday, nth)
        return du.rrule(
            _DU_FREQ[self.freq],
            dtstart=dtstart,
            interval=self.interval,
            until=until,
            **kwargs,
        )


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def nth_weekday_of(day: datetime.date) -> int:
    """Which occurrence of its weekday *day* is in its month (1-5)."""
    return (day.day - 1) // 7 + 1


def is_last_weekday_of_month(day: datetime.date) -> bool:
    return day.day + 7 > calendar.monthrange(day.year, day.month)[1]


# Preset choices of the form's "Repeat" select, derived from the start date
# (like Google Calendar's "Weekly on Tuesday"). "" and "custom" are handled
# by the form.
PRESET_DAILY = "daily"
PRESET_WEEKDAYS = "weekdays"
PRESET_WEEKLY = "weekly"
PRESET_MONTHLY_DAY = "monthly_day"
PRESET_MONTHLY_NTH = "monthly_nth"
PRESET_MONTHLY_LAST = "monthly_last"


def preset_patterns(day: datetime.date) -> dict[str, Pattern]:
    """The presets that apply to start date *day*, keyed by choice value.

    "The nth weekday" is offered for the first four weeks and "the last
    weekday" for the last seven days of the month, so a date can have both.
    """
    weekday = day.weekday()
    presets = {
        PRESET_DAILY: Pattern(Freq.DAILY),
        PRESET_WEEKDAYS: Pattern(Freq.WEEKLY, weekdays=WEEKDAYS_MON_FRI),
        PRESET_WEEKLY: Pattern(Freq.WEEKLY, weekdays=(weekday,)),
        PRESET_MONTHLY_DAY: Pattern(Freq.MONTHLY, month_day=day.day),
    }
    nth = nth_weekday_of(day)
    if nth <= 4:
        presets[PRESET_MONTHLY_NTH] = Pattern(
            Freq.MONTHLY, nth=nth, nth_weekday=weekday
        )
    if is_last_weekday_of_month(day):
        presets[PRESET_MONTHLY_LAST] = Pattern(
            Freq.MONTHLY, nth=-1, nth_weekday=weekday
        )
    return presets


@dataclass(frozen=True)
class Ends:
    """When a rule stops: on a date (inclusive), after a number of dates, or
    never (both None; the limits cut it off)."""

    until: datetime.date | None = None
    count: int | None = None


class CutReason(StrEnum):
    """Why an expansion stopped before the rule's own end."""

    HORIZON = "horizon"  # EVENT_HORIZON ahead of now
    SERIES_LIMIT = "series_limit"  # MAX_UPCOMING_OCCURRENCES_PER_SERIES
    ACCOUNT_LIMIT = "account_limit"  # MAX_UPCOMING_EVENTS_PER_USER


@dataclass(frozen=True)
class Expansion:
    starts: list[datetime.datetime]
    cut: CutReason | None = None


def expand(
    pattern: Pattern,
    anchor: datetime.datetime,
    *,
    ends: Ends,
    now: datetime.datetime,
    limit: int,
    limit_reason: CutReason = CutReason.SERIES_LIMIT,
    start_from: datetime.datetime | None = None,
) -> Expansion:
    """Start times of *pattern* from *anchor*, after *now*, within the limits.

    *anchor* is the rule's DTSTART: it fixes the phase of "every 2 weeks" and
    the time of day; it is only an occurrence itself when it matches the rule
    (weekly on Tuesday from a Monday starts on the Tuesday). Dates before
    *start_from* (default: the anchor) are skipped and don't count towards
    `ends.count`; dates up to *now* count but aren't returned. At most *limit*
    dates are returned, and none more than EVENT_HORIZON after *now*.
    """
    start_from = start_from or anchor
    horizon_end = now + EVENT_HORIZON
    # A finite bound for rules that never end. Going a year past the horizon
    # tells a rule the horizon cut off from one that ends just after it.
    open_bound = horizon_end + EVENT_HORIZON
    until_bound = open_bound
    if ends.until is not None:
        until_bound = min(
            open_bound, datetime.datetime.combine(ends.until, datetime.time.max)
        )

    starts: list[datetime.datetime] = []
    counted = 0
    for occurrence in pattern._rrule(anchor, until_bound):
        if occurrence < start_from:
            continue
        if ends.count is not None and counted >= ends.count:
            return Expansion(starts)
        if occurrence > horizon_end:
            return Expansion(starts, CutReason.HORIZON)
        counted += 1
        if occurrence <= now:
            continue
        if len(starts) >= limit:
            return Expansion(starts, limit_reason)
        starts.append(occurrence)
    if until_bound == open_bound and (ends.count is None or counted < ends.count):
        # Only a rule with no occurrence in the year after the horizon gets
        # here (e.g. every 99 months); it still runs past the horizon.
        return Expansion(starts, CutReason.HORIZON)
    return Expansion(starts)
