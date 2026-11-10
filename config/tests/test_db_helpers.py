"""Tests for config.db single-statement counter writes."""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from analytics.models import DailyCount, VisitorHash
from config.db import increment_counter, insert_if_absent
from events.models import FeedHit

DAY = datetime.date(2026, 1, 2)


@pytest.mark.django_db
class TestIncrementCounter:
    def test_creates_then_increments_in_one_query_each(self):
        lookup = {"date": DAY, "kind": "page", "key": "/"}
        for expected in (1, 2, 3):
            with CaptureQueriesContext(connection) as queries:
                increment_counter(DailyCount, lookup)
            assert len(queries) == 1
            assert DailyCount.objects.get(**lookup).count == expected

    def test_rows_are_per_lookup(self):
        increment_counter(FeedHit, {"feed_type": "ical", "date": DAY})
        increment_counter(FeedHit, {"feed_type": "rss", "date": DAY})
        increment_counter(FeedHit, {"feed_type": "ical", "date": DAY})
        counts = dict(FeedHit.objects.values_list("feed_type", "count"))
        assert counts == {"ical": 2, "rss": 1}


@pytest.mark.django_db
class TestInsertIfAbsent:
    def test_reports_whether_a_row_was_inserted(self):
        values = {"date": DAY, "digest": "a" * 64}
        assert insert_if_absent(VisitorHash, values) is True
        assert insert_if_absent(VisitorHash, values) is False
        assert VisitorHash.objects.count() == 1
