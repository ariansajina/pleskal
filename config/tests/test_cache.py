"""Tests for config.cache.DatabaseCache (single-statement set)."""

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from config.cache import DatabaseCache

TABLE = "test_pleskal_cache"


def _row_count():
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(TABLE)}")  # noqa: S608
        return cursor.fetchone()[0]


@pytest.fixture
def db_cache(db):
    call_command("createcachetable", TABLE, verbosity=0)
    yield DatabaseCache(TABLE, {"OPTIONS": {"MAX_ENTRIES": 3, "CULL_FREQUENCY": 2}})
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE {connection.ops.quote_name(TABLE)}")


def test_set_get_and_overwrite(db_cache):
    db_cache.set("k", {"a": 1}, 60)
    assert db_cache.get("k") == {"a": 1}
    db_cache.set("k", 2, 60)
    assert db_cache.get("k") == 2


def test_set_is_one_query(db_cache):
    db_cache.set("k", 1, 60)
    with CaptureQueriesContext(connection) as queries:
        db_cache.set("k", 2, 60)
    assert len(queries) == 1
    assert "COUNT" not in queries[0]["sql"]


def test_set_without_timeout_never_expires(db_cache):
    db_cache.set("forever", "x", None)
    assert db_cache.get("forever") == "x"


def test_expired_entries_are_misses(db_cache):
    db_cache.set("gone", 1, -1)
    assert db_cache.get("gone") is None


def test_add_and_delete_still_work(db_cache):
    assert db_cache.add("lock", 1, 60) is True
    assert db_cache.add("lock", 1, 60) is False
    db_cache.delete("lock")
    assert db_cache.add("lock", 1, 60) is True


def test_culls_on_every_nth_write(db_cache):
    db_cache.CULL_CHECK_EVERY = 5
    for i in range(10):
        db_cache.set(f"k{i}", i, 60)
    assert _row_count() < 10
