"""Creating and changing recurring events.

A recurring event is an EventSeries plus one ordinary Event row per
occurrence, so lists, feeds, search and retention need no special cases.
This module plans changes to a series without writing anything (the form
preview shows the plan) and then applies them in one transaction:

- `plan_creation` / `create_series`: a new event that repeats.
- `plan_edit` / `SeriesEdit.apply`: an edit to an occurrence applied to
  "this and following" or "all" events of its series (or turning a single
  event into a series). Only the fields the owner changed are copied to the
  other occurrences, so their individual edits survive. Changing the rule or
  the date regenerates the upcoming occurrences; changing only the end date
  extends or shortens the series.
- `scope_queryset`: the occurrences a delete affects.
- `link_scraped_series`: groups a scraped show's dates into a series (no
  rule; the importer calls it after each run).
- `first_per_series` / `attach_series_cards`: listings show a series as one
  card, at its first date in the listed range, with its other dates.

Past occurrences are never moved or deleted by an edit; limits count only
upcoming dates (MAX_UPCOMING_OCCURRENCES_PER_SERIES per series,
MAX_UPCOMING_EVENTS_PER_USER per account) and rules that produce more are cut
off with a notice rather than rejected.
"""

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateformat import format as date_format

from .models import Event, EventSeries
from .recurrence import CutReason, Ends, Expansion, Pattern, expand


class Scope(StrEnum):
    THIS = "this"
    FOLLOWING = "following"
    ALL = "all"


SCOPE_CHOICES = [
    (Scope.THIS, "Only this event"),
    (Scope.FOLLOWING, "This and following events"),
    (Scope.ALL, "All events in the series"),
]

# Event fields an edit copies to the other occurrences in scope (when changed).
CONTENT_FIELDS = (
    "title",
    "description",
    "image",
    "venue_name",
    "venue_address",
    "category",
    "is_free",
    "is_wheelchair_accessible",
    "price_note",
    "source_url",
)

Span = tuple[datetime.datetime, datetime.datetime | None]


def local_naive(value) -> datetime.datetime:
    """*value* (an aware datetime) as a naive local wall-clock time."""
    return timezone.localtime(value).replace(tzinfo=None)


def _event_span(event: Event) -> Span:
    return event.start_datetime, event.end_datetime  # ty: ignore[invalid-return-type]


def _set_span(event: Event, span: Span) -> None:
    event.start_datetime, event.end_datetime = span  # ty: ignore[invalid-assignment]


def _series(event: Event) -> EventSeries | None:
    return event.series  # ty: ignore[invalid-return-type]


def _span(start: datetime.datetime, duration: datetime.timedelta | None) -> Span:
    """Aware start/end of an occurrence at local wall-clock time *start*."""
    end = timezone.make_aware(start + duration) if duration is not None else None
    return timezone.make_aware(start), end


def _duration(start: datetime.datetime, end: datetime.datetime | None):
    """Wall-clock length of an event, so it keeps its local end time across DST."""
    return local_naive(end) - local_naive(start) if end else None


def _format_date(value: datetime.datetime) -> str:
    return date_format(timezone.localtime(value), "D j M Y")


def _upcoming_count(user) -> int:
    return Event.objects.filter(
        submitted_by=user, start_datetime__gte=timezone.now()
    ).count()


def _account_room(user) -> int | None:
    """How many more upcoming events *user* may have; None = unlimited."""
    if user is None or user.is_system_account:
        return None
    return max(0, settings.MAX_UPCOMING_EVENTS_PER_USER - _upcoming_count(user))


def _limit(series_room: int, account_room: int | None) -> tuple[int, CutReason]:
    if account_room is not None and account_room < series_room:
        return account_room, CutReason.ACCOUNT_LIMIT
    return series_room, CutReason.SERIES_LIMIT


def cut_notice(expansion: Expansion) -> str:
    """Tell the owner why the dates stop before the rule's own end."""
    if not expansion.starts or expansion.cut is None:
        return ""
    count = len(expansion.starts)
    if expansion.cut == CutReason.HORIZON:
        last = date_format(expansion.starts[-1], "j F Y")
        return f"The dates stop at {last}: events can be at most one year ahead."
    if expansion.cut == CutReason.SERIES_LIMIT:
        return (
            f"Only the first {count} dates are included: a repeating event can "
            f"have at most {settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES} "
            "upcoming dates."
        )
    return (
        f"Only the first {count} dates are included: you can have at most "
        f"{settings.MAX_UPCOMING_EVENTS_PER_USER} upcoming events in total."
    )


NO_DATES_ERROR = "This repeat rule doesn't produce any upcoming dates."


def check_conflicts(rows: list[tuple[str, datetime.datetime, str]], exclude=()):
    """Raise ValidationError if two rows, or a row and another event, share a
    (title, start, venue) — the Event unique constraint. *exclude* lists the
    pks of rows being rewritten or deleted."""
    seen: set[tuple] = set()
    clashes: set[datetime.datetime] = set()
    for key in rows:
        if key in seen:
            clashes.add(key[1])
        seen.add(key)
    existing = (
        Event.objects.filter(
            start_datetime__in={start for _, start, _ in rows},
            title__in={title for title, _, _ in rows},
            venue_name__in={venue for _, _, venue in rows},
        )
        .exclude(pk__in=list(exclude))
        .values_list("title", "start_datetime", "venue_name")
    )
    clashes.update(key[1] for key in existing if key in seen)
    if clashes:
        dates = ", ".join(_format_date(start) for start in sorted(clashes))
        raise ValidationError(
            "An event with this title already exists at this venue at the same "
            f"date and time: {dates}."
        )


def _clone(template: Event, span: Span, series: EventSeries | None) -> Event:
    """A new occurrence with *template*'s content at *span*."""
    start, end = span
    return Event(
        **{name: getattr(template, name) for name in CONTENT_FIELDS if name != "image"},
        image=template.image.name or None,
        start_datetime=start,
        end_datetime=end,
        submitted_by=template.submitted_by,
        is_draft=template.is_draft,
        series=series,
        # Same venue, so skip geocoding (save() only geocodes when these are
        # unset or the venue changed).
        latitude=template.latitude,
        longitude=template.longitude,
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


@dataclass
class SeriesCreation:
    pattern: Pattern
    anchor: datetime.datetime  # naive local DTSTART
    spans: list[Span]
    expansion: Expansion

    @property
    def notice(self) -> str:
        return cut_notice(self.expansion)


def plan_creation(
    pattern: Pattern,
    ends: Ends,
    start: datetime.datetime,
    end: datetime.datetime | None,
    user,
) -> SeriesCreation:
    """The occurrences of a new repeating event starting at *start*."""
    anchor = local_naive(start)
    limit, reason = _limit(
        settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES, _account_room(user)
    )
    expansion = expand(
        pattern,
        anchor,
        ends=ends,
        now=local_naive(timezone.now()),
        limit=limit,
        limit_reason=reason,
    )
    if not expansion.starts:
        raise ValidationError(NO_DATES_ERROR)
    duration = _duration(start, end)
    spans = [_span(s, duration) for s in expansion.starts]
    return SeriesCreation(pattern, anchor, spans, expansion)


def create_series(event: Event, plan: SeriesCreation) -> list[Event]:
    """Save *event* (unsaved, with its image attached) as the first occurrence
    of a new series and create the others as copies of it."""
    with transaction.atomic():
        series = EventSeries.objects.create(
            rrule=plan.pattern.to_rrule(), dtstart=timezone.make_aware(plan.anchor)
        )
        _set_span(event, plan.spans[0])
        event.series = series
        event.save()
        occurrences = [event]
        for span in plan.spans[1:]:
            occurrence = _clone(event, span, series)
            occurrence.save()
            occurrences.append(occurrence)
    return occurrences


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@dataclass
class SeriesEdit:
    """A planned edit of occurrence `event` and the others in its scope."""

    event: Event  # the edited occurrence, carrying the form's changes
    event_span: Span | None  # its new start/end; None = delete it
    others: list[Event]  # other occurrences in scope that stay
    moves: dict = field(default_factory=dict)  # pk -> new Span
    deletes: list[Event] = field(default_factory=list)
    creates: list[Span] = field(default_factory=list)
    content_fields: list[str] = field(default_factory=list)
    copy_draft: bool = False
    # Series the occurrences in scope belong to afterwards: the existing one,
    # a new one (`new_series`, unsaved), or None (no longer repeating).
    series: EventSeries | None = None
    new_series: bool = False
    update_series: bool = False  # save a changed rrule/dtstart on `series`
    expansion: Expansion | None = None

    @property
    def notice(self) -> str:
        return cut_notice(self.expansion) if self.expansion else ""

    @property
    def upcoming_dates(self) -> list[datetime.datetime]:
        """Start times of the upcoming occurrences in scope after the edit."""
        now = timezone.now()
        starts = [start for start, _ in self.creates]
        if self.event_span is not None:
            starts.append(self.event_span[0])
        for other in self.others:
            starts.append(self.moves.get(other.pk, (other.start_datetime,))[0])
        return sorted(start for start in starts if start >= now)

    def _final_rows(self):
        event = self.event
        title, venue = str(event.title), str(event.venue_name)
        rows = []
        if self.event_span is not None:
            rows.append((title, self.event_span[0], venue))
        for other in self.others:
            start = self.moves.get(other.pk, (other.start_datetime,))[0]
            rows.append(
                (
                    title if "title" in self.content_fields else str(other.title),
                    start,
                    venue
                    if "venue_name" in self.content_fields
                    else str(other.venue_name),
                )
            )
        rows.extend((title, start, venue) for start, _ in self.creates)
        return rows

    def check(self) -> None:
        """Raise ValidationError if the edit would clash with other events."""
        exclude = [self.event.pk, *(o.pk for o in self.others + self.deletes)]
        check_conflicts(self._final_rows(), exclude)

    def apply(self) -> Event | None:
        """Write the edit. Returns the edited event, or when the edit removed
        it, the first remaining occurrence in scope (None if there is none)."""
        event = self.event
        old_series_id = event.series_id
        try:
            with transaction.atomic():
                series = self.series
                if series is not None and (self.new_series or self.update_series):
                    series.save()
                for row in self.deletes:
                    row.delete()
                if self.event_span is not None:
                    _set_span(event, self.event_span)
                    event.series = series  # ty: ignore[invalid-assignment]
                    event.save()
                # The edited event's values (incl. a new image) are the
                # template for the others even when the edit removes it.
                for other in self.others:
                    self._update_other(other, series)
                created = [_clone(event, span, series) for span in self.creates]
                for occurrence in created:
                    occurrence.save()
                if self.event_span is None:
                    # Last, so its files are still referenced by the others
                    # when the delete signal checks.
                    event.delete()
                # The occurrences may have left it (e.g. "does not repeat"),
                # which the delete signal can't see.
                _delete_series_if_empty(old_series_id)
        except IntegrityError as exc:
            # check() already rules out clashes in the final state; this is
            # a safety net for a concurrent edit or an intermediate clash.
            raise ValidationError(
                "The changes clash with another event at the same time. "
                "Please try again."
            ) from exc
        if self.event_span is not None:
            return event
        remaining = sorted(
            [*self.others, *created], key=lambda o: (o.start_datetime, str(o.pk))
        )
        return remaining[0] if remaining else None

    def _update_other(self, other: Event, series: EventSeries | None) -> None:
        """Apply the edit to another occurrence in scope and save it."""
        for name in self.content_fields:
            value = getattr(self.event, name)
            if name == "image":
                value = value.name or None
            setattr(other, name, value)
        if other.pk in self.moves:
            _set_span(other, self.moves[other.pk])
        if self.copy_draft:
            other.is_draft = self.event.is_draft
        other.series = series  # ty: ignore[invalid-assignment]
        other.save()


def _delete_series_if_empty(series_id) -> None:
    if series_id and not Event.objects.filter(series_id=series_id).exists():
        EventSeries.objects.filter(pk=series_id).delete()


def _scope_others(original: Event, scope: Scope) -> list[Event]:
    """The other occurrences an edit of *original* with *scope* affects."""
    if original.series_id is None or scope == Scope.THIS:
        return []
    qs = Event.objects.filter(
        series_id=original.series_id, submitted_by=original.submitted_by
    ).exclude(pk=original.pk)
    if scope == Scope.FOLLOWING:
        qs = qs.filter(start_datetime__gte=original.start_datetime)
    return list(qs.order_by("start_datetime", "id"))


def plan_edit(
    event: Event,
    original: Event,
    *,
    scope: Scope,
    pattern: Pattern | None,
    ends: Ends,
    ends_changed: bool,
    changed_fields,
    user,
) -> SeriesEdit:
    """Plan an edit of occurrence *event* applied to *scope*.

    *event* carries the form's changes (unsaved); *original* is the same row
    as stored. *pattern* is the form's repeat rule (None = does not repeat)
    and *changed_fields* the form's changed_data. Raises ValidationError when
    no dates would be left or the result clashes with other events.
    """
    now = timezone.now()
    now_local = local_naive(now)
    series = _series(original)
    if series is None:
        scope = Scope.ALL
    others = _scope_others(original, scope)

    edit = SeriesEdit(
        event=event,
        event_span=_event_span(event),
        others=others,
        content_fields=[f for f in CONTENT_FIELDS if f in changed_fields],
        copy_draft=event.is_draft != original.is_draft,
        series=series,
    )

    if pattern is None:
        # "Does not repeat": the upcoming occurrences in scope go, the edited
        # one and past ones stay (the event keeps its series only while it
        # has other occurrences).
        edit.deletes = [o for o in others if o.start_datetime >= now]
        edit.others = [o for o in others if o.start_datetime < now]
        if series is not None:
            remaining = Event.objects.filter(series=series).exclude(
                pk__in=[event.pk, *(o.pk for o in edit.deletes)]
            )
            if not remaining.exists():
                edit.series = None
        edit.check()
        return edit

    old_pattern = series.pattern if series is not None else None
    date_changed = (
        local_naive(event.start_datetime).date()
        != local_naive(original.start_datetime).date()
    )
    if pattern != old_pattern or date_changed:
        if date_changed and not ends_changed and ends.until is not None:
            # Moving the dates without touching the end moves the end along,
            # so the series keeps its number of dates.
            shift = (
                local_naive(event.start_datetime).date()
                - local_naive(original.start_datetime).date()
            )
            ends = Ends(until=ends.until + shift)
        _plan_regeneration(edit, original, scope, pattern, ends, user, now)
    else:
        _plan_time_and_end(
            edit, original, scope, ends, ends_changed, user, now, now_local
        )
    edit.check()
    return edit


def _plan_regeneration(edit, original, scope, pattern, ends, user, now):
    """New rule or date: replace the upcoming occurrences in scope with the
    rule's dates, reusing existing rows (and their URLs) where possible."""
    event, series = edit.event, edit.series
    duration = _duration(event.start_datetime, event.end_datetime)
    anchor = _regeneration_anchor(edit, original, scope, now)

    event_upcoming = original.start_datetime >= now
    pool = [o for o in edit.others if o.start_datetime >= now]
    if event_upcoming:
        pool.append(original)
    pool.sort(key=lambda o: o.start_datetime)

    account_room = _account_room(user)
    if account_room is not None:
        account_room += len(pool)
    limit, reason = _limit(settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES, account_room)
    expansion = expand(
        pattern,
        anchor,
        ends=ends,
        now=local_naive(now),
        limit=limit,
        limit_reason=reason,
    )
    if not expansion.starts:
        raise ValidationError(NO_DATES_ERROR)
    edit.expansion = expansion
    spans = [_span(s, duration) for s in expansion.starts]
    assigned, edit.creates, removed = _assign_spans(pool, spans)

    if event_upcoming:
        edit.event_span = assigned.get(original.pk)  # None: removed
    edit.deletes = [o for o in edit.others if o.pk in removed]
    edit.others = [o for o in edit.others if o.pk not in removed]
    edit.moves = {pk: span for pk, span in assigned.items() if pk != original.pk}

    rrule, dtstart = pattern.to_rrule(), timezone.make_aware(anchor)
    splits = (
        series is not None
        and scope == Scope.FOLLOWING
        and Event.objects.filter(
            series=series, start_datetime__lt=original.start_datetime
        )
        .exclude(pk=original.pk)
        .exists()
    )
    if series is None or splits:
        # A single event becoming a series, or "this and following" leaving
        # the earlier occurrences in the old series.
        edit.series = EventSeries(rrule=rrule, dtstart=dtstart)
        edit.new_series = True
    else:
        series.rrule, series.dtstart = rrule, dtstart
        edit.update_series = True


def _regeneration_anchor(edit, original, scope, now) -> datetime.datetime:
    """DTSTART of a regenerated series: the edited date and time, or for
    scope "all", the series' first upcoming date moved by as many days as the
    edited occurrence was (as in Google Calendar)."""
    start_local = local_naive(edit.event.start_datetime)
    if scope != Scope.ALL or edit.series is None:
        return start_local
    upcoming = [o for o in [original, *edit.others] if o.start_datetime >= now]
    first = min(upcoming, key=lambda o: o.start_datetime, default=original)
    shift = start_local.date() - local_naive(original.start_datetime).date()
    return datetime.datetime.combine(
        local_naive(first.start_datetime).date() + shift, start_local.time()
    )


def _assign_spans(pool: list[Event], spans: list[Span]):
    """Pair existing rows with new dates: returns (pk -> span, spans left
    to create, pks left without a date).

    Rows already at one of the new start times keep it; the rest are paired
    with the remaining dates in order. Rows never move onto a start another
    row still holds, so the unique constraint holds at every step.
    """
    by_start = {span[0]: span for span in spans}
    assigned: dict = {}
    unmatched_rows = []
    for row in pool:
        span = by_start.pop(row.start_datetime, None)
        if span is None:
            unmatched_rows.append(row)
        else:
            assigned[row.pk] = span
    free_spans = sorted(by_start.values(), key=lambda s: s[0])
    for row, span in zip(unmatched_rows, free_spans, strict=False):
        assigned[row.pk] = span
    creates = free_spans[len(unmatched_rows) :]
    removed = {row.pk for row in unmatched_rows[len(free_spans) :]}
    return assigned, creates, removed


def _plan_time_and_end(edit, original, scope, ends, ends_changed, user, now, now_local):
    """Same rule and date: move the others to the new time of day, and if the
    end changed, add dates after the last occurrence or drop those past it."""
    event, series = edit.event, edit.series
    start_local = local_naive(event.start_datetime)
    new_time = start_local.time()
    duration = _duration(event.start_datetime, event.end_datetime)
    old_duration = _duration(original.start_datetime, original.end_datetime)
    if (
        new_time != local_naive(original.start_datetime).time()
        or duration != old_duration
    ):
        for other in edit.others:
            day = local_naive(other.start_datetime).date()
            edit.moves[other.pk] = _span(
                datetime.datetime.combine(day, new_time), duration
            )
    if not ends_changed:
        return

    def new_start(row):
        if row.pk == original.pk:
            return event.start_datetime
        return edit.moves.get(row.pk, (row.start_datetime,))[0]

    scope_rows = [original, *edit.others]
    pool = [row for row in scope_rows if new_start(row) >= now]
    in_scope = {row.pk for row in scope_rows}
    outside_upcoming = (
        Event.objects.filter(series=series, start_datetime__gte=now)
        .exclude(pk__in=in_scope)
        .count()
    )
    account_room = _account_room(user)
    if account_room is not None:
        account_room += len(pool)
    limit, reason = _limit(
        max(0, settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES - outside_upcoming),
        account_room,
    )
    anchor = datetime.datetime.combine(local_naive(series.dtstart).date(), new_time)
    start_from = (
        datetime.datetime.combine(start_local.date(), new_time)
        if scope == Scope.FOLLOWING
        else now_local
    )
    expansion = expand(
        series.pattern,
        anchor,
        ends=ends,
        now=now_local,
        limit=limit,
        limit_reason=reason,
        start_from=start_from,
    )
    if not expansion.starts:
        raise ValidationError(NO_DATES_ERROR)
    edit.expansion = expansion
    last = timezone.make_aware(expansion.starts[-1])

    removed = {row.pk for row in pool if new_start(row) > last}
    if original.pk in removed:
        edit.event_span = None
    edit.deletes = [o for o in edit.others if o.pk in removed]
    edit.others = [o for o in edit.others if o.pk not in removed]
    kept_starts = [new_start(row) for row in scope_rows if row.pk not in removed]
    last_kept = max(kept_starts, default=None)
    edit.creates = [
        _span(s, duration)
        for s in expansion.starts
        if last_kept is None or timezone.make_aware(s) > last_kept
    ]


# ---------------------------------------------------------------------------
# Delete / publish
# ---------------------------------------------------------------------------


def scope_queryset(event: Event, scope: str):
    """The events a delete or publish/draft toggle of *event* affects."""
    qs = Event.objects.filter(pk=event.pk)
    if event.series_id is None or scope not in (Scope.FOLLOWING, Scope.ALL):
        return qs
    qs = Event.objects.filter(
        series_id=event.series_id, submitted_by=event.submitted_by
    )
    if scope == Scope.FOLLOWING:
        qs = qs.filter(start_datetime__gte=event.start_datetime)
    return qs


def series_context(event: Event, user) -> dict | None:
    """Detail-page info for an occurrence of a series: the rule (if any) and
    all its dates, grouped by day for the date strip.

    Drafts are shown only to their owner; dates too old for the listings
    (hidden_events_q) are left out.
    """
    from .models import hidden_events_q

    if event.series_id is None:
        return None
    series = _series(event)
    if series is None:
        return None
    occurrences = Event.objects.filter(series=series).exclude(
        ~Q(pk=event.pk) & hidden_events_q()
    )
    is_owner = user.is_authenticated and user == event.submitted_by
    if not is_owner:
        occurrences = occurrences.filter(Q(is_draft=False) | Q(pk=event.pk))
    occurrences = list(
        occurrences.order_by("start_datetime", "id").only(
            "slug", "start_datetime", "venue_name", "is_draft", "series_id"
        )
    )
    if len(occurrences) < 2:
        return None
    now = timezone.now()
    days: dict[datetime.date, list[Event]] = {}
    for occurrence in occurrences:
        days.setdefault(occurrence.local_start_date, []).append(occurrence)
    strip = []
    month = None
    current_day = []
    for day, dated in days.items():
        is_current = any(o.pk == event.pk for o in dated)
        if is_current:
            current_day = dated
        strip.append(
            {
                "date": day,
                "occurrences": dated,
                "new_month": (day.year, day.month) != month,
                "is_current": is_current,
                "is_past": all(o.start_datetime < now for o in dated),
            }
        )
        month = (day.year, day.month)
    pattern = series.pattern
    return {
        "summary": pattern.describe() if pattern is not None else "",
        "first": occurrences[0].start_datetime,
        "last": occurrences[-1].start_datetime,
        "count": len(occurrences),
        "day_count": len(strip),
        "days": strip,
        "current_day_times": current_day if len(current_day) > 1 else [],
    }


# ---------------------------------------------------------------------------
# Scraped shows
# ---------------------------------------------------------------------------

# A trailing date segment, as in WordPress/Tribe Events per-date URLs
# (".../event/get-weird-with-wrestling/2026-10-01/").
_TRAILING_DATE_RE = re.compile(r"/\d{4}-\d{2}-\d{2}/?$")


def scraped_series_key(external_source: str, source_url: str) -> str:
    """Identify the show a scraped date belongs to ("" = can't tell).

    Scrapers emit one record per date, and the dates of one show share its
    page URL (or, for per-date URLs, the URL minus the date).
    """
    if not external_source or not source_url:
        return ""
    return f"{external_source}:{_TRAILING_DATE_RE.sub('/', source_url)}"


def link_scraped_series(external_source: str, events: list[Event]) -> int:
    """Link imported dates of the same show into one series.

    A show gets a series once it lists two or more dates; after that its
    dates keep joining it, so a show down to its last upcoming date still
    groups with its past ones. Returns how many events were (re)linked.
    """
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        key = scraped_series_key(external_source, str(event.source_url))
        if key:
            groups[key].append(event)
    if not groups:
        return 0
    series_by_key = {
        series.source_key: series
        for series in EventSeries.objects.filter(source_key__in=list(groups))
    }
    linked = 0
    for key, dates in groups.items():
        series = series_by_key.get(key)
        if series is None:
            if len(dates) < 2:
                continue
            series = EventSeries.objects.create(
                source_key=key, dtstart=min(e.start_datetime for e in dates)
            )
        stray = [e.pk for e in dates if e.series_id != series.pk]
        if stray:
            linked += Event.objects.filter(pk__in=stray).update(series=series)
    return linked


# ---------------------------------------------------------------------------
# Listings: one card per series
# ---------------------------------------------------------------------------

# How many other days a list card names before "+N more".
CARD_DAYS = 5


def series_group():
    """What a listing groups by: the series, or the event itself."""
    from django.db.models import CharField
    from django.db.models.functions import Cast, Coalesce

    return Coalesce(Cast("series_id", CharField()), Cast("id", CharField()))


def first_per_series(qs, *, descending=False):
    """Keep only the first date of each series in *qs* (the latest when
    *descending*, for past listings); single events are kept as they are.

    Ranks the dates within each series by a window function, so filters
    already applied to *qs* decide which date stands for its series.
    """
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber

    order = (
        [F("start_datetime").desc(), F("id").desc()]
        if descending
        else [F("start_datetime").asc(), F("id").asc()]
    )
    return (
        qs.annotate(series_group=series_group())
        .annotate(
            series_rank=Window(
                RowNumber(), partition_by=[F("series_group")], order_by=order
            )
        )
        .filter(series_rank=1)
    )


@dataclass
class SeriesCard:
    """What a list card shows about the other dates of its series."""

    count: int  # dates of the series in the listed range
    day_count: int  # distinct days among them
    days: list[dict]  # other days: {"date", "count"}, at most CARD_DAYS
    more_days: int  # other days not named
    last: datetime.date  # last day in range
    times_on_day: int  # dates on the card's own day (incl. its own)
    total: int | None = None  # all listed dates when a date filter is on
    showtimes: list[datetime.datetime] = field(default_factory=list)

    @property
    def outside(self) -> int:
        return max(0, self.total - self.count) if self.total is not None else 0


def attach_series_cards(
    events, dated_qs, *, range_active=False, single_day=False, include_drafts=False
) -> None:
    """Set `series_card` on each event of a listing page that stands for a
    series with other dates (None otherwise).

    *dated_qs* is the listing's queryset before `first_per_series`: the
    dates it holds are the ones a card counts and names. With
    *range_active*, a card also says how many listed dates fall outside
    the range (drafts count only with *include_drafts*).
    """
    from django.db.models import Count

    from .models import hidden_events_q

    events = list(events)
    series_ids = {e.series_id for e in events if e.series_id}
    for event in events:
        event.series_card = None
    if not series_ids:
        return
    dated: dict = defaultdict(list)
    for occurrence in (
        dated_qs.filter(series_id__in=series_ids)
        .select_related(None)
        .order_by("start_datetime", "id")
        .only("start_datetime", "series_id")
    ):
        dated[occurrence.series_id].append(occurrence.start_datetime)
    totals = {}
    if range_active:
        listed = Event.objects.filter(series_id__in=series_ids).exclude(
            hidden_events_q()
        )
        if not include_drafts:
            listed = listed.filter(is_draft=False)
        totals = dict(
            listed.values_list("series_id").annotate(n=Count("id")).order_by()
        )
    for event in events:
        starts = dated.get(event.series_id, [])
        total = totals.get(event.series_id) if range_active else None
        if len(starts) < 2 and not (total and total > 1):
            continue
        days: dict[datetime.date, int] = {}
        for start in starts:
            day = timezone.localtime(start).date()
            days[day] = days.get(day, 0) + 1
        own_day = event.local_start_date
        others = [{"date": d, "count": n} for d, n in days.items() if d != own_day]
        event.series_card = SeriesCard(
            count=len(starts),
            day_count=len(days),
            days=others[:CARD_DAYS],
            more_days=max(0, len(others) - CARD_DAYS),
            last=max(days) if days else own_day,
            times_on_day=days.get(own_day, 1),
            total=total,
            showtimes=[timezone.localtime(s) for s in starts] if single_day else [],
        )
