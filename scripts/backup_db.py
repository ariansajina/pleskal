#!/usr/bin/env python
"""
PostgreSQL database backup script for Railway.

Backs up the database to Cloudflare R2 with gzip compression.
Runs via railway.cron.toml on a scheduled interval.

Environment variables:
  DATABASE_URL: PostgreSQL connection string (set by Railway)
  R2_BUCKET_NAME: Cloudflare R2 bucket name
  R2_ACCESS_KEY: R2 access key ID
  R2_SECRET_KEY: R2 secret access key
  R2_ENDPOINT_URL: R2 endpoint (https://<account_id>.r2.cloudflarestorage.com)
  DB_BACKUP_RETENTION_DAYS: Days to keep backups (default: 30)
  SENTRY_DSN: Optional; reports failures and Sentry Crons check-ins
  SENTRY_ENVIRONMENT, APP_VERSION: Optional Sentry environment / release tags
  SENTRY_CRON_SCHEDULE: Optional; this service's Railway cron schedule, if it
    differs from BACKUP_CRON_SCHEDULE below
"""

import gzip
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import sentry_sdk
from sentry_sdk.crons import monitor

if TYPE_CHECKING:
    from sentry_sdk._types import MonitorConfig

try:
    import boto3
except ImportError:
    print("Error: boto3 not installed. Install with: pip install boto3")
    sys.exit(1)


# Must match the backup-cron service's schedule in the Railway dashboard, or
# Sentry will flag missed check-ins; override with SENTRY_CRON_SCHEDULE.
BACKUP_CRON_SCHEDULE = "0 3 * * *"

# Same monitor config as config/cron_monitoring.py, inlined because this script
# runs outside Django and can't import the config package.
MONITOR_CONFIG: MonitorConfig = {
    "schedule": {
        "type": "crontab",
        "value": os.environ.get("SENTRY_CRON_SCHEDULE") or BACKUP_CRON_SCHEDULE,
    },
    "timezone": "UTC",
    "checkin_margin": 30,
    "max_runtime": 30,
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}


def init_sentry() -> None:
    """Initialize Sentry when SENTRY_DSN is set; otherwise its calls are no-ops."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        environment=os.environ.get("SENTRY_ENVIRONMENT") or None,
        release=os.environ.get("APP_VERSION") or None,
    )


def get_db_url() -> str:
    """Get DATABASE_URL from environment."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set")
    return db_url


def dump_database(db_url: str) -> bytes:
    """Dump PostgreSQL database to bytes."""
    print("Dumping database...")
    try:
        result = subprocess.run(  # noqa: S603
            ["pg_dump", db_url],  # noqa: S607
            capture_output=True,
            check=True,
            shell=False,
            timeout=300,  # 5 minutes
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"pg_dump failed: {e.stderr.decode('utf-8', errors='replace')}"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(
            "pg_dump not found. Ensure PostgreSQL client tools are installed."
        ) from e


def compress_dump(dump_data: bytes) -> bytes:
    """Compress database dump with gzip."""
    print("Compressing dump...")
    compressed = gzip.compress(dump_data, compresslevel=9)
    original_size = len(dump_data) / (1024 * 1024)
    compressed_size = len(compressed) / (1024 * 1024)
    print(f"  Original: {original_size:.1f} MB")
    print(f"  Compressed: {compressed_size:.1f} MB")
    return compressed


def upload_to_r2(
    compressed_dump: bytes, bucket: str, access_key: str, secret_key: str, endpoint: str
) -> str:
    """Upload compressed dump to Cloudflare R2."""
    print("Uploading to R2...")

    s3 = boto3.client(
        "s3",
        region_name="auto",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    key = f"backups/pleskal_{timestamp}.sql.gz"

    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=compressed_dump,
            ContentType="application/gzip",
        )
        print(f"  Uploaded to s3://{bucket}/{key}")
        return key
    except Exception as e:
        raise RuntimeError(f"Failed to upload to R2: {e}") from e


def cleanup_old_backups(
    bucket: str,
    access_key: str,
    secret_key: str,
    endpoint: str,
    retention_days: int = 30,
) -> None:
    """Delete backups older than retention_days."""
    print(f"Cleaning up backups older than {retention_days} days...")

    s3 = boto3.client(
        "s3",
        region_name="auto",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    cutoff_date = datetime.now() - timedelta(days=retention_days)

    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix="backups/")
        if "Contents" not in response:
            print("  No backups to clean up")
            return

        deleted_count = 0
        for obj in response.get("Contents", []):
            obj_key = obj["Key"]
            last_modified = obj["LastModified"].replace(tzinfo=None)

            if last_modified < cutoff_date:
                s3.delete_object(Bucket=bucket, Key=obj_key)
                print(f"  Deleted {obj_key}")
                deleted_count += 1

        if deleted_count == 0:
            print("  No old backups to delete")
    except Exception as e:
        # Report but don't fail the entire backup if cleanup fails
        sentry_sdk.capture_exception(e)
        print(f"  Warning: cleanup failed: {e}")


def main() -> None:
    """Run the backup, reporting the outcome to Sentry Crons."""
    init_sentry()
    # sys.exit inside raises SystemExit, which the monitor records as a failed
    # check-in; Railway itself doesn't alert on a non-zero exit.
    with monitor(monitor_slug="backup-db", monitor_config=MONITOR_CONFIG):
        run_backup()


def run_backup() -> None:
    """Main backup orchestration."""
    print("=" * 60)
    print("pleskal Database Backup")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    # Validate environment
    required_vars = [
        "DATABASE_URL",
        "R2_BUCKET_NAME",
        "R2_ACCESS_KEY",
        "R2_SECRET_KEY",
        "R2_ENDPOINT_URL",
    ]
    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        message = f"Missing environment variables: {', '.join(missing)}"
        print(f"Error: {message}")
        sentry_sdk.capture_message(f"Database backup failed: {message}", "error")
        sys.exit(1)

    db_url = get_db_url()
    r2_bucket = os.environ["R2_BUCKET_NAME"]
    r2_access_key = os.environ["R2_ACCESS_KEY"]
    r2_secret_key = os.environ["R2_SECRET_KEY"]
    r2_endpoint = os.environ["R2_ENDPOINT_URL"]
    retention_days = int(os.environ.get("DB_BACKUP_RETENTION_DAYS", "30"))

    try:
        # Dump, compress, upload
        dump_data = dump_database(db_url)
        compressed_dump = compress_dump(dump_data)
        upload_to_r2(
            compressed_dump, r2_bucket, r2_access_key, r2_secret_key, r2_endpoint
        )

        # Cleanup old backups
        cleanup_old_backups(
            r2_bucket, r2_access_key, r2_secret_key, r2_endpoint, retention_days
        )

        print("=" * 60)
        print("Backup completed successfully")
        print("=" * 60)

    except Exception as e:
        sentry_sdk.capture_exception(e)
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
