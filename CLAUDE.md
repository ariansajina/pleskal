# CLAUDE.md — pleskal (Copenhagen Dance Calendar)

## Project Overview

pleskal is a local-first, crowd-sourced Django web application for discovering and sharing dance events in Copenhagen. Anyone can submit events. Community-maintained, editorially neutral.

Inspired by [dukop.dk](https://dukop.dk). Designed for low operational cost and complexity.

## Tech Stack

- **Framework:** Django 6.0.3+ (Python 3.13+)
- **Database:** PostgreSQL (production), SQLite (dev default)
- **Frontend:** Django templates + HTMX (no JS framework)
- **Styling:** Tailwind CSS 4.0 (built via CLI)
- **Package manager:** `uv` (Python), `npm` (Tailwind only)
- **Image storage:** Cloudflare R2 (S3-compatible) in production, local filesystem in dev
- **Auth:** django-allauth (email verification) + django-axes (brute-force protection) + zxcvbn password strength + HMAC-peppered PBKDF2 hasher
- **Markdown:** django-markdownx + nh3 sanitization
- **Email:** Resend via django-anymail (production), console backend (dev)
- **Error tracking:** Sentry (optional)
- **Static files:** WhiteNoise (production)
- **Type checker:** `ty` (not mypy)
- **Deployment:** Railway

## Project Structure

```
config/          # Django project settings, URLs, CSP middleware, rate limiting
accounts/        # User management app (custom User model, UUID PK, email-based auth)
events/          # Dance events app (CRUD, feeds, image processing)
scrapers/        # Data import scripts (e.g. dansehallerne.py)
templates/       # Global Django templates (base, accounts, events, partials)
static/          # Static assets (Tailwind input CSS, vendored HTMX, logo)
conftest.py      # pytest-django autouse fixtures (disables SSL, uses simple storage)
spec.md          # Full system specification (authoritative reference)
deployment-notes.md  # Production deployment guidance
docker-compose.yml   # Local PostgreSQL for development
```

### Key files within apps

```
events/
  models.py          # Event model
  views.py           # CRUD + list + feeds views
  forms.py           # EventForm (markdownx)
  feeds.py           # iCal and RSS feeds
  images.py          # WebP conversion, EXIF stripping, resize
  validators.py      # Image format/size and URL validators
  templatetags/
    markdown_filters.py   # render_markdown filter (nh3 sanitized)
  management/commands/
    import_dansehallerne.py

accounts/
  models.py          # Custom User (UUID PK, display_name, bio, website)
  views.py           # Login, password reset, profile, account deletion
  forms.py           # CustomAuthenticationForm, ProfileForm
  hashers.py         # HmacPepperedPasswordHasher
  validators.py      # ZxcvbnPasswordValidator
  signals.py         # Admin notification on new signup

config/
  settings.py        # Django settings
  urls.py            # Root URL conf
  ratelimit.py       # Cache-based RateLimitMixin
  middleware.py      # ContentSecurityPolicyMiddleware
```

## Commands

### Development

```bash
uv sync --dev                              # Install all dependencies
uv run python manage.py runserver          # Start dev server
npm run css:watch                          # Watch & rebuild Tailwind CSS (separate terminal)
uv run python manage.py migrate            # Apply database migrations
uv run python manage.py makemigrations     # Create new migrations
uv run python manage.py createsuperuser    # Create admin user
```

### Testing

```bash
uv run pytest                              # Run all tests (parallel, 8 workers)
uv run pytest --cov                        # Tests with coverage report
uv run pytest --cov --cov-fail-under=90    # Enforce 90% coverage (local)
uv run pytest path/to/test_file.py         # Run specific test file
uv run pytest -k "test_name"               # Run tests matching name
uv run pytest --create-db                  # Force fresh DB (default: --reuse-db)
```

- Tests run in parallel via pytest-xdist (`-n 8`)
- `--reuse-db` is on by default; use `--create-db` to force fresh DB
- Coverage minimum: 90% for `events/` and `accounts/` (local), 80% in CI
- Test factories: `accounts/tests/factories.py` (UserFactory), `events/tests/factories.py` (EventFactory)

### Linting & Formatting

```bash
uv run ruff check .                        # Lint
uv run ruff check . --fix                  # Lint with auto-fix
uv run ruff format .                       # Format code
uv run ruff format --check .               # Check formatting (CI)
uv run ty check .                          # Type checking
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
- **Ruff rules:** E, F, I (isort), UP (pyupgrade), B (bugbear), SIM (simplify), S (security); E501 ignored
- **Migrations excluded** from linting
- **Pre-commit hooks:** ruff check+fix, ruff format, ty check, check-yaml, check-toml, trailing-whitespace, end-of-file-fixer

### Architecture Patterns

- **Class-based views** (CBV) with mixins: `DetailView`, `ListView`, `CreateView`, `UpdateView`, `DeleteView`
- **HTMX integration:** Views return full page or partial template based on `HX-Request` header; list results swapped via `events/partials/event_list_results.html`
- **Custom mixins:**
  - `RateLimitMixin` — cache-based rate limiting, IP or user-keyed via `rate_limit_by_user = True`
  - `EventOwnerOrModeratorMixin` — restricts edit/delete to owner or staff
- **Custom User model:** UUID primary key, email-based authentication (no username login)
- **No moderation workflow:** Status/rejection fields were removed; all submitted events are visible

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
- `conftest.py` (root) provides autouse fixture: disables SSL redirect, sets `PASSWORD_PEPPER`, uses simple static storage

### Security

- CSRF protection via Django middleware; HTMX includes token via `hx-headers` on `<body>`
- XSS: Markdown sanitized via nh3 (allowlist of tags/attributes in `markdown_filters.py`)
- Never use `|safe` or `{% autoescape off %}` on user-supplied content
- Image uploads: Pillow-validated (not Content-Type), EXIF stripped, resized to 1200px, converted to WebP
- Brute-force: django-axes (5 failures = 30 min IP lockout)
- Rate limiting: custom cache-based (`config/ratelimit.py`); limits per endpoint listed below
- CSP: `ContentSecurityPolicyMiddleware` — `default-src 'self'`, `script-src 'self'`, `style-src 'self' 'unsafe-inline'`
- Password hashing: HMAC-SHA256 pepper (env `PASSWORD_PEPPER`) + PBKDF2; auto-migrates legacy hashes
- Password strength: zxcvbn minimum score 2

### Rate Limits (current)

| Endpoint | Limit |
|---|---|
| Login | 20 req/hr per IP |
| Password reset | 5 req/hr per IP |
| Event list/search | 20 req/min per IP |
| Event create | 20 req/hr per user |
| Event update | 20 req/min per user |
| Event delete | 20 req/min per user |
| Event duplicate | 20 req/min per user |

## Models

### User (`accounts/models.py`)

Extends `AbstractUser`, UUID primary key, email-based auth.

| Field | Notes |
|---|---|
| `id` | UUID PK |
| `username` | Required, unique |
| `email` | Required, unique |
| `display_name` | Optional; shown instead of username in public UI |
| `bio` | Markdown, 500 chars max |
| `website` | Optional URL |
| `intro_message` | Readonly, reserved for future use |

### Event (`events/models.py`)

| Field | Notes |
|---|---|
| `id` | UUID PK |
| `slug` | Auto-generated, immutable, collision-safe (random 2-byte hex suffix) |
| `title` | Max 200 chars, min 3 chars |
| `description` | Markdown |
| `image` | Optional; WebP, max 10 MB, 1200px max dimension, EXIF stripped |
| `start_datetime` | Must be future on creation, max 1 year out |
| `end_datetime` | Optional, must be after start |
| `venue_name` | Max 200 chars |
| `venue_address` | Optional |
| `category` | Enum: performance, talk, workshop, open_practice, social, other |
| `is_free` | Boolean |
| `is_wheelchair_accessible` | Boolean |
| `price_note` | Optional, max 200 chars |
| `source_url` | Optional, http/https only |
| `external_source` | Optional (e.g. `"dansehallerne"`) |
| `submitted_by` | FK → User, nullable (SET_NULL on delete) |
| `created_at`, `updated_at` | Auto timestamps |

## Views Summary

### events/

| View | URL | Auth |
|---|---|---|
| `EventListView` | `/` | Public |
| `EventDetailView` | `/events/<slug>/` | Public |
| `EventCreateView` | `/events/new/` | Login required |
| `EventUpdateView` | `/events/<slug>/edit/` | Owner or staff |
| `EventDeleteView` | `/events/<slug>/delete/` | Owner or staff |
| `EventDuplicateView` | `/events/<slug>/duplicate/` | Login required |
| `EventRSSFeed` | `/feeds/rss/` | Public |
| `EventICalFeed` | `/feeds/ical/` | Public |

Feeds support optional `?category=` filter. They never expose submitter identity.

### accounts/

| View | URL |
|---|---|
| `RateLimitedLoginView` | `/accounts/login/` |
| `RateLimitedPasswordResetView` | `/accounts/password-reset/` |
| `AccountDeleteView` | `/accounts/delete/` |
| `EditProfileView` | `/accounts/profile/edit/` |
| `ChangePasswordView` | `/accounts/change-password/` |
| `PublisherProfileView` | `/accounts/publishers/<username>/` |
| `AccountProfileView` | `/accounts/profile/` (redirects to own PublisherProfileView) |

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`:

1. Install uv + Python 3.13
2. `uv sync --dev`
3. `npm ci` + `npm run css:build`
4. `collectstatic --noinput`
5. `ruff check .` (lint)
6. `ruff format --check .` (format)
7. `ty check .` (type checking)
8. `pytest --cov --cov-fail-under=80 --create-db` (PostgreSQL 16)
9. SonarQube scan

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `true`/`false` |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | DB connection string (default: `sqlite:///db.sqlite3`) |
| `PASSWORD_PEPPER` | 64-char hex string for HMAC password hashing |
| `R2_BUCKET_NAME` | Enables Cloudflare R2 storage when set |
| `R2_ACCESS_KEY` | R2 access key |
| `R2_SECRET_KEY` | R2 secret key |
| `R2_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `CDN_DOMAIN` | Public CDN domain for R2 images |
| `RESEND_API_KEY` | Enables Resend email sending (production) |
| `SENTRY_DSN` | Enables Sentry error tracking |
| `ADMINS` | Comma-separated admin emails (notified on new signups) |
| `CSRF_TRUSTED_ORIGINS` | Required in production |
| `RAILWAY_PUBLIC_DOMAIN` | Auto-set by Railway |

## Deployment

- **Platform:** Railway (single web process, gunicorn)
- **Database:** Railway managed PostgreSQL 16
- **Images:** Cloudflare R2 (free tier: 10 GB / 10M reads)
- **Static files:** WhiteNoise
- **Email:** Resend via django-anymail
- **Monitoring:** Sentry (errors), UptimeRobot (uptime)
- **Estimated cost:** $5–10/month
