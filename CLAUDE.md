# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pleskal is a Django web application for a Copenhagen dance and performance art calendar. Inspired by [dukop.dk](https://dukop.dk); designed for low operational cost and complexity.

## Tech Stack

- **Framework:** Django 6.0.3+ (Python 3.14+)
- **Database:** PostgreSQL (production), SQLite (dev default)
- **Frontend:** Django templates + HTMX (no JS framework)
- **Styling:** Tailwind CSS 4.0 (built via CLI)
- **Theming:** light + dark themes; follows `prefers-color-scheme` unless the header toggle (`static/js/theme.js`) picked one. Colors are CSS custom properties in `templates/base.html` `:root`; dark values live in `templates/partials/dark_theme_tokens.css`
- **Package manager:** `uv` (Python), `npm` (Tailwind only)
- **Image storage:** Cloudflare R2 (S3-compatible) in production, local filesystem in dev
- **Image formats:** JPEG, PNG, WebP, HEIF/HEIC (via pillow-heif)
- **Auth:** django-allauth (email verification) + django-axes (brute-force protection) + zxcvbn password strength + HMAC-peppered Argon2id hasher
- **Registration:** Invite-only via claim codes (no open self-registration)
- **Markdown:** django-markdownx + nh3 sanitization
- **Translation (offline):** lingua (EN/DA language detection) + the Argos Translate da→en model run directly via CTranslate2 (no PyTorch); scraped Danish descriptions are machine-translated to English
- **Email:** Resend via django-anymail (production), console backend (dev)
- **Error tracking:** Sentry (optional)
- **Static files:** WhiteNoise (production)
- **Type checker:** `ty` (not mypy)
- **Deployment:** Railway

## Project Structure

```
config/          # Django project settings (incl. SECURE_CSP), URLs, rate limiting, PWA endpoints
accounts/        # User management app (custom User model, UUID PK, email-based auth, claim codes)
events/          # Dance events app (CRUD, feeds, image processing, geocoding, sharing)
analytics/       # Cookieless server-side analytics (daily counters, staff /stats/ dashboard)
scrapers/        # Per-source scrapers (afukscene, blaagaardteater, dansehallerne, dansehallerne_workshops, dansekapellet, faar302, hautscene, kbhdanser, sort_hvid, sydhavnteater, taornby, toastercph, warehouse9); teaterbilletter.py is shared by the venues ticketed through teaterbilletter.dk
templates/       # Global Django templates (base, accounts, events, partials)
static/          # Static assets (Tailwind input CSS, vendored HTMX, PWA icons, JS shims)
scripts/         # Standalone scripts (backup_db.py for the backup cron; download_translation_model.py, run at Docker build time)
conftest.py      # pytest-django autouse fixtures (SSL off, fixed pepper, geocoding off, translation off, ANALYTICS_ENABLED off)
deployment-notes.md  # Production deployment guidance
docker-compose.yml   # Local PostgreSQL for development
```

### Key files within apps

```
events/
  models.py            # Event, EventSeries, EventCategory, FeedHit models
  limits.py            # Field length limits (Django-free, so scrapers run standalone)
  views.py             # CRUD + list + subscribe views
  forms.py             # EventForm (markdownx; repeat fields + edit scope for recurring events)
  recurrence.py        # Repeat rules (no DB): Pattern <-> RRULE, describe(), date-dependent presets, expand() within the one-year / per-series limits
  series.py            # Series: plan + apply recurring-event creation and scoped edits (this / following / all), scope_queryset for delete/toggle, scraped-show linking (scraped_series_key, link_scraped_series), listing helpers (first_per_series, attach_series_cards), detail date strip (series_context)
  feeds.py             # iCal feed, RSS feed, single-event iCal download (+ shared `_plain_text` helper)
  images.py            # WebP conversion, EXIF stripping, resize; list-card thumbnails (make_thumbnail/store_thumbnail)
  geocoding.py         # Nominatim/OSM geocoder with rate limiting
  translation.py       # Offline per-paragraph EN/DA detection (lingua) + Markdown-preserving da→en translation (CTranslate2)
  sharing.py           # Apple/Google calendar URL builders used by detail page
  signals.py           # Event file cleanup: deletes image + thumbnail files on event delete and when an image is replaced/cleared (unless another event references them)
  context_processors.py  # Template context (site_origin = https://SITE_DOMAIN for canonical/og:url)
  structured_data.py   # SEO: schema.org Event JSON-LD + meta description for event detail pages
  sitemaps.py          # /sitemap.xml (events, publishers, static pages)
  validators.py        # URL scheme validator (image format/size validation lives in images.py)
  urls.py              # Event URL patterns
  templatetags/
    markdown_filters.py   # render_markdown filter (nh3 sanitized)
  management/commands/
    base_import.py              # Base class for event import logic (upsert, stale deletion, images, linking a show's dates into a series)
    import_events.py            # Generic importer: import_events <source> (config from scrapers/registry.py)
    run_scrapers.py             # Unified command: runs all scrapers + imports (used by Railway cron)
    backfill_geocoding.py       # Populate latitude/longitude on events that predate geocoding
    backfill_translations.py    # Detect language / translate scraped descriptions not yet processed (run by run_scrapers)
    backfill_thumbnails.py      # Generate list-card thumbnails for images that have none yet (run by run_scrapers)
    purge_expired_events.py     # Delete past scraped events older than their retention period (run by run_scrapers)
    weekly_digest.py            # Weekly digest email (growth, feed hits, last 7 days of site traffic)

accounts/
  models.py          # Custom User (UUID PK, display_name, display_name_slug) + ClaimCode
  managers.py        # UserManager; `publishers()` = named, active source accounts or users with published events (directory + sitemap)
  views.py           # Login, password reset, profile, account deletion, claim flow, invite management
  forms.py           # CustomAuthenticationForm, ProfileForm (current password required to change email), AccountDeleteForm (password required), ClaimCodeForm, ClaimRegisterForm
  hashers.py         # HmacPepperedArgon2PasswordHasher
  validators.py      # ZxcvbnPasswordValidator
  signals.py         # Admin notification on new signup; Resend CRM sync on email verification (old address removed on email change, all removed on account deletion); preserve claim-code emails on user delete
  urls.py            # Account URL patterns
  management/commands/
    generate_claim_codes.py     # Generate invite codes (--count, --expires, --created-by)
    create_source_accounts.py   # Create system accounts from scrapers/sources.json

analytics/
  models.py          # DailyCount (per-day counters), DailySalt + VisitorHash (today's unique-visitor dedupe, deleted at rollover)
  middleware.py      # AnalyticsMiddleware: records page views, referrers, searches, filters, calendar downloads
  stats.py           # Read-side aggregation shared by the dashboard and weekly_digest
  views.py           # StatsDashboardView (/stats/, staff only)

config/
  settings.py        # Django settings
  urls.py            # Root URL conf (includes /health/, /health/db/, /manifest.webmanifest, /service-worker.js, /offline/); wraps markdownx's markdownify (preview) view with login_required and leaves its image-upload view unmounted (its default urls.py mounts both unauthenticated)
  ratelimit.py       # Cache-based RateLimitMixin
  middleware.py      # NoStoreForAuthenticatedMiddleware: `Cache-Control: no-store` on logged-in responses (kept out of browser + service-worker caches)
  pwa.py             # PWA endpoints: manifest, service worker, offline fallback page
  cron_monitoring.py # cron_monitor(): Sentry Crons check-ins for run_scrapers + weekly_digest

scrapers/
  base.py                      # Shared utilities (get_soup, canonical_url, scrape_url_list, etc.)
  dansehallerne.py             # Dansehallerne scraper
  dansehallerne_workshops.py   # Dansehallerne workshops scraper
  teaterbilletter.py           # Shared scraper for venues ticketed through teaterbilletter.dk (Billetten): public JSON API (/api/events?venueCodes=…) for shows, times, prices, images (tereba.dk) and a description with the credits appended (`credits()`: one "**Role** names" line per role, crew before cast, plus the producing company); per-venue config (TeaterbilletterVenue: venue codes, genre/category filter, wheelchair) + optional `venue_links` hook (`venue_page_links` reads only the venue's programme page and links events to the venue's own show pages via the ticket widget's data-event_no; an unreadable programme page, e.g. faar302.dk's intermittent bot challenge, is retried once and then fails the venue's scrape rather than switching its links). Content comes from the API only: the venues' show pages add nothing it lacks, and faar302.dk's are often behind that bot challenge. API times are UTC
  afukscene.py                 # AFUK Scene (teaterbilletter.dk; dance/performance/new-circus only; links to teaterbilletter.dk)
  blaagaardteater.py           # Blaagaard Teater (teaterbilletter.dk; dance/performance/new-circus only; links to blaagaardteater.dk show pages)
  dansekapellet.py             # Dansekapellet (teaterbilletter.dk; every genre; links to teaterbilletter.dk)
  faar302.py                   # Teater FÅR302 (teaterbilletter.dk; every genre, incl. its site-specific venue; links to faar302.dk show pages)
  hautscene.py                 # HAUT Scene scraper
  kbhdanser.py                 # KBH Danser scraper
  sort_hvid.py                 # Sort/Hvid scraper
  sydhavnteater.py             # Sydhavn Teater scraper
  taornby.py                   # Tårnby Park Studio festival scraper (single hand-formatted page, overfit to the 2026 edition; retired via SCRAPER_DISABLED_AFTER)
  toastercph.py                # Toaster CPH scraper (retired via SCRAPER_DISABLED_AFTER)
  warehouse9.py                # Warehouse9 scraper (Tribe Events iCal feed)
  registry.py                  # Scraper source registry (scrape fn, external_source, image-domain allowlist, etc.) consumed by run_scrapers + import_events
  sources.json                 # Source account config (external_source, display_name, email, website) for all scrapers
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
uv run pytest                              # Run all tests (parallel, defaults from pyproject)
uv run pytest --cov                        # Tests with coverage report
uv run pytest --cov --cov-fail-under=90    # Enforce 90% coverage (local)
uv run pytest path/to/test_file.py         # Run specific test file
uv run pytest -k "test_name"               # Run tests matching name
uv run pytest --create-db                  # Force fresh DB (default: --reuse-db)
```

- Default pytest addopts: `--reuse-db -n 8` (see `pyproject.toml`); pass `-n auto` to override worker count
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

# Event importer (generic; per-source config lives in scrapers/registry.py)
uv run python manage.py import_events hautscene                 # default JSON: hautscene_events.json
uv run python manage.py import_events hautscene events.json --dry-run

# Unified scraper (runs all sources; used by Railway scrape-cron service)
uv run python manage.py run_scrapers              # run all 13 importers
uv run python manage.py run_scrapers --dry-run    # preview only (no DB writes)
uv run python manage.py run_scrapers --skip-images  # skip image downloads
uv run python manage.py run_scrapers --only hautscene --only sydhavnteater  # subset
# Individual scrapers can be disabled via env: SCRAPER_<NAME>_ENABLED=false

# Weekly digest email
uv run python manage.py weekly_digest

# Event retention (also runs daily as the last step of run_scrapers)
uv run python manage.py purge_expired_events              # delete expired scraped events
uv run python manage.py purge_expired_events --dry-run    # report counts only

# Geocoding backfill for events that predate the OSM integration
uv run python manage.py backfill_geocoding                  # all events without coords
uv run python manage.py backfill_geocoding --dry-run        # print resolutions only
uv run python manage.py backfill_geocoding --limit 50       # cap per-run size

# List-card thumbnails for images saved before thumbnails existed (also runs daily as a step of run_scrapers)
uv run python manage.py backfill_thumbnails --dry-run      # list images missing a thumbnail
uv run python manage.py backfill_thumbnails --limit 100    # generate in batches

# Description translation (also runs daily as a step of run_scrapers)
uv run python scripts/download_translation_model.py         # one-time local model download (~80 MB, git-ignored models/)
uv run python manage.py backfill_translations --dry-run     # print detected languages only
uv run python manage.py import_events faar302 --skip-translation  # import without detection/translation
```

## Code Conventions

### Style & Linting

- **Line length:** 88 (ruff default)
- **Python target:** 3.14 (ruff target; matches `requires-python`)
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
- **Series (recurring events, scraped multi-date shows):** stored as one `Event` row per occurrence linked to an `EventSeries` (see Models), so feeds, search and retention need no special cases; listings collapse a series into one card
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

### Theming (light/dark)

- Every color is a token in `:root` in `templates/base.html` with a matching dark value in `templates/partials/dark_theme_tokens.css`; never hardcode hex/rgba in rules, inline styles or page `<style>` blocks (`500.html` is the standalone exception and carries its own copy)
- `base.html` includes the dark tokens twice: under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` (system setting) and under `:root[data-theme="dark"]` (toggle). Any other theme-dependent rule needs both selectors too (see the logo/icon swap in the header CSS)
- Toggle: `static/js/theme.js` is loaded **synchronously** in `<head>` (after the `theme-color` metas) so a saved choice applies before first paint; it sets `data-theme` on `<html>`, pins both `theme-color` metas, and stores the choice in `localStorage["theme"]` (cleared when the user toggles back to the system's own theme). The button is `hidden` until the script wires it up
- `--blue` is lighter in dark mode, so text on a `--blue` fill uses `--on-blue` (not `--cream`); text on `--c-perf`/`--c-op` fills uses `--on-danger`
- `<meta name="color-scheme" content="light dark">` stops browsers (Chrome/Samsung Internet "darken websites") from auto-darkening the page
- Header shows `logo-header.png` or `logo-header-dark.png` (cream recolor) as two `<img>`s swapped by CSS, since a `<picture>` media query can't follow the toggle; the header uses 120px renditions (`logo-header*.png`, ~15 KB) of the 1024px `logo.png` / `logo-dark.png` sources, so regenerate them when the logo changes; `--img-bg` gives the transparent fallback event image a cream backdrop in dark mode
- Third-party iframes must resolve to the same color scheme as their inner document, or browsers (Safari/Firefox) paint an opaque white backdrop behind them in dark mode: the Ko-fi widget's iframes are pinned with `iframe[id^="kofi-"] { color-scheme: light !important; }`

### Security

- CSRF protection via Django middleware; HTMX includes token via `hx-headers` on `<body>`
- XSS: Markdown sanitized via nh3 (allowlist of tags/attributes in `markdown_filters.py`); the markdownx editor preview uses the same renderer (`MARKDOWNX_MARKDOWNIFY_FUNCTION`). The markdownx image-upload endpoint is not mounted (`<img>` is stripped on render anyway)
- Never use `|safe` or `{% autoescape off %}` on user-supplied content
- Image uploads: Pillow-validated (not Content-Type), capped at `MAX_IMAGE_PIXELS` (50 MP, checked from the header before decoding; JPEGs measured after draft downscaling), EXIF stripped, resized to 1200px, converted to WebP
- Brute-force: django-axes (5 failures = 30 min lockout of the (email, client IP) pair; client IP resolved via `config.ratelimit.get_client_ip`, since `REMOTE_ADDR` is Railway's proxy). `AXES_DISABLE_ACCESS_LOG = True`: successful logins aren't recorded; failed attempts are dropped after the cool-off
- Caching: `NoStoreForAuthenticatedMiddleware` marks logged-in responses `no-store`; the service worker never writes `no-store` responses to Cache Storage, so per-user pages (drafts, edit forms) don't outlive logout
- Media is served from a public bucket, so replaced/cleared event images and their thumbnails are deleted (`events/signals.py`) rather than left reachable at their old URL
- Rate limiting: custom cache-based (`config/ratelimit.py`), backed by the shared database cache in production (`CACHES` in settings; table created by `createcachetable` in preDeploy); fixed-window counters whose cache key is bucketed by window index (`f"{key}:{int(time.time() // window)}"`) so each window starts fresh regardless of the backend's TTL behavior; counted with a get-then-set (no `add()`/`incr()`, which cost twice the queries on DatabaseCache) and rejected requests don't write; limits per endpoint listed below
- CSP: Django's built-in `django.middleware.csp.ContentSecurityPolicyMiddleware`, configured via `SECURE_CSP` in `config/settings.py` — `default-src 'self'`, `script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:` (+ R2 domain if configured), `frame-src https://www.openstreetmap.org` (OSM map embed)
- Password hashing: HMAC-SHA256 pepper (env `PASSWORD_PEPPER`, 32-byte key) + Argon2id; `PASSWORD_HASHERS` configures only this hasher, no PBKDF2 fallback
- Password strength: zxcvbn minimum score 2
- Re-authentication: changing the login email (`ProfileForm.current_password`) and deleting the account (`AccountDeleteForm`) require the current password, so a hijacked session alone can't take over or delete an account

### Rate Limits (current)

| Endpoint | Method(s) | Limit | Key |
|---|---|---|---|
| Login | POST | 20 req/hr | per IP |
| Password reset | POST | 5 req/hr | per IP |
| Claim code | POST | 5 req/hr | per IP |
| Event list/search | GET | 120 req/min | per IP |
| Event create | POST | 20 req/hr | per user |
| Event update | POST | 20 req/min | per user |
| Event duplicate | POST | 20 req/min | per user |
| Event toggle draft | POST | 20 req/min | per user |
| Repeat dates preview | POST | 120 req/min | per user |

- `EventDeleteView` is **not** rate-limited (owner-only + confirmation step).
- Event toggle draft shares the `event_update` cache key, so it draws from the same per-user counter as Event update.
- Default `rate_limit_methods` is `["POST"]`; the list view overrides it to `["GET"]` (limit `PUBLIC_BROWSE_RATE_LIMIT` in `events/views.py`).
- HTMX doesn't swap 4xx/5xx responses; `static/js/htmx-errors.js` shows a banner (`#htmx-error` in `base.html`) on 429s and other failed partial requests.

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
| `claimed_by` | FK -> User, nullable (SET_NULL on delete) |
| `claimed_by_email` | Email snapshot; populated on user deletion so the record stays informative |
| `created_by` | FK -> User, nullable (SET_NULL on delete); the user who generated the code |
| `created_by_email` | Email snapshot; populated on user deletion so the record stays informative |

Properties: `is_expired`, `is_claimed`, `is_valid`.

### Event (`events/models.py`)

| Field | Notes |
|---|---|
| `id` | UUID PK |
| `slug` | Auto-generated, immutable, collision-safe (random 2-byte hex suffix) |
| `title` | Max 250 chars, min 3 chars |
| `description` | Markdown |
| `image` | Optional; WebP, max 10 MB, 1200px max dimension, EXIF stripped |
| `thumbnail` | Not editable: list-card rendition of `image` (WebP, shorter side scaled to 360px), content-addressed under `events/thumbs/`; kept in sync by `save()` (regenerated when `image` changes, reused from another event with the same image, cleared with it). Generation failures leave it empty and the card falls back to the full image; `backfill_thumbnails` retries. Deleted with the event unless another event shares it |
| `image_source_url` | Scraped events only (not editable): source URL `image` was downloaded from; the importer re-downloads when the scraped `image_url` differs (e.g. a venue replaces an "image coming soon" placeholder) |
| `start_datetime` | Must be future on creation, max 1 year out (not for system accounts) |
| `end_datetime` | Optional, must be after start; consumers that need an end (iCal `DTEND`, calendar links, JSON-LD `endDate`) use `Event.effective_end` = start + `DEFAULT_EVENT_DURATION` (1 hour) when unset |
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
| `description_language` | `da` / `en` / `mixed`, blank = not processed; set for scraped events by the importer / `backfill_translations` |
| `description_da` | Danish part of a `mixed` description (blank otherwise) |
| `description_en` | Machine translation of a Danish description, or the English part of a `mixed` one (blank for English originals) |
| `description_en_is_machine` | Boolean; True when `description_en` is a machine translation |
| `series` | FK -> EventSeries, nullable (SET_NULL), not editable; set on the occurrences of a recurring event and the dates of a scraped show with several dates |
| `created_at`, `updated_at` | Auto timestamps |

Constraint: `(title, start_datetime, venue_name)` is unique — dedupes the same event arriving from two scrapers (or a scraper and a manual submission) while letting generic titles recur at the same time in different venues. `EventForm.clean()` mirrors it with a friendly error.

Properties: `display_image_url` (own image, else the publisher default in `DEFAULT_PUBLISHER_IMAGES`, else the logo; detail page, og:image, JSON-LD) and `display_thumbnail_url` (the event cards: `thumbnail`, else the full image, else the default's static thumbnail at `default_thumbnail_path()`, i.e. under a `thumbs/` directory; regenerate those when a default image changes).

Method: `get_display_description()` returns the English description (`description_for("en")`) and prepends the scraped event disclaimer if `external_source` is set.

Translation: `description` always keeps the scraped original. `events.translation.process_description` detects each paragraph's language offline (lingua, EN/DA only, capitalized words/names stripped first) and: English → nothing stored; Danish → machine translation in `description_en`; both with a substantial English part (≥300 chars) → split into `description_da`/`description_en`. `description_for(lang)` is the accessor for a future bilingual site; `is_machine_translated` drives the "Automatically translated from Danish" note on the detail page. Feeds, JSON-LD, meta description and search use the English text. Failures leave the event unprocessed (blank `description_language`) so `backfill_translations` retries; the importer resets the fields when a description changes without being re-processed. Scope: scraped descriptions only (not titles or user events). Input to the model is Moses punctuation-normalized and HTML-entity-escaped (`MosesPunctNormalizer` + `escape=True`), matching its training data; without that, quotes and dashes come out as `â ¢` mojibake.

Retention: past events are counted from `end_datetime` (or `start_datetime` when there is no end). **Scraped** events (non-blank `external_source`) are deleted `SCRAPED_EVENT_RETENTION_DAYS` (default 90) after they end: `expired_events_q()` in `events/models.py` matches them and `purge_expired_events` deletes them daily (as a step of `run_scrapers`). **User-published** events, drafts included, are **never deleted**; `hidden_events_q()` drops them from the event list `USER_EVENT_HIDE_AFTER_DAYS` (default 730) after they end, and also hides expired scraped events before the purge runs. Detail pages stay reachable. The importer's stale deletion only touches **upcoming** events, since scrapers list only what's coming up and past events would otherwise vanish on every run.

Property: `has_map_location` — True when both `latitude` and `longitude` are set; used by the event detail page to render the "Show map" button and OpenStreetMap embed modal. Geocoding happens synchronously at save time (best-effort, failures swallowed) via `events.geocoding.geocode`, which calls Nominatim with a ≥1 req/sec rate limit and the configured `GEOCODING_USER_AGENT`. Results (including definitive "no result" answers) are cached in the shared Django cache, so repeat venues skip the network call.

### EventSeries (`events/models.py`)

Several dates of one event, listed as one card. Each occurrence is an ordinary `Event` row with `series` set. Two kinds: a **recurring event** (a user's repeat rule; the series stores what repeats) and a **scraped show** (a source page listing several dates; no rule).

| Field | Notes |
|---|---|
| `id` | UUID PK |
| `rrule` | RFC 5545 RRULE **without** COUNT/UNTIL, as written by `events.recurrence.Pattern.to_rrule()` (subset: DAILY; WEEKLY + BYDAY; MONTHLY + BYMONTHDAY or BYDAY=`<n>`/`-1` weekday; INTERVAL); blank for a scraped show (`pattern` is then None) |
| `dtstart` | Anchor of the rule (fixes the phase of "every 2 weeks" and the time of day); not necessarily an occurrence. First date for a scraped show |
| `source_key` | Scraped shows only: `"<external_source>:<source page URL>"` (`series.scraped_series_key`; a trailing `/YYYY-MM-DD/` is dropped for per-date URLs such as Warehouse9's). Unique when non-blank |
| `created_at` | Auto timestamp |

The end isn't stored: a series ends at its last occurrence, which is what lets the owner extend or shorten it. Deleted with its last occurrence (`events/signals.py`, and `SeriesEdit.apply` when an edit detaches the occurrences).

Recurrence (`events/recurrence.py`, `events/series.py`):
- Options match Google/Apple Calendar minus yearly: daily, every weekday, weekly on a day, monthly on day N / on the nth or last weekday, and a custom rule (every N days/weeks/months, chosen weekdays, monthly mode); ends never / until a date / after N dates. Presets are labelled from the start date (server-side in `forms._repeat_choices`, client-side in `static/js/event-form.js`); ones that don't fit the date render hidden + disabled.
- Rules are expanded on the local wall clock (a 19:00 class stays at 19:00 across DST) and limited to dates at most `EVENT_HORIZON` (365 days) from today, `MAX_UPCOMING_OCCURRENCES_PER_SERIES` (110) **upcoming** dates per series, and the owner's remaining `MAX_UPCOMING_EVENTS_PER_USER` (220) allowance (system accounts exempt). Rules producing more are **cut off, not rejected**; the form preview and a flash message say why (`series.cut_notice`).
- Planning is separate from writing: `plan_creation` / `plan_edit` return a plan (used by the HTMX preview, `EventRecurrencePreviewView`, and by the save), `create_series` / `SeriesEdit.apply` write it in one transaction. Every occurrence is checked against the `(title, start_datetime, venue_name)` constraint first (`check_conflicts`); a clash rejects the whole change.
- Editing an occurrence asks for a scope (`this` / `following` / `all`). Only the fields the owner changed (`form.changed_data`) are copied to the others, so individual edits survive; the publish state is copied only when it changed. A new time of day moves every date in scope; a new rule or date regenerates the **upcoming** occurrences in scope (rows already on a new date keep it, the rest are reused in order, so URLs survive; "all" shifts the series by the same number of days from its first upcoming date, "following" splits off a new series when earlier occurrences exist); changing only the end adds dates after the last occurrence or deletes those past it ("Extend series" on the detail page links to the edit form with `?scope=all`). "Does not repeat" deletes the other upcoming occurrences in scope. Past occurrences are never moved or deleted by an edit. A single event can be given a rule on edit and becomes the first occurrence of a new series.
- Delete takes the same scope (`scope_queryset`); deleting "all" includes past occurrences. **Publishing is all-or-nothing**: the draft toggle and the edit form's Publish / Save as draft buttons always apply to every date of the series (`_sync_series_publish_state`), whatever the edit's scope.

Scraped shows: scrapers emit one record per date. After each import `link_scraped_series` links the dates sharing a `source_key` into a series once a show lists two or more dates (a later lone date still joins an existing series); migration `0011` did the same for rows already in the database. The series is deleted with its last date, like any series.

Display (both kinds):
- **Listings show one card per series** (event list, publisher profile incl. drafts): `first_per_series` keeps each series' first date in the listed range (its latest for past listings) using a `RowNumber` window over the already-filtered queryset, so filters decide which date stands for the series. Counts and pagination count series (`series_group()` = series id, else event id); the results line reads "N events · M dates found". `attach_series_cards` gives each card a `SeriesCard`: a boxed **NEXT** (LAST in past listings) marker, "+N more times" when the card's day has several showings, and a date line (`events/partials/series_date_rail.html`) naming up to 5 other days (`×n` per day) then "+N more". With a date filter the line reads "X of Y dates in range" plus how many fall outside it; a single-day filter lists that day's showtimes instead. The "Repeats" badge shows only on cards without that line.
- **Detail page:** a date strip — all dates of the series (drafts only for the owner; dates hidden from listings left out) as one horizontally scrolling row of day tiles, month markers where a month starts, the current day highlighted (`static/js/date-strip.js` scrolls it into view) and, for a day with several showings, its showtimes below. Headed by the rule summary ("until" the last date) or, for a scraped show, the date range. The calendar dropdown adds "All dates (.ics)" (`EventICalSeriesView`).
- Feeds, JSON-LD and the sitemap list each occurrence as its own event.

### FeedHit (`events/models.py`)

Daily hit counter for feed analytics (used by weekly digest).

| Field | Notes |
|---|---|
| `feed_type` | `ical` or `rss` |
| `date` | Date |
| `count` | Positive integer, atomically incremented |

Unique together: `(feed_type, date)`.

Classmethod: `record(feed_type)` atomically increments the daily counter via `update_or_create`.

### Analytics (`analytics/models.py`)

Cookieless, server-side analytics: nothing is stored on or read from the visitor's device, so no consent banner is needed. `AnalyticsMiddleware` counts successful GET HTML responses after the view runs; it skips bots (User-Agent regex), prefetches, staff users, infrastructure URLs (`/health/`, PWA, robots, sitemap, `/stats/`), the admin, and non-200s. HTMX partials are not page views, but on `event_list` they feed search and filter counts, diffed against `HX-Current-URL` so each newly applied filter counts once and incremental typing counts only the final search term. Recording failures are logged and never break the response.

- `DailyCount(date, kind, key, count)`: kinds `page` (key = path), `visitors` (key blank), `referrer` (external host), `search` (normalized term), `filter` (e.g. `category:workshop`, `is_free`), `calendar` (single-event or all-dates `.ics` path). Unique `(date, kind, key)`; `increment()`/`decrement()` use `F()` updates.
- `DailySalt` / `VisitorHash`: unique visitors per day = SHA-256 of today's random salt + client IP + User-Agent. The first request of a new day creates a new salt and deletes older salts and hashes, so no IP is stored and days can't be linked. Skipped when the browser sends `Sec-GPC: 1` or `DNT: 1`.

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
| `EventToggleDraftView` | `/events/<slug>/toggle-draft/` | Owner only (a series is published / unpublished as a whole) |
| `EventRecurrencePreviewView` | `/events/submit/preview-dates/` | Login required (owner of `event` when editing); HTMX partial listing the dates a repeat rule produces |
| `MyEventsView` | `/my-events/` | Login required (redirects to publisher profile) |
| `SubscribeView` | `/subscribe/` | Public |
| `TemplateView` (about) | `/about/` | Public (static `about.html`) |
| `EventICalFeed` | `/feed/events.ics` | Public |
| `EventRSSFeed` | `/feed/events.rss` | Public |
| `EventICalSingleView` | `/events/<slug>/calendar.ics` | Public |
| `EventICalSeriesView` | `/events/<slug>/all-dates.ics` | Public; every upcoming published date of the event's series (404 for a single event); counted as a calendar download by analytics |

- Feeds support optional `?category=` and `?publisher=` filters and never expose submitter identity
- Event list filters (`_filtered_event_queryset` + `events/partials/event_filter_panel.html`) support: category (multi-value), date range, is_free, is_wheelchair_accessible, search (title/venue/description/submitter)
- Quick date filters: this_week, next_week, this_month, next_month
- Max upcoming events per user enforced on create/duplicate (see `MAX_UPCOMING_EVENTS_PER_USER` setting); a repeating event counts each occurrence and is cut off at the remaining allowance. This cap and the one-year limit apply to private users only: system (scraper) accounts are exempt, and the importer never runs them
- The event list and publisher profile show a series as one card (see EventSeries → Display)
- Draft events are hidden from public list/detail; only visible to the owner

### Project-level (config/urls.py)

| URL | Purpose |
|---|---|
| `/health/` | Plain `200 OK` health check (Railway `healthcheckPath`) |
| `/health/db/` | Deep health check (`SELECT 1`, `503` on DB failure); polled by UptimeRobot |
| `/manifest.webmanifest` | PWA manifest (`config.pwa.manifest_view`) |
| `/service-worker.js` | PWA service worker (`config.pwa.service_worker_view`); served at root so SW scope covers the whole site |
| `/offline/` | Offline fallback rendered when SW intercepts a navigation with no network |
| `/stats/` | `analytics.views.StatsDashboardView`: staff-only analytics dashboard (anonymous → login, non-staff → 403); linked in the nav for staff, network-only in the service worker, disallowed in robots.txt |

### accounts/

| View | URL | Auth |
|---|---|---|
| `RateLimitedLoginView` | `/accounts/login/` | Public |
| `RateLimitedPasswordResetView` | `/accounts/password-reset/` | Public |
| `EmailVerifiedView` | `/accounts/email-verified/` | Public (post-verification landing page) |
| `AccountDeleteView` | `/accounts/delete/` | Login required + current password |
| `EditProfileView` | `/accounts/profile/edit/` | Login required |
| `ChangePasswordView` | `/accounts/change-password/` | Login required |
| `PublisherListView` | `/accounts/publishers/` | Public (directory of `User.objects.publishers()`, linked from the footer) |
| `PublisherProfileView` | `/accounts/publishers/<slug>/` | Public |
| `AccountProfileView` | `/accounts/profile/` | Login required (redirects to own publisher profile) |
| `ClaimCodeView` | `/claim/` | Public |
| `ClaimRegisterView` | `/claim/register/` | Public (requires valid claim code in session) |
| `MyInvitesView` | `/accounts/invites/` | Login required |

- `MyInvitesView`: GET lists user's claim codes (filterable by all/active/claimed); POST generates a new batch (limited to `CLAIM_CODES_PER_BATCH` codes, expires in `CLAIM_CODE_EXPIRY_DAYS` days); supports HTMX partial swap

## Claude Code Hooks

This repo ships `.claude/hooks/` + `.claude/settings.json` for remote/web sessions (gated on `CLAUDE_CODE_REMOTE=true`, no-op locally):

- **`session-start.sh`** (`SessionStart`): runs `uv sync --dev`, `npm install`, and `pre-commit install --install-hooks` at session start, so dependencies are ready without spending turns on setup.
- **`pre-pr-check.sh`** (`PreToolUse`, matches `create_pull_request`): runs `pre-commit run --all-files` — ruff format, ruff check, ty check, and the full `pytest -n 8` suite (see `.pre-commit-config.yaml`) — and blocks PR creation with the failure output until it's clean.

Project skills live in `.claude/skills/`: `run-pleskal` (run + smoke-test the app locally) and `scraper-health` (samples 1–3 scraped events per active scraper from the live site, compares them with the venues' pages, checks start times for time-zone shifts (against the teaterbilletter.dk API for the venues scraped from it, and against the clock times on each source page), and reports a Healthy / Needs work / Unhealthy table; meant to run as a periodic routine; evidence gathered by `collect.py`, which reads public pages only and never the feeds, so FeedHit counts stay clean).

Because of this hook, **do not manually run `ruff format`, `ruff check`, `ty check`, or `pytest` before opening a PR** — the hook runs them automatically and will block the PR creation tool call if anything fails, feeding the failure output back for you to fix and retry. Manually re-running these first just duplicates the check. Only run them ad hoc if you want a mid-task sanity check on a single file, or if the hook itself surfaces a failure to diagnose.

## CI / CD

`.github/workflows/ci.yml` runs on push/PR to `main` as three parallel jobs (superseded PR runs are cancelled via `concurrency`; `setup-uv` caches the uv download cache and `UV_LOCKED=1` fails on a stale `uv.lock`):

- **lint**: `ruff check`, `ruff format --check`, `ty check`
- **static**: `npm ci` + `npm run css:build` + `collectstatic --noinput` (catches broken static references before the Docker build)
- **test**: `pytest -n auto --cov --cov-report=term-missing --cov-report=xml --cov-branch --cov-fail-under=80 --create-db` (PostgreSQL 16), then SonarQube scan (full-history checkout for blame). `-n auto` matches the runner's cores; the local default `-n 8` oversubscribes a 4-core runner

`.github/workflows/deploy-production.yml` runs on git tag `v*`. It sets `APP_VERSION=<tag>` and runs `railway up` against three Railway services in turn (web, scrape-cron, backup-cron); a `concurrency` group queues overlapping deploys instead of racing them. `.dockerignore` keeps tests, docs, `.git` and local caches/models out of the build context. `APP_VERSION` is forwarded to Sentry as the release tag.

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `true`/`false` |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | DB connection string (default: `sqlite:///db.sqlite3`) |
| `CONN_MAX_AGE` | Seconds a worker keeps its DB connection open for reuse (default: 600; health-checked before each request) |
| `PASSWORD_PEPPER` | 64-char hex string (32-byte key) for HMAC password hashing |
| `R2_BUCKET_NAME` | Enables Cloudflare R2 storage when set |
| `R2_ACCESS_KEY` | R2 access key |
| `R2_SECRET_KEY` | R2 secret key |
| `R2_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `CDN_DOMAIN` | Public CDN domain for R2 images |
| `RESEND_API_KEY` | Enables Resend email sending (production) |
| `RESEND_SEGMENT_ID` | Optional; for contact list syncing |
| `SENTRY_DSN` | Enables Sentry error tracking |
| `SENTRY_ENVIRONMENT` | Environment tag attached to Sentry events (e.g. `staging`, `production`) |
| `APP_VERSION` | Application version, used as the Sentry release tag (set automatically by deploy workflow from the git tag) |
| `SENTRY_CRON_SCHEDULE` | Cron services only: overrides the Sentry Crons schedule in code when the service's Railway cron schedule differs |
| `ADMINS` | Comma-separated admin emails (notified on new signups) |
| `CSRF_TRUSTED_ORIGINS` | Required in production |
| `SITE_DOMAIN` | Site domain for allauth |
| `SITE_NAME` | Site name for allauth |
| `RAILWAY_PUBLIC_DOMAIN` | Auto-set by Railway |
| `ANALYTICS_ENABLED` | Toggle cookieless page-view counting (default: `true`; `conftest.py` disables it, `analytics/tests/` re-enable it) |
| `GEOCODING_ENABLED` | Toggle Nominatim calls in `Event.save()` (default: `false` in DEBUG, `true` otherwise) |
| `GEOCODING_USER_AGENT` | User-Agent string sent to Nominatim (required by their policy) |
| `TRANSLATION_ENABLED` | Toggle language detection + translation of scraped descriptions (default: `false` in DEBUG, `true` otherwise; `conftest.py` disables it) |
| `TRANSLATION_MODEL_DIR` | Translation model directory (default: `models/translate-da_en`; baked into the Docker image there) |
| `TRANSLATION_MIN_CONFIDENCE` | Minimum lingua confidence for a paragraph's language to count (default: 0.9) |
| `MAX_UPCOMING_EVENTS_PER_USER` | Cap on upcoming events per user, occurrences of repeating events included (default: 220) |
| `MAX_UPCOMING_OCCURRENCES_PER_SERIES` | Cap on the upcoming dates of one repeating event (default: 110) |
| `CLAIM_CODES_PER_BATCH` | Max codes a user can mint per month from `MyInvitesView` (default: 3) |
| `CLAIM_CODE_EXPIRY_DAYS` | Expiry for user-minted claim codes (default: 30) |
| `DB_BACKUP_RETENTION_DAYS` | Retention for `scripts/backup_db.py` uploads to R2 (default: 30) |
| `SCRAPER_<NAME>_ENABLED` | Per-scraper kill switch consulted by `run_scrapers` |
| `SCRAPED_EVENT_RETENTION_DAYS` | Days after a scraped event ends before `purge_expired_events` deletes it (default: 90) |
| `USER_EVENT_HIDE_AFTER_DAYS` | Days after a user-published event ends before it drops out of the event list; user events are never deleted (default: 730) |

## Deployment

- **Platform:** Railway. The production environment runs app services (deployed from this repo) plus a managed database:
  - **web-service** (`railway.toml`): gunicorn (`--workers 2 --threads 4`, see `Dockerfile` `CMD`), public domain `pleskal.dk`, `migrate --noinput && createcachetable` as preDeploy, `/health/` healthcheck, `restartPolicyType = ON_FAILURE`
  - **scrape-cron** (`railway.scrape-cron.toml`): scheduled cron running `python manage.py run_scrapers` (scrape + import, geocoding backfill, translation backfill, thumbnail backfill, retention purge), `restartPolicyType = NEVER`
  - **backup-cron** (`railway.backup-cron.toml`): scheduled cron running `python scripts/backup_db.py`, `restartPolicyType = NEVER`
  - **digest-cron** (`railway.digest-cron.toml`): scheduled cron running `python manage.py weekly_digest`, `restartPolicyType = NEVER`. Set up manually per `deployment-notes.md` (not wired into `deploy-production.yml`, unlike the other two crons, since that requires a Railway service ID secret to be provisioned first)
  - **Postgres**: Railway managed PostgreSQL 16, backed by a persistent `postgres-volume`
- **Images / DB backups:** Cloudflare R2 (free tier: 10 GB / 10M reads)
- **Static files:** WhiteNoise
- **Email:** Resend via django-anymail
- **Monitoring:** Sentry (errors, release-tagged via `APP_VERSION`), Sentry Crons (check-ins from `run_scrapers`, `weekly_digest`, and `scripts/backup_db.py`; monitors auto-created from code; skipped on `--dry-run`/`--only`), UptimeRobot (uptime, polling `/health/db/`). See `deployment-notes.md` "Monitoring"
- **Environments:** staging is web-only (no cron services); production is deployed by tagging `v*` (see `deploy-production.yml`)
- **Estimated cost:** $5-10/month
