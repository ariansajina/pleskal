---
name: run-pleskal
description: Set up, build, run, and smoke-test the pleskal Django app locally (server, migrations, curl-based event flow). Use when asked to run pleskal, start the dev server, seed test data, or verify a change works end-to-end.
---

Paths below are relative to the repo root (`<unit>/`), not this skill
directory. The driver is `.claude/skills/run-pleskal/driver.sh`.

## Run (agent path) — use the driver

```bash
.claude/skills/run-pleskal/driver.sh full     # setup + seed + start + smoke + stop
```

Individual steps (useful when iterating):

```bash
.claude/skills/run-pleskal/driver.sh setup    # create .venv, install deps, build CSS
.claude/skills/run-pleskal/driver.sh seed     # migrate + create a smoke-test user/event
.claude/skills/run-pleskal/driver.sh start    # start dev server on :8000 in background
.claude/skills/run-pleskal/driver.sh smoke    # curl the home page, detail page, iCal feed
.claude/skills/run-pleskal/driver.sh stop     # kill the background server
```

`smoke` PASS/FAIL output checks: `/health/` returns 200, the home page
lists the seeded "Smoke Test Event", its detail page
(`/events/smoke-test-event/`) returns 200 and shows the title, the
iCal feed (`/feed/events.ics`) contains a `SUMMARY:Smoke Test Event`
line, and `/accounts/login/` returns 200. Server logs go to
`/tmp/pleskal-smoke-server.log`; the PID is tracked in
`.smoke-server.pid`.

To poke further by hand once `start` is running: `curl` any URL under
`http://127.0.0.1:8000/`, or `.venv/bin/python manage.py shell` for
direct model access (see the seed step in `driver.sh` for the pattern:
`accounts.models.User`, `events.models.Event`).

## Prerequisites

- `uv` (already on PATH in this environment)
- `npm` (for the Tailwind CSS build)
- No Postgres needed — the driver uses SQLite (`DATABASE_URL=sqlite:///db.sqlite3`).
  Full-text search doesn't work on SQLite, but the rest of the app does.

## Build

`driver.sh setup` does this; the commands, verified in this container:

```bash
uv venv --python 3.13 .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install --ignore-requires-python \
  "django>=6.0.3" "psycopg[binary]>=3.2" "django-markdownx>=4.0" "nh3>=0.2" \
  "django-storages[boto3]>=1.14" "django-axes>=7.0" "django-environ>=0.12" \
  "pillow>=12.2.0" "gunicorn>=23.0" "sentry-sdk[django]>=2.0" "whitenoise>=6.8" \
  "icalendar>=6.0" "pytest-xdist>=3.8.0" "zxcvbn>=4.4" "requests>=2.32.5" \
  "beautifulsoup4>=4.14.3" "lxml>=6.0.2" "django-anymail[resend]>=10.0" \
  "markdownify>=1.2.2" "django-allauth>=65.15.0" "argon2-cffi>=25.1.0" \
  "resend>=2.26.0" "pillow-heif>=1.3.0" \
  "ruff>=0.9" "pytest>=8.0" "pytest-django>=4.9" "pytest-cov>=6.0" \
  "factory-boy>=3.3" "ty>=0.0.23" "pre-commit>=4.0"
npm install
npm run css:build
```

## Run (human path)

```bash
source .venv/bin/activate
export SECRET_KEY=dev PASSWORD_PEPPER=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
       DEBUG=true ALLOWED_HOSTS=localhost,127.0.0.1 DATABASE_URL=sqlite:///db.sqlite3 \
       SITE_DOMAIN=localhost:8000 SITE_NAME=pleskal \
       DEFAULT_FROM_EMAIL="pleskal <onboarding@resend.dev>" SERVER_EMAIL="pleskal <onboarding@resend.dev>"
python manage.py migrate
python manage.py runserver 8000
```

Opens on `http://localhost:8000/`; `Ctrl-C` to stop. Same env vars as
the driver — see `.env.example` for the full list (R2/Sentry/Resend
are all optional and unset here).

## Gotchas

- **`pyproject.toml` requires `python>=3.14`, but `uv sync` can't get
  there in a network-restricted sandbox.** `uv sync`/`uv python install`
  fetch a standalone CPython 3.14 build from a GitHub release URL
  (`github.com/astral-sh/python-build-standalone/...`); this
  environment's outbound proxy only allowlists `pypi.org` /
  `files.pythonhosted.org` (see `/root/.ccr/README.md`), so that
  download 403s. `apt-get install python3.14` also fails the same way
  — it comes from the `deadsnakes` PPA, not Ubuntu's own repos, and
  that host isn't allowlisted either. Workaround: build the venv on
  the system's Python 3.13 (`uv venv --python 3.13 .venv`) and install
  deps with `pip install --ignore-requires-python` instead of
  `uv sync`/`uv pip install -e .` — the app runs fine on 3.13, the
  `>=3.14` floor is aspirational/CI-only (CI itself installs Python
  3.13 via `actions/setup-python`, so this isn't even inconsistent
  with what actually ships).
- **Don't `pip install -e .`** — setuptools refuses with "Multiple
  top-level packages discovered in a flat-layout" because this repo
  has no `[tool.setuptools]` package config (it's a Django app, not a
  distributable package; `manage.py` puts the repo root on
  `sys.path` directly). Install the dependency list directly instead
  (see Build above) — nothing needs the `pleskal` project itself
  "installed".
- **`ensurepip` in a fresh `uv venv`**: `uv venv` does not bundle pip.
  Run `.venv/bin/python -m ensurepip --upgrade` once before any `pip
  install` in that venv, or `uv pip install` fails resolving
  `requires-python` the same way `uv sync` does (see above) — plain
  `pip` with `--ignore-requires-python` is the only installer that
  will take a 3.13 interpreter here.
- **No `PASSWORD_PEPPER` / `SECRET_KEY` in `.env` locally** → Django
  raises on startup. The driver generates a throwaway pepper and uses
  a fixed dev secret key; don't reuse these for anything real.
- Search (`?q=`) silently returns nothing on SQLite — Postgres-only
  feature. Not a bug if you're testing on the SQLite fallback.

## Troubleshooting

- `ModuleNotFoundError: No module named 'pip'` right after `uv venv` →
  run `.venv/bin/python -m ensurepip --upgrade` first.
- `error: Multiple top-level packages discovered in a flat-layout` →
  you ran `pip install -e .`; don't — see Gotchas above.
- `Because the current Python version (3.13.12) does not satisfy
  Python>=3.14 ... cannot be used` → you used `uv sync` or `uv pip
  install -e .` (both enforce `requires-python`); use `pip install
  --ignore-requires-python <deps>` instead.
- Server up but `/` 500s with a settings error mentioning
  `PASSWORD_PEPPER` or `SECRET_KEY` → export them before
  `runserver`/`migrate` (see Run (human path) above).
