#!/bin/sh
set -e

echo "[entrypoint] Starting application..."
echo "[entrypoint] Python version: $(python --version)"
echo "[entrypoint] Gunicorn version: $(gunicorn --version)"

# Use PORT env var if set, otherwise default to 8000
PORT="${PORT:-8000}"
echo "[entrypoint] Using PORT: $PORT"

# Run migrations
echo "[entrypoint] Running database migrations..."
uv run python manage.py migrate --noinput || {
  echo "[entrypoint] Migration failed!"
  exit 1
}

echo "[entrypoint] Migrations completed successfully"
echo "[entrypoint] Starting gunicorn..."

exec gunicorn config.wsgi \
  --bind 0.0.0.0:"$PORT" \
  --workers 2 \
  --timeout 120 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
