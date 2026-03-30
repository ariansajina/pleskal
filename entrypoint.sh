#!/bin/sh
set -ex

echo "=== Starting entrypoint ==="
echo "Python: $(python --version)"
echo "Gunicorn: $(gunicorn --version)"

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Starting gunicorn on port 8000 ==="
# Railway sets PORT via startCommand substitution, but when running Docker directly,
# we use 8000. Railway's startCommand will override the CMD anyway.
exec gunicorn config.wsgi \
  --bind 0.0.0.0:8080 \
  --workers 2 \
  --timeout 120 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
