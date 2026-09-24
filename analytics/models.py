"""Cookieless, aggregate-only site analytics.

Nothing here identifies a visitor: page views, referrers, searches and filter
usage are stored as per-day counters. The only per-visitor data is the salted
hash in ``VisitorHash``, used to count unique visitors per day; the salt and
the hashes are deleted when the day rolls over (see
``analytics.middleware._daily_salt``), after which the day's count can no
longer be linked back to anyone.
"""

from django.db import models
from django.db.models import F
from django.utils import timezone


class DailyCount(models.Model):
    """A per-day counter for one (kind, key) pair, e.g. ("page", "/about/")."""

    PAGE = "page"
    VISITORS = "visitors"
    REFERRER = "referrer"
    SEARCH = "search"
    FILTER = "filter"
    CALENDAR = "calendar"
    KIND_CHOICES = [
        (PAGE, "Page view"),
        (VISITORS, "Unique visitors"),
        (REFERRER, "Referrer"),
        (SEARCH, "Search"),
        (FILTER, "Filter"),
        (CALENDAR, "Calendar download"),
    ]

    objects = models.Manager()

    date = models.DateField()
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    key = models.CharField(max_length=255, blank=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "kind", "key"], name="unique_daily_count"
            )
        ]
        indexes = [models.Index(fields=["kind", "date"])]

    def __str__(self):
        return f"{self.date} {self.kind} {self.key!r}: {self.count}"

    @classmethod
    def increment(cls, kind: str, key: str = "") -> None:
        """Atomically add one to today's counter."""
        cls.objects.update_or_create(
            date=timezone.localdate(),
            kind=kind,
            key=key,
            create_defaults={"count": 1},
            defaults={"count": F("count") + 1},
        )

    @classmethod
    def decrement(cls, kind: str, key: str = "") -> None:
        """Atomically subtract one from today's counter, never going below 0."""
        cls.objects.filter(
            date=timezone.localdate(), kind=kind, key=key, count__gt=0
        ).update(count=F("count") - 1)


class DailySalt(models.Model):
    """Random salt for today's visitor hashes; deleted once the day is over."""

    objects = models.Manager()

    date = models.DateField(unique=True)
    salt = models.CharField(max_length=64)

    def __str__(self):
        return f"salt for {self.date}"


class VisitorHash(models.Model):
    """Salted hash of (IP, User-Agent) seen today; deleted with the salt."""

    objects = models.Manager()

    date = models.DateField()
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "digest"], name="unique_visitor_hash"
            )
        ]

    def __str__(self):
        return f"visitor {self.digest} on {self.date}"
