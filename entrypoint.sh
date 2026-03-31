#!/bin/sh
set -ex

echo "=== Starting entrypoint ==="
echo "Python: $(python --version)"
echo "Gunicorn: $(gunicorn --version)"

echo "=== Running migrations ==="
python manage.py migrate --noinput

PORT=${PORT:-8000}

echo "=== Starting gunicorn on port $PORT ==="
exec gunicorn config.wsgi \
  --bind 0.0.0.0:$PORT \
  --workers 2 \
  --timeout 120 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
