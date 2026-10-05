#!/bin/bash
# Driver for running pleskal locally and smoke-testing the event flow.
# Usage: driver.sh <setup|seed|start|smoke|stop|full>
#   setup  - uv sync --dev (versions from uv.lock), npm install, build CSS
#   seed   - migrate DB, create a smoke-test user + event
#   start  - start the dev server in the background, write PID to .smoke-server.pid
#   smoke  - curl health, home, search, event detail, iCal feed, login; verify the seeded event appears
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
  # Install exactly what the project pins. uv.lock is the single source of
  # truth for versions - this skill deliberately keeps no dependency list of
  # its own, so upgrades in pyproject.toml/uv.lock need no change here.
  uv sync --dev
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
  local fail=0 code body

  # Fetch each body into a variable before grepping: `curl | grep -q` fails
  # under pipefail whenever grep exits before curl has written everything
  # (curl error 23), which turns a passing check into a FAIL.
  check() {  # check <label> <path> <needle or empty>
    body=$(curl -sS -w '\n%{http_code}' "$base$2")
    code=${body##*$'\n'}
    body=${body%$'\n'*}
    if [ "$code" = "200" ] && { [ -z "$3" ] || grep -qF -- "$3" <<<"$body"; }; then
      echo "PASS $2 -> 200${3:+, contains \"$3\"}"
    else
      echo "FAIL $2 -> $code${3:+ (expected \"$3\")} ($1)"; fail=1
    fi
  }

  check "health check" /health/ ""
  check "home page lists seeded event" / "Smoke Test Event"
  check "search finds seeded event" "/?q=smoke" "Smoke Test Event"
  check "detail page shows title" /events/smoke-test-event/ "Smoke Test Event"
  check "iCal feed has seeded event" /feed/events.ics "SUMMARY:Smoke Test Event"
  check "login page" /accounts/login/ ""

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
