# CLAUDE.md — Pleskal (Copenhagen Dance Calendar)

## Project Overview

Pleskal is a local-first, crowd-sourced Django web application for discovering and sharing dance events in Copenhagen. Anyone can submit events; approved users can post freely. Community-maintained, editorially neutral.

## Tech Stack

- **Framework:** Django 6.0.3+ (Python 3.13+)
- **Database:** PostgreSQL (production), SQLite (dev default)
- **Frontend:** Django templates + HTMX (no JS framework)
- **Styling:** Tailwind CSS 4.0 (built via CLI)
- **Package manager:** `uv` (Python), `npm` (Tailwind only)
- **Image storage:** Cloudflare R2 (S3-compatible) in production, local filesystem in dev
- **Auth:** Django built-in + django-axes (brute-force protection) + zxcvbn password strength
- **Markdown:** django-markdownx + nh3 sanitization
- **Error tracking:** Sentry (optional)
- **Static files:** WhiteNoise (production)
- **Deployment:** Railway

## Project Structure

```
config/          # Django project settings, URLs, middleware, rate limiting
accounts/        # User management app (custom User model, UUID PK, email-based auth)
events/          # Dance events app (CRUD, moderation, feeds, image processing)
templates/       # Global Django templates (base, accounts, events, partials)
static/          # Static assets (Tailwind input CSS, vendored HTMX)
conftest.py      # pytest-django autouse fixtures (disables SSL, uses simple storage)
spec.md          # Full system specification (authoritative reference)
```

## Commands

### Development

```bash
uv sync --dev                              # Install all dependencies
uv run python manage.py runserver          # Start dev server
npm run css:watch                          # Watch & rebuild Tailwind CSS
uv run python manage.py migrate            # Apply database migrations
uv run python manage.py makemigrations     # Create new migrations
uv run python manage.py createsuperuser    # Create admin user
```

### Testing

```bash
uv run pytest                              # Run all tests (parallel, 4 workers)
uv run pytest --cov                        # Tests with coverage report
uv run pytest --cov --cov-fail-under=90    # Enforce 90% coverage (local)
uv run pytest path/to/test_file.py         # Run specific test file
uv run pytest -k "test_name"               # Run tests matching name
```

- Tests run in parallel via pytest-xdist (`-n 4`)
- `--reuse-db` is on by default; use `--create-db` to force fresh DB
- Coverage minimum: 90% for `events/` and `accounts/` (local), 80% in CI
- Test factories: `accounts/tests/factories.py` (UserFactory), `events/tests/factories.py` (EventFactory)

### Linting & Formatting

```bash
uv run ruff check .                        # Lint
uv run ruff check . --fix                  # Lint with auto-fix
uv run ruff format .                       # Format code
uv run ruff format --check .               # Check formatting
uv run ty check                            # Type checking
pre-commit run --all-files                 # Run all pre-commit hooks
```

### Build (CSS)

```bash
npm run css:build                          # One-time Tailwind build
npm run css:watch                          # Watch mode
```

## Code Conventions

### Style & Linting

- **Line length:** 88 (ruff default)
- **Python target:** 3.13
- **Ruff rules:** E, F, I (isort), UP (pyupgrade), B (bugbear), SIM (simplify); E501 ignored
- **Migrations excluded** from linting
- **Pre-commit hooks:** ruff check+fix, ruff format, check-yaml, check-toml, trailing-whitespace, end-of-file-fixer, ty check

### Architecture Patterns

- **Class-based views** (CBV) with mixins: `DetailView`, `ListView`, `CreateView`, `UpdateView`, `DeleteView`
- **HTMX integration:** Views return full page or partial template based on `HX-Request` header
- **Custom mixins:** `RateLimitMixin` (IP or user-based keying via `rate_limit_by_user`), `EventOwnerOrModeratorMixin`
- **Custom User model:** UUID primary key, email-based authentication
- **Event status workflow:** pending → approved/rejected (admin moderation)

### Naming

- **Views:** PascalCase, suffixed with `View` (e.g., `EventCreateView`)
- **Models:** Singular PascalCase (e.g., `Event`, `User`)
- **Forms:** Suffixed with `Form` (e.g., `EventForm`)
- **Factories:** Suffixed with `Factory` (e.g., `UserFactory`)
- **URL names:** snake_case (e.g., `event_detail`, `my_events`)
- **Templates:** lowercase with underscores (e.g., `event_list.html`)

### Testing

- Use `factory_boy` factories for test data, not raw model creation
- Tests live in `<app>/tests/` directories with `test_*.py` naming
- Each app has `factories.py` for shared test factories
- `conftest.py` (root) provides autouse fixture disabling SSL redirect and using simple storage

### Security

- CSRF protection via Django middleware
- XSS: Markdown sanitized via nh3
- Image uploads: EXIF metadata stripped, resized
- Brute-force: django-axes (5 failures = 30 min lockout)
- Rate limiting: Custom cache-based IP/user limiting (`config/ratelimit.py`)
- CSP: Custom middleware (`config/middleware.py`)

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`:
1. Install uv + Python 3.13
2. `uv sync --dev`
3. `npm ci` + `npm run css:build`
4. `collectstatic --noinput`
5. `ruff check .` (lint)
6. `ruff format --check .` (format)
7. `pytest --cov --cov-fail-under=80 --create-db` (tests with PostgreSQL 16)

## Environment Variables

See `.env.example` for the full list. Key variables:
- `SECRET_KEY` — Django secret key
- `DEBUG` — `true`/`false`
- `ALLOWED_HOSTS` — Comma-separated hostnames
- `DATABASE_URL` — Database connection string (default: `sqlite:///db.sqlite3`)
- `AWS_STORAGE_BUCKET_NAME` — Enables R2 storage when set
- `SENTRY_DSN` — Enables Sentry when set
