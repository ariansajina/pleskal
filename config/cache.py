"""Database cache backend with cheaper writes.

Django's ``DatabaseCache.set`` runs ``SELECT COUNT(*)`` on the whole cache
table before every write (to decide whether to cull), then a ``SELECT`` of the
key and an ``UPDATE`` or ``INSERT``: four queries for each rate-limit counter
bump. This backend writes ``set()`` as one ``INSERT ... ON CONFLICT DO UPDATE``
(PostgreSQL and SQLite) and checks the table size only every
``CULL_CHECK_EVERY`` writes per process. ``add()``, ``touch()`` and the read
path are Django's.
"""

import base64
import pickle
from datetime import UTC, datetime
from itertools import count

from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.db import DatabaseCache as DjangoDatabaseCache
from django.db import connections, router
from django.utils.timezone import now as tz_now


class DatabaseCache(DjangoDatabaseCache):
    # MAX_ENTRIES may be exceeded by up to this many writes between checks.
    CULL_CHECK_EVERY = 50

    def __init__(self, table, params):
        super().__init__(table, params)
        self._writes = count(1)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        key = self.make_and_validate_key(key, version=version)
        timeout = self.get_backend_timeout(timeout)
        db = router.db_for_write(self.cache_model_class)
        connection = connections[db]
        qn = connection.ops.quote_name
        table = qn(self._table)

        if timeout is None:
            exp = datetime.max
        else:
            exp = datetime.fromtimestamp(timeout, tz=UTC if settings.USE_TZ else None)
        exp = connection.ops.adapt_datetimefield_value(exp.replace(microsecond=0))
        pickled = pickle.dumps(value, self.pickle_protocol)
        b64encoded = base64.b64encode(pickled).decode("latin1")

        with connection.cursor() as cursor:
            if next(self._writes) % self.CULL_CHECK_EVERY == 0:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                num = cursor.fetchone()[0]
                if num > self._max_entries:
                    self._cull(db, cursor, tz_now().replace(microsecond=0), num)
            cache_key, val, expires = (
                qn("cache_key"),
                qn("value"),
                qn("expires"),
            )
            cursor.execute(
                f"INSERT INTO {table} ({cache_key}, {val}, {expires}) "  # noqa: S608
                "VALUES (%s, %s, %s) "
                f"ON CONFLICT ({cache_key}) DO UPDATE SET "
                f"{val} = EXCLUDED.{val}, {expires} = EXCLUDED.{expires}",
                [key, b64encoded, exp],
            )
