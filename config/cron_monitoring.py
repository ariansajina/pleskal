"""Sentry Crons check-ins for the scheduled Railway jobs.

Railway doesn't alert when a cron job exits non-zero, and capturing exceptions
only helps if the job starts at all. Wrapping each job in a Sentry Crons
monitor covers both: Sentry opens an issue when a check-in reports an error,
runs past ``max_runtime``, or never arrives.

The monitor is created (or updated) in Sentry from ``monitor_config`` on the
first check-in, so no manual setup is needed there. The schedule has to match
the job's Railway cron schedule, which lives in the Railway dashboard; set
``SENTRY_CRON_SCHEDULE`` on the cron service to override the default here
when the two differ.

Every call is a no-op when Sentry is not initialized (``SENTRY_DSN`` unset).
``scripts/backup_db.py`` runs outside Django and can't import this module, so
it inlines the same config.
"""

import os

from sentry_sdk.crons import monitor

# Minutes after the scheduled time before a check-in that hasn't arrived is
# counted as missed. Railway cron starts can lag by several minutes.
CHECKIN_MARGIN_MINUTES = 30


def cron_monitor(slug: str, schedule: str, max_runtime_minutes: int) -> monitor:
    """Return a context manager that reports a run to the Sentry cron ``slug``."""
    schedule = os.environ.get("SENTRY_CRON_SCHEDULE") or schedule
    return monitor(
        monitor_slug=slug,
        monitor_config={
            "schedule": {"type": "crontab", "value": schedule},
            "timezone": "UTC",
            "checkin_margin": CHECKIN_MARGIN_MINUTES,
            "max_runtime": max_runtime_minutes,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
        },
    )
