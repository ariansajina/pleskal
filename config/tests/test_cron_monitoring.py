"""Tests for the Sentry Crons monitor helper."""

from config.cron_monitoring import CHECKIN_MARGIN_MINUTES, cron_monitor


def test_monitor_config(monkeypatch):
    monkeypatch.delenv("SENTRY_CRON_SCHEDULE", raising=False)

    m = cron_monitor("run-scrapers", "0 6 * * *", max_runtime_minutes=60)

    assert m.monitor_slug == "run-scrapers"
    assert m.monitor_config == {
        "schedule": {"type": "crontab", "value": "0 6 * * *"},
        "timezone": "UTC",
        "checkin_margin": CHECKIN_MARGIN_MINUTES,
        "max_runtime": 60,
        "failure_issue_threshold": 1,
        "recovery_threshold": 1,
    }


def test_schedule_env_override(monkeypatch):
    monkeypatch.setenv("SENTRY_CRON_SCHEDULE", "0 6,18 * * *")

    m = cron_monitor("run-scrapers", "0 6 * * *", max_runtime_minutes=60)

    assert m.monitor_config is not None
    assert m.monitor_config["schedule"] == {
        "type": "crontab",
        "value": "0 6,18 * * *",
    }
