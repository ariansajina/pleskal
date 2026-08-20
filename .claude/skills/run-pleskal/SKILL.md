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
.claude/skills/run-pleskal/driver.sh setup    # uv sync --dev (versions from uv.lock), build CSS
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
uv sync --dev
npm install
npm run css:build
```

`uv sync --dev` creates `.venv` and installs the exact versions in
`uv.lock`. **This skill deliberately keeps no dependency list of its
own** — the project's `pyproject.toml`/`uv.lock` are the single source
of truth, so dependency upgrades need no change here. If you find
yourself about to paste package names or version pins into this file or
into `driver.sh`, don't: fix the project's lockfile instead.

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

- **Don't `pip install -e .`** — setuptools refuses with "Multiple
  top-level packages discovered in a flat-layout" because this repo
  has no `[tool.setuptools]` package config (it's a Django app, not a
  distributable package; `manage.py` puts the repo root on `sys.path`
  directly). `uv sync --dev` is the supported path and does not try to
  build the project itself.
- **`requires-python` decides which interpreter `uv sync` needs.** It
  is `>=3.13` and the container's system Python satisfies it, so the
  sync resolves locally. If it is ever raised above the interpreters
  available here, `uv sync`/`uv python install` will try to fetch a
  standalone CPython from a GitHub release URL
  (`github.com/astral-sh/python-build-standalone/...`) and 403 — this
  environment's proxy only allowlists `pypi.org` /
  `files.pythonhosted.org` (see `/root/.ccr/README.md`). The fix is to
  make a satisfying interpreter available, not to re-pin dependencies
  here.
- **No `PASSWORD_PEPPER` / `SECRET_KEY` in `.env` locally** → Django
  raises on startup. The driver generates a throwaway pepper and uses
  a fixed dev secret key; don't reuse these for anything real.
- Search (`?q=`) silently returns nothing on SQLite — Postgres-only
  feature. Not a bug if you're testing on the SQLite fallback.

## Troubleshooting

- `error: Multiple top-level packages discovered in a flat-layout` →
  you ran `pip install -e .`; don't — use `uv sync --dev`, see Gotchas
  above.
- `Because the current Python version ... does not satisfy
  Python>=X ... cannot be used` → the project's `requires-python` is
  above every interpreter uv can find, and it cannot download one here.
  See the `requires-python` gotcha above; don't work around it by
  installing packages by hand.
- Stale packages after a dependency change (`ModuleNotFoundError`, an
  unexpected version) → re-run `driver.sh setup`. `uv sync --dev`
  reconciles `.venv` with `uv.lock`, adding and removing as needed.
- Server up but `/` 500s with a settings error mentioning
  `PASSWORD_PEPPER` or `SECRET_KEY` → export them before
  `runserver`/`migrate` (see Run (human path) above).
