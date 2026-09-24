"""Tests for scripts/backup_db.py's failure reporting.

The script runs outside Django (the backup-cron service), so it's loaded from
its path rather than imported as a package.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "backup_db.py"

R2_ENV = {
    "DATABASE_URL": "postgres://localhost/pleskal",
    "R2_BUCKET_NAME": "bucket",
    "R2_ACCESS_KEY": "key",
    "R2_SECRET_KEY": "secret",
    "R2_ENDPOINT_URL": "https://r2.example.com",
}


@pytest.fixture
def backup_db():
    spec = importlib.util.spec_from_file_location("backup_db", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkins(monkeypatch):
    """Record the statuses of Sentry Crons check-ins instead of sending them."""
    statuses = []
    monkeypatch.setattr(
        "sentry_sdk.crons.decorator.capture_checkin",
        lambda **kwargs: statuses.append(kwargs["status"]),
    )
    return statuses


@pytest.fixture
def r2_env(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    for name, value in R2_ENV.items():
        monkeypatch.setenv(name, value)


def test_success_checks_in_ok(backup_db, checkins, r2_env, monkeypatch):
    monkeypatch.setattr(backup_db, "dump_database", lambda url: b"dump")
    monkeypatch.setattr(backup_db, "upload_to_r2", lambda *args: "key")
    monkeypatch.setattr(backup_db, "cleanup_old_backups", lambda *args: None)

    backup_db.main()

    assert checkins == ["in_progress", "ok"]


def test_dump_failure_is_reported(backup_db, checkins, r2_env, monkeypatch):
    boom = RuntimeError("pg_dump failed")

    def failing_dump(url):
        raise boom

    captured = []
    monkeypatch.setattr(backup_db, "dump_database", failing_dump)
    monkeypatch.setattr(backup_db.sentry_sdk, "capture_exception", captured.append)

    with pytest.raises(SystemExit) as exc_info:
        backup_db.main()

    assert exc_info.value.code == 1
    assert captured == [boom]
    assert checkins == ["in_progress", "error"]


def test_missing_env_is_reported(backup_db, checkins, monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    for name in R2_ENV:
        monkeypatch.delenv(name, raising=False)
    messages = []
    monkeypatch.setattr(
        backup_db.sentry_sdk,
        "capture_message",
        lambda message, level: messages.append(message),
    )

    with pytest.raises(SystemExit):
        backup_db.main()

    assert len(messages) == 1
    assert "DATABASE_URL" in messages[0]
    assert checkins == ["in_progress", "error"]


def test_cleanup_failure_is_reported_but_not_fatal(
    backup_db, checkins, r2_env, monkeypatch
):
    boom = RuntimeError("list failed")

    class FailingS3:
        def list_objects_v2(self, **kwargs):
            raise boom

    captured = []
    monkeypatch.setattr(backup_db.boto3, "client", lambda *args, **kwargs: FailingS3())
    monkeypatch.setattr(backup_db.sentry_sdk, "capture_exception", captured.append)

    backup_db.cleanup_old_backups("bucket", "key", "secret", "https://r2.example.com")

    assert captured == [boom]
