#!/bin/sh
set -ex

echo "=== Starting entrypoint ==="
echo "PORT=${PORT:-8000}"
echo "Python: $(python --version)"
echo "Gunicorn: $(gunicorn --version)"

PORT="${PORT:-8000}"

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Starting gunicorn on port $PORT ==="
exec gunicorn config.wsgi \
  --bind 0.0.0.0:"$PORT" \
  --workers 2 \
  --timeout 120 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
