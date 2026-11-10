"""Single-statement counter writes for PostgreSQL and SQLite.

``update_or_create(..., defaults={"count": F("count") + 1})`` costs a
``SELECT ... FOR UPDATE`` plus an ``UPDATE`` or ``INSERT`` (and savepoints)
per call. Counters written on every page view or feed poll use one
``INSERT ... ON CONFLICT`` instead, which both supported databases (PostgreSQL,
SQLite >= 3.24) understand and which is atomic on its own.
"""

from django.db import connections, router


def _columns_and_params(model, values: dict, connection):
    columns, params = [], []
    for name, value in values.items():
        field = model._meta.get_field(name)
        columns.append(connection.ops.quote_name(field.column))
        params.append(field.get_db_prep_save(value, connection))
    return columns, params


def increment_counter(model, lookup: dict, field: str = "count") -> None:
    """Add one to *model*'s *field* on the row matching *lookup*, creating the
    row with 1 when it doesn't exist. *lookup*'s fields must be exactly a
    unique constraint of *model*."""
    db = router.db_for_write(model)
    connection = connections[db]
    qn = connection.ops.quote_name
    table = qn(model._meta.db_table)
    columns, params = _columns_and_params(model, lookup, connection)
    counter = qn(model._meta.get_field(field).column)
    placeholders = ", ".join(["%s"] * (len(columns) + 1))
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}, {counter}) "  # noqa: S608
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(columns)}) "
        f"DO UPDATE SET {counter} = {table}.{counter} + 1"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [*params, 1])


def insert_if_absent(model, values: dict) -> bool:
    """Insert a *model* row with *values* unless it would violate a unique
    constraint. Returns True when a row was inserted."""
    db = router.db_for_write(model)
    connection = connections[db]
    table = connection.ops.quote_name(model._meta.db_table)
    columns, params = _columns_and_params(model, values, connection)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "  # noqa: S608
        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount == 1
