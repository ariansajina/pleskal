"""Read-side helpers shared by the stats dashboard and the weekly digest."""

import datetime
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.urls import Resolver404, resolve

from events.models import Event, EventCategory, FeedHit

from .models import DailyCount

PAGE_LABELS = {
    "event_list": "Event list (home)",
    "event_map": "Map",
    "subscribe": "Subscribe",
    "about": "About",
    "guide": "Guide",
    "event_create": "Submit event",
    "claim": "Claim invite code",
    "claim_register": "Register",
    "login": "Log in",
}

FILTER_LABELS = {
    "is_free": "Free events",
    "is_wheelchair_accessible": "Wheelchair accessible",
    "past": "Past events",
    "date_range": "Date range",
}


@dataclass
class Row:
    label: str
    count: int
    path: str = ""


def date_range(days: int, end: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Return the inclusive (start, end) covering the last ``days`` days."""
    return end - datetime.timedelta(days=days - 1), end


def _counts(start, end):
    return DailyCount.objects.filter(date__gte=start, date__lte=end)


def totals(start, end) -> dict[str, int]:
    """Summed count per kind over the period (missing kinds are 0)."""
    rows = (
        _counts(start, end)
        .values("kind")
        .annotate(total=Sum("count"))
        .values_list("kind", "total")
    )
    result = {kind: 0 for kind, _ in DailyCount.KIND_CHOICES}
    result.update(rows)
    result["feeds"] = (
        FeedHit.objects.filter(date__gte=start, date__lte=end).aggregate(
            total=Sum("count")
        )["total"]
        or 0
    )
    return result


def daily_series(start, end) -> list[dict]:
    """One entry per day: {"date", "views", "visitors"} (zeros for gaps)."""
    rows = (
        _counts(start, end)
        .filter(kind__in=[DailyCount.PAGE, DailyCount.VISITORS])
        .values("date", "kind")
        .annotate(total=Sum("count"))
    )
    by_day = {}
    for row in rows:
        by_day.setdefault(row["date"], {})[row["kind"]] = row["total"]
    series = []
    day = start
    while day <= end:
        counts = by_day.get(day, {})
        series.append(
            {
                "date": day,
                "views": counts.get(DailyCount.PAGE, 0),
                "visitors": counts.get(DailyCount.VISITORS, 0),
            }
        )
        day += datetime.timedelta(days=1)
    return series


def _top(start, end, kind, limit):
    return list(
        _counts(start, end)
        .filter(kind=kind)
        .values("key")
        .annotate(total=Sum("count"))
        .filter(total__gt=0)
        .order_by("-total", "key")
        .values_list("key", "total")[:limit]
    )


def _path_labels(paths) -> dict[str, str]:
    """Human-readable labels for counted paths (event titles, page names)."""
    resolved = {}
    for path in paths:
        try:
            resolved[path] = resolve(path)
        except Resolver404:
            continue
    event_slugs = {
        m.kwargs["slug"]
        for m in resolved.values()
        if m.url_name in {"event_detail", "event_ical_single"}
    }
    publisher_slugs = {
        m.kwargs["slug"] for m in resolved.values() if m.url_name == "publisher_profile"
    }
    event_titles = dict(
        Event.objects.filter(slug__in=event_slugs).values_list("slug", "title")
    )
    publisher_names = dict(
        get_user_model()
        .objects.filter(display_name_slug__in=publisher_slugs)
        .values_list("display_name_slug", "display_name")
    )

    labels = {}
    for path in paths:
        match = resolved.get(path)
        label = path
        if match is None:
            pass
        elif match.url_name in {"event_detail", "event_ical_single"}:
            label = event_titles.get(match.kwargs["slug"], path)
        elif match.url_name == "publisher_profile":
            name = publisher_names.get(match.kwargs["slug"])
            label = f"Publisher: {name}" if name else path
        else:
            label = PAGE_LABELS.get(match.url_name, path)
        labels[path] = label
    return labels


def top_pages(start, end, limit=10, kind=DailyCount.PAGE) -> list[Row]:
    top = _top(start, end, kind, limit)
    labels = _path_labels([key for key, _ in top])
    return [Row(label=labels[key], count=total, path=key) for key, total in top]


def top_referrers(start, end, limit=10) -> list[Row]:
    return [
        Row(label=key, count=total)
        for key, total in _top(start, end, DailyCount.REFERRER, limit)
    ]


def top_searches(start, end, limit=10) -> list[Row]:
    return [
        Row(label=key, count=total)
        for key, total in _top(start, end, DailyCount.SEARCH, limit)
    ]


def filter_label(key: str) -> str:
    if key.startswith("category:"):
        value = key.removeprefix("category:")
        labels = dict(EventCategory.choices)
        return f"Category: {labels.get(value, value)}"
    if key.startswith("publisher:"):
        return f"Publisher: {key.removeprefix('publisher:')}"
    return FILTER_LABELS.get(key, key)


def top_filters(start, end, limit=10) -> list[Row]:
    return [
        Row(label=filter_label(key), count=total)
        for key, total in _top(start, end, DailyCount.FILTER, limit)
    ]
