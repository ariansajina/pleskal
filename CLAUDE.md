# CLAUDE.md — pleskal (Copenhagen Dance Calendar)

## Project Overview

pleskal is a Django web application for a Copenhagen dance and performance art calendar.

Inspired by [dukop.dk](https://dukop.dk). Designed for low operational cost and complexity.

## Tech Stack

- **Framework:** Django 6.0.3+ (Python 3.14+)
- **Database:** PostgreSQL (production), SQLite (dev default)
- **Frontend:** Django templates + HTMX (no JS framework)
- **Styling:** Tailwind CSS 4.0 (built via CLI)
- **Package manager:** `uv` (Python), `npm` (Tailwind only)
- **Image storage:** Cloudflare R2 (S3-compatible) in production, local filesystem in dev
- **Image formats:** JPEG, PNG, WebP, HEIF/HEIC (via pillow-heif)
- **Auth:** django-allauth (email verification) + django-axes (brute-force protection) + zxcvbn password strength + HMAC-peppered Argon2id hasher
- **Registration:** Invite-only via claim codes (no open self-registration)
- **Markdown:** django-markdownx + nh3 sanitization
- **Email:** Resend via django-anymail (production), console backend (dev)
- **Error tracking:** Sentry (optional)
- **Static files:** WhiteNoise (production)
- **Type checker:** `ty` (not mypy)
- **Deployment:** Railway

## Project Structure

```
config/          # Django project settings, URLs, CSP middleware, rate limiting
accounts/        # User management app (custom User model, UUID PK, email-based auth, claim codes)
events/          # Dance events app (CRUD, feeds, image processing)
scrapers/        # Data import scripts (dansehallerne, hautscene, sydhavnteater, kbhdanser, toastercph)
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
  models.py          # Event, EventCategory, FeedHit models
  views.py           # CRUD + list + subscribe views
  forms.py           # EventForm (markdownx)
  feeds.py           # iCal feed, RSS feed, single-event iCal download
  images.py          # WebP conversion, EXIF stripping, resize
  validators.py      # Image format/size and URL validators
  urls.py            # Event URL patterns
  templatetags/
    markdown_filters.py   # render_markdown filter (nh3 sanitized)
  management/commands/
    base_import.py              # Base class for scraper import commands
    import_dansehallerne.py     # Dansehallerne events importer
    import_dansehallerne_workshops.py  # Dansehallerne workshops importer
    import_hautscene.py         # HAUT Scene importer
    import_kbhdanser.py         # KBH Danser importer
    import_sydhavnteater.py     # Sydhavn Teater importer
    import_toastercph.py        # Toaster CPH importer
    run_scrapers.py             # Unified command: runs all scrapers + imports (used by Railway cron)
    weekly_digest.py            # Weekly digest email (feed analytics)

accounts/
  models.py          # Custom User (UUID PK, display_name, display_name_slug) + ClaimCode
  managers.py        # UserManager (custom user manager)
  views.py           # Login, password reset, profile, account deletion, claim flow, invite management
  forms.py           # CustomAuthenticationForm, ProfileForm, ClaimCodeForm, ClaimRegisterForm
  hashers.py         # HmacPepperedArgon2PasswordHasher
  validators.py      # ZxcvbnPasswordValidator
  signals.py         # Admin notification on new signup; Resend CRM contact sync on email verification
  urls.py            # Account URL patterns
  management/commands/
    generate_claim_codes.py     # Generate invite codes (--count, --expires, --created-by)
    create_source_accounts.py   # Create system accounts from scrapers/sources.json

config/
  settings.py        # Django settings
  urls.py            # Root URL conf
  ratelimit.py       # Cache-based RateLimitMixin
  middleware.py      # ContentSecurityPolicyMiddleware

scrapers/
  base.py                      # Shared utilities (get_soup, scrape_url_list, etc.)
  dansehallerne.py             # Dansehallerne scraper
  dansehallerne_workshops.py   # Dansehallerne workshops scraper
  hautscene.py                 # HAUT Scene scraper
  kbhdanser.py                 # KBH Danser scraper
  sydhavnteater.py             # Sydhavn Teater scraper
  toastercph.py                # Toaster CPH scraper
  sources.json                 # Source account config for 5 scrapers (external_source, display_name, email)
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
uv run pytest -n auto                      # Run all tests (parallel, auto workers)
uv run pytest -n auto --cov               # Tests with coverage report
uv run pytest -n auto --cov --cov-fail-under=90  # Enforce 90% coverage (local)
uv run pytest path/to/test_file.py         # Run specific test file
uv run pytest -k "test_name"              # Run tests matching name
uv run pytest --create-db                  # Force fresh DB (default: --reuse-db)
```

- Tests run in parallel via pytest-xdist (`-n auto`)
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

### Management Commands

```bash
# Claim codes (invite-only registration)
uv run python manage.py generate_claim_codes --count 5 --expires 2026-12-31

# Source accounts (create system users for scrapers)
uv run python manage.py create_source_accounts

# Event importers (individual)
uv run python manage.py import_dansehallerne
uv run python manage.py import_dansehallerne_workshops
uv run python manage.py import_hautscene
uv run python manage.py import_kbhdanser
uv run python manage.py import_sydhavnteater
uv run python manage.py import_toastercph

# Unified scraper (runs all sources; used by Railway cron)
uv run python manage.py run_scrapers              # run all (6 sources)
uv run python manage.py run_scrapers --dry-run    # preview only (no DB writes)
uv run python manage.py run_scrapers --skip-images  # skip image downloads
uv run python manage.py run_scrapers --only hautscene --only sydhavnteater  # subset
# Individual scrapers can be disabled via env: SCRAPER_<NAME>_ENABLED=false

# Weekly digest email
uv run python manage.py weekly_digest

# Geocoding backfill for events that predate the OSM integration
uv run python manage.py backfill_geocoding                  # all events without coords
uv run python manage.py backfill_geocoding --dry-run        # print resolutions only
uv run python manage.py backfill_geocoding --limit 50       # cap per-run size
```

## Code Conventions

### Style & Linting

- **Line length:** 88 (ruff default)
- **Python target:** 3.13 (ruff target; runtime requires Python 3.14+)
- **Ruff rules:** E, F, I (isort), UP (pyupgrade), B (bugbear), SIM (simplify), S (security); E501 ignored
- **Per-file ignores:** tests allow S101 (assert), S106 (hardcoded password), S314
- **Migrations excluded** from linting
- **Pre-commit hooks:** ruff check+fix, ruff format, ty check, pytest, check-yaml, check-toml, trailing-whitespace, end-of-file-fixer

### Architecture Patterns

- **Class-based views** (CBV) with mixins: `DetailView`, `CreateView`, `UpdateView`, `DeleteView`, `View`
- **HTMX integration:** Views return full page or partial template based on `HX-Request` header; list results swapped via `events/partials/event_list_results.html`
- **Custom mixins:**
  - `RateLimitMixin` — cache-based rate limiting, IP or user-keyed via `rate_limit_by_user = True`
  - `EventOwnerMixin` — restricts edit/delete/duplicate to event owner (raises 403)
- **Custom User model:** UUID primary key, email-based authentication (`USERNAME_FIELD = "email"`, no username)
- **Draft events:** Events can be saved as drafts (`is_draft=True`) and are only visible to their owner; toggle via `EventToggleDraftView`
- **No moderation workflow:** All published events are visible immediately
- **Invite-only registration:** Users register via claim codes (`/claim/` flow), no open signup; logged-in users can generate batches of invite codes via `MyInvitesView` (limited by `CLAIM_CODES_PER_BATCH` per month)

### Naming

- **Views:** PascalCase, suffixed with `View` (e.g., `EventCreateView`)
- **Models:** Singular PascalCase (e.g., `Event`, `User`, `ClaimCode`)
- **Forms:** Suffixed with `Form` (e.g., `EventForm`, `ClaimCodeForm`)
- **Factories:** Suffixed with `Factory` (e.g., `UserFactory`)
- **URL names:** snake_case (e.g., `event_detail`, `my_events`, `claim_register`)
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
- CSP: `ContentSecurityPolicyMiddleware` — `default-src 'self'`, `script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:` (+ R2 domain if configured), `frame-src https://www.openstreetmap.org` (OSM map embed)
- Password hashing: HMAC-SHA256 pepper (env `PASSWORD_PEPPER`, 32-byte key) + Argon2id; auto-migrates legacy PBKDF2 hashes on login
- Password strength: zxcvbn minimum score 2

### Rate Limits (current)

| Endpoint | Limit |
|---|---|
| Login | 20 req/hr per IP |
| Password reset | 5 req/hr per IP |
| Claim code | 5 req/hr per IP |
| Event list/search | 20 req/min per IP |
| Event create | 20 req/hr per user |
| Event update | 20 req/min per user |
| Event delete | 20 req/min per user |
| Event duplicate | 20 req/min per user |
| Event toggle draft | 20 req/min per user |

## Models

### User (`accounts/models.py`)

Extends `AbstractBaseUser` + `PermissionsMixin`, UUID primary key, email-based auth.

| Field | Notes |
|---|---|
| `id` | UUID PK |
| `email` | Required, unique; used as `USERNAME_FIELD` |
| `display_name` | Optional, max 100 chars; shown in public UI |
| `display_name_slug` | Auto-generated unique slug (from display_name or email prefix) |
| `bio` | Markdown, 2000 chars max |
| `website` | Optional URL |
| `is_active` | Boolean, default True |
| `is_staff` | Boolean, default False |
| `is_system_account` | Boolean, default False; marks scraper accounts |
| `date_joined` | Timestamp |

Properties: `public_name` returns display_name or `"Anonymous"` if unset.

### ClaimCode (`accounts/models.py`)

Invite-only registration codes.

| Field | Notes |
|---|---|
| `code` | 8-char unique code (A-Z, 2-9, no ambiguous chars O/0/I/1/L) |
| `created_at` | Auto timestamp |
| `expires_at` | Expiry datetime |
| `claimed_at` | Nullable; set when used |
| `claimed_by` | FK -> User, nullable |
| `created_by` | FK -> User, nullable; the user who generated the code |

Properties: `is_expired`, `is_claimed`, `is_valid`.

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
| `venue_address` | Optional, max 200 chars |
| `category` | Enum: performance, worksharing, workshop, openpractice, talk, social, other |
| `is_free` | Boolean |
| `is_wheelchair_accessible` | Boolean |
| `price_note` | Optional, max 200 chars |
| `source_url` | Optional, http/https only |
| `external_source` | Optional (e.g. `"dansehallerne"`) |
| `latitude` | Optional float; populated at save time via OSM/Nominatim geocoding |
| `longitude` | Optional float; populated alongside `latitude` |
| `submitted_by` | FK -> User, nullable (SET_NULL on delete) |
| `is_draft` | Boolean, default False; drafts are only visible to the owner |
| `created_at`, `updated_at` | Auto timestamps |

Method: `get_display_description()` prepends scraped event disclaimer if `external_source` is set.

Property: `has_map_location` — True when both `latitude` and `longitude` are set; used by the event detail page to render the "Show map" button and OpenStreetMap embed modal. Geocoding happens synchronously at save time (best-effort, failures swallowed) via `events.geocoding.geocode`, which calls Nominatim with a ≥1 req/sec rate limit and the configured `GEOCODING_USER_AGENT`.

### FeedHit (`events/models.py`)

Daily hit counter for feed analytics (used by weekly digest).

| Field | Notes |
|---|---|
| `feed_type` | `ical` or `rss` |
| `date` | Date |
| `count` | Positive integer, atomically incremented |

Unique together: `(feed_type, date)`.

Classmethod: `record(feed_type)` atomically increments the daily counter via `update_or_create`.

## Views Summary

### events/

| View | URL | Auth |
|---|---|---|
| `EventListView` | `/` | Public |
| `EventDetailView` | `/events/<slug>/` | Public |
| `EventCreateView` | `/events/submit/` | Login required |
| `EventUpdateView` | `/events/<slug>/edit/` | Owner only |
| `EventDeleteView` | `/events/<slug>/delete/` | Owner only |
| `EventDuplicateView` | `/events/<slug>/duplicate/` | Owner only |
| `EventToggleDraftView` | `/events/<slug>/toggle-draft/` | Owner only |
| `MyEventsView` | `/my-events/` | Login required (redirects to publisher profile) |
| `SubscribeView` | `/subscribe/` | Public |
| `EventICalFeed` | `/feed/events.ics` | Public |
| `EventRSSFeed` | `/feed/events.rss` | Public |
| `EventICalSingleView` | `/events/<slug>/calendar.ics` | Public |

- Feeds support optional `?category=` and `?publisher=` filters and never expose submitter identity
- Event list supports: category (multi-value), date range, is_free, is_wheelchair_accessible, search (title/venue/description/submitter)
- Quick date filters: this_week, next_week, this_month, next_month
- Max upcoming events per user enforced on create/duplicate (see `MAX_UPCOMING_EVENTS_PER_USER` setting)
- Draft events are hidden from public list/detail; only visible to the owner

### accounts/

| View | URL | Auth |
|---|---|---|
| `RateLimitedLoginView` | `/accounts/login/` | Public |
| `RateLimitedPasswordResetView` | `/accounts/password-reset/` | Public |
| `AccountDeleteView` | `/accounts/delete/` | Login required |
| `EditProfileView` | `/accounts/profile/edit/` | Login required |
| `ChangePasswordView` | `/accounts/change-password/` | Login required |
| `PublisherProfileView` | `/accounts/publishers/<slug>/` | Public |
| `AccountProfileView` | `/accounts/profile/` | Login required (redirects to own publisher profile) |
| `ClaimCodeView` | `/claim/` | Public |
| `ClaimRegisterView` | `/claim/register/` | Public (requires valid claim code in session) |
| `MyInvitesView` | `/accounts/invites/` | Login required |

- `MyInvitesView`: GET lists user's claim codes (filterable by all/active/claimed); POST generates a new batch (limited to `CLAIM_CODES_PER_BATCH` codes, expires in `CLAIM_CODE_EXPIRY_DAYS` days); supports HTMX partial swap

## Remote Session Requirements

When running as a Claude Code remote agent (e.g. via the web or API), **before creating a pull request** you must:

1. Run pre-commit hooks across all files and fix any issues:
   ```bash
   pre-commit run --all-files
   ```
2. Run the full test suite and fix any failures:
   ```bash
   uv run pytest -n auto
   ```

Do not open a PR until both commands pass cleanly.

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`:

1. Checkout (full history)
2. Install uv + Python 3.13
3. `uv sync --dev`
4. `npm ci` + `npm run css:build`
5. `collectstatic --noinput`
6. `ruff check .` (lint)
7. `ruff format --check .` (format)
8. `ty check .` (type checking)
9. `pytest --cov --cov-report=term-missing --cov-report=xml --cov-branch --cov-fail-under=80 --create-db` (PostgreSQL 16)
10. SonarQube scan

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `true`/`false` |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | DB connection string (default: `sqlite:///db.sqlite3`) |
| `PASSWORD_PEPPER` | 64-char hex string (32-byte key) for HMAC password hashing |
| `R2_BUCKET_NAME` | Enables Cloudflare R2 storage when set |
| `R2_ACCESS_KEY` | R2 access key |
| `R2_SECRET_KEY` | R2 secret key |
| `R2_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `CDN_DOMAIN` | Public CDN domain for R2 images |
| `RESEND_API_KEY` | Enables Resend email sending (production) |
| `RESEND_SEGMENT_ID` | Optional; for contact list syncing |
| `SENTRY_DSN` | Enables Sentry error tracking |
| `ADMINS` | Comma-separated admin emails (notified on new signups) |
| `CSRF_TRUSTED_ORIGINS` | Required in production |
| `SITE_DOMAIN` | Site domain for allauth |
| `SITE_NAME` | Site name for allauth |
| `RAILWAY_PUBLIC_DOMAIN` | Auto-set by Railway |
| `GEOCODING_ENABLED` | Toggle Nominatim calls in `Event.save()` (default: `false` in DEBUG, `true` otherwise) |
| `GEOCODING_USER_AGENT` | User-Agent string sent to Nominatim (required by their policy) |

## Deployment

- **Platform:** Railway (single web process, gunicorn)
- **Database:** Railway managed PostgreSQL 16
- **Images:** Cloudflare R2 (free tier: 10 GB / 10M reads)
- **Static files:** WhiteNoise
- **Email:** Resend via django-anymail
- **Monitoring:** Sentry (errors), UptimeRobot (uptime)
- **Estimated cost:** $5-10/month
- **Cron job:** `railway.cron.toml` runs `python manage.py run_scrapers` on a schedule (restartPolicyType: NEVER)
