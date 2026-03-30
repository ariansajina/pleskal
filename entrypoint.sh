#!/bin/sh
set -e

# Use PORT env var if set, otherwise default to 8000
PORT="${PORT:-8000}"

exec gunicorn config.wsgi \
  --bind 0.0.0.0:"$PORT" \
  --workers 2 \
  --timeout 120 \
  --log-level info
