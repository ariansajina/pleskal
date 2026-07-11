#!/bin/bash
# Driver for running pleskal locally and smoke-testing the event flow.
# Usage: driver.sh <setup|seed|start|smoke|stop|full>
#   setup  - create .venv (py3.13, --ignore-requires-python) + install deps, build CSS
#   seed   - migrate DB, create a smoke-test user + event
#   start  - start the dev server in the background, write PID to .smoke-server.pid
#   smoke  - curl the home page, event detail, and iCal feed; verify the seeded event appears
#   stop   - kill the background dev server
#   full   - setup + seed + start + smoke + stop (default end-to-end run)
set -euo pipefail
cd "$(dirname "$0")/../../.."   # repo root (this file lives in .claude/skills/run-pleskal/)

VENV=.venv
PORT=8000
PIDFILE=.smoke-server.pid
LOGFILE=/tmp/pleskal-smoke-server.log
DB=db.sqlite3

export SECRET_KEY="${SECRET_KEY:-dev-secret-key-not-for-production}"
export PASSWORD_PEPPER="${PASSWORD_PEPPER:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
export DEBUG="${DEBUG:-true}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-localhost,127.0.0.1}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$DB}"
export SITE_DOMAIN="${SITE_DOMAIN:-localhost:$PORT}"
export SITE_NAME="${SITE_NAME:-pleskal}"
export DEFAULT_FROM_EMAIL="${DEFAULT_FROM_EMAIL:-pleskal <onboarding@resend.dev>}"
export SERVER_EMAIL="${SERVER_EMAIL:-pleskal <onboarding@resend.dev>}"

PY="$VENV/bin/python"

do_setup() {
  # pyproject.toml requires-python is >=3.14, which uv can only satisfy by
  # downloading a standalone interpreter from a GitHub release URL. In
  # network-restricted sandboxes that download is blocked (403), so build a
  # 3.13 venv directly and force the install past the version guard - the
  # app itself runs fine on 3.13.
  if [ ! -x "$PY" ]; then
    uv venv --python 3.13 "$VENV"
    "$PY" -m ensurepip --upgrade >/dev/null
  fi
  "$PY" -m pip install -q --ignore-requires-python \
    "django>=6.0.3" "psycopg[binary]>=3.2" "django-markdownx>=4.0" "nh3>=0.2" \
    "django-storages[boto3]>=1.14" "django-axes>=7.0" "django-environ>=0.12" \
    "pillow>=12.2.0" "gunicorn>=23.0" "sentry-sdk[django]>=2.0" "whitenoise>=6.8" \
    "icalendar>=6.0" "pytest-xdist>=3.8.0" "zxcvbn>=4.4" "requests>=2.32.5" \
    "beautifulsoup4>=4.14.3" "lxml>=6.0.2" "django-anymail[resend]>=10.0" \
    "markdownify>=1.2.2" "django-allauth>=65.15.0" "argon2-cffi>=25.1.0" \
    "resend>=2.26.0" "pillow-heif>=1.3.0" \
    "ruff>=0.9" "pytest>=8.0" "pytest-django>=4.9" "pytest-cov>=6.0" \
    "factory-boy>=3.3" "ty>=0.0.23" "pre-commit>=4.0"
  npm install --silent
  npm run css:build --silent
  echo "setup: OK"
}

do_seed() {
  "$PY" manage.py migrate --noinput
  "$PY" manage.py shell -c "
from accounts.models import User
from events.models import Event, EventCategory
from django.utils import timezone
import datetime
u, created = User.objects.get_or_create(email='smoke@example.com', defaults={'display_name': 'Smoke Tester'})
if created:
    u.set_password('smoketestpass123')
    u.save()
e, _ = Event.objects.get_or_create(
    title='Smoke Test Event',
    defaults=dict(
        description='A test event for smoke testing',
        start_datetime=timezone.now() + datetime.timedelta(days=1),
        venue_name='Test Venue',
        category=EventCategory.PERFORMANCE,
        is_free=True,
        submitted_by=u,
    ),
)
print('seed: user=' + u.email + ' event_slug=' + e.slug)
"
}

do_start() {
  "$PY" manage.py runserver "$PORT" > "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 20); do
    if curl -sS -o /dev/null "http://127.0.0.1:$PORT/health/" 2>/dev/null; then
      echo "start: OK (pid $(cat "$PIDFILE"), log $LOGFILE)"
      return 0
    fi
    sleep 0.5
  done
  echo "start: server did not come up, see $LOGFILE" >&2
  cat "$LOGFILE" >&2
  exit 1
}

do_smoke() {
  local base="http://127.0.0.1:$PORT"
  local fail=0

  code=$(curl -sS -o /dev/null -w "%{http_code}" "$base/health/")
  [ "$code" = "200" ] && echo "PASS /health/ -> 200" || { echo "FAIL /health/ -> $code"; fail=1; }

  if curl -sS "$base/" | grep -q "Smoke Test Event"; then
    echo "PASS / lists seeded event"
  else
    echo "FAIL / does not list seeded event"; fail=1
  fi

  code=$(curl -sS -o /dev/null -w "%{http_code}" "$base/events/smoke-test-event/")
  if [ "$code" = "200" ] && curl -sS "$base/events/smoke-test-event/" | grep -q "Smoke Test Event"; then
    echo "PASS /events/smoke-test-event/ -> 200, shows title"
  else
    echo "FAIL /events/smoke-test-event/ -> $code"; fail=1
  fi

  if curl -sS "$base/feed/events.ics" | grep -q "SUMMARY:Smoke Test Event"; then
    echo "PASS /feed/events.ics contains seeded event"
  else
    echo "FAIL /feed/events.ics missing seeded event"; fail=1
  fi

  code=$(curl -sS -o /dev/null -w "%{http_code}" "$base/accounts/login/")
  [ "$code" = "200" ] && echo "PASS /accounts/login/ -> 200" || { echo "FAIL /accounts/login/ -> $code"; fail=1; }

  return $fail
}

do_stop() {
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  echo "stop: OK"
}

case "${1:-full}" in
  setup) do_setup ;;
  seed) do_seed ;;
  start) do_start ;;
  smoke) do_smoke ;;
  stop) do_stop ;;
  full)
    do_setup
    do_seed
    do_start
    trap do_stop EXIT
    do_smoke
    ;;
  *) echo "usage: $0 <setup|seed|start|smoke|stop|full>" >&2; exit 1 ;;
esac
