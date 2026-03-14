# Copenhagen Dance Calendar — System Specification v2

## 1. Project Overview

A local-first, crowd-sourced web application for discovering and sharing dance events in Copenhagen. Anyone can submit an event; approved users can post freely. The platform is community-maintained and editorially neutral.

**Inspiration:** [dukop.dk](https://dukop.dk/en/)

---

## 2. Goals

- Make it easy to discover upcoming dance events in Copenhagen in one place.
- Allow anyone with an account to contribute events with minimal friction.
- Provide machine-readable feeds (iCal, RSS) for calendar integration.
- Keep operational cost and complexity low enough for a single maintainer.

---

## 3. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend framework | Django | Built-in admin, auth, syndication |
| Database | PostgreSQL (Railway managed) | Automatic daily backups on paid plan |
| Frontend | Django templates + HTMX | Dynamic filtering without a JS framework |
| Styling | Tailwind CSS | |
| Markdown rendering | `django-markdownx` + `nh3` | Server-side rendering; sanitized output (see §9.1) |
| Image processing | Pillow | Resize, thumbnail generation, format validation |
| Image storage | Cloudflare R2 via `django-storages` + `boto3` | S3-compatible; free tier (10 GB / 10M reads) |
| Hosting | Railway | Simple Django + Postgres deploys |
| Error tracking | Sentry (free tier) | Django SDK integration |
| Uptime monitoring | UptimeRobot (free tier) | 5-minute checks on homepage |

### 3.1 Application Dependencies

```
django
psycopg[binary]
django-markdownx
nh3
django-storages[boto3]
django-axes
django-environ
Pillow
gunicorn
sentry-sdk[django]
whitenoise
```

### 3.2 What Is Intentionally Excluded from POC

The following are deferred. Do not build them yet.

- **Django REST Framework / API.** No mobile client exists. The feeds (iCal, RSS) cover machine-readable access. Add DRF when a concrete consumer (mobile app, third-party integration) materializes.
- **JWT authentication.** Without an API, there is no need for token auth. Django session auth is used for all web views.
- **Celery / Redis.** No background tasks at POC stage. Scrapers and bots are post-POC features.
- **Full-text search.** Postgres `LIKE` queries on title are sufficient at low volume.

---

## 4. Development Tooling

### 4.1 Core Tools

| Tool | Purpose |
|---|---|
| `uv` | Package and project management. Replaces pip, pip-tools, and virtualenv. |
| `ruff` | Linting and formatting (replaces flake8, isort, black). |
| `ty` | Type checking. Do not add mypy alongside it. |
| `pytest` + `pytest-django` | Test runner. Integrates with Django's database fixtures and settings. |
| `pytest-cov` | Coverage reporting. Set a minimum threshold (80%) in CI. |
| `factory_boy` | Test data factories for Django models. |
| `django-debug-toolbar` | SQL query inspection, template context, request timing. Enabled only when `DEBUG=True`. |
| `django-environ` | Load environment variables from `.env` files during local development. |

### 4.2 Pre-commit Hooks

Install via the `pre-commit` framework. Configuration lives in `.pre-commit-config.yaml`.

Hooks to enable:

| Hook | Source | Purpose |
|---|---|---|
| `ruff check --fix` | `ruff-pre-commit` | Lint and auto-fix |
| `ruff format` | `ruff-pre-commit` | Format code |
| `ty check` | Run as a `local` hook | Type check |
| `check-yaml` | `pre-commit-hooks` | Validate YAML files |
| `check-toml` | `pre-commit-hooks` | Validate TOML files |
| `trailing-whitespace` | `pre-commit-hooks` | Strip trailing whitespace |
| `end-of-file-fixer` | `pre-commit-hooks` | Ensure files end with a newline |

### 4.3 CI Pipeline (GitHub Actions)

Runs on every push and pull request to `main`. Steps:

1. Install dependencies with `uv`.
2. `ruff check` — fail on lint errors.
3. `ruff format --check` — fail on formatting violations.
4. `ty check` — fail on type errors.
5. `pytest --cov --cov-fail-under=80` — fail on test failures or coverage below threshold.

### 4.4 Project Configuration

All tool configuration lives in `pyproject.toml`. Do not create separate `ruff.toml`, `pytest.ini`, `setup.cfg`, or `.coveragerc` files.

```toml
# Example structure (not exhaustive)
[project]
name = "cph-dance-calendar"
requires-python = ">=3.12"

[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["tests.py", "test_*.py"]

[tool.coverage.run]
source = ["events", "accounts"]

[tool.coverage.report]
fail_under = 80
```

---

## 5. Data Models

### 5.1 User

Extends Django `AbstractUser`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `username` | string | |
| `email` | string | Used for login; unique. Never exposed publicly (see §9.6). |
| `is_approved` | boolean | Default `false`; set to `true` after first event is approved |
| `is_moderator` | boolean | Default `false`; grants moderation access |
| `date_joined` | datetime | |

### 5.2 Event

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key (internal) |
| `slug` | string | Auto-generated from `title`; unique; used in public URLs |
| `title` | string | Max 200 chars |
| `description` | text | Stored as raw Markdown; rendered and sanitized on output |
| `image` | image | Optional; stored in R2. Max 4 MB. JPEG, PNG, or WebP only |
| `image_thumbnail` | image | Auto-generated on upload; 400px wide |
| `start_datetime` | datetime | Timezone-aware; must not be more than 1 year in the future |
| `end_datetime` | datetime | Optional; must be after `start_datetime` if provided |
| `venue_name` | string | Free text; max 200 chars |
| `venue_address` | string | Optional free text |
| `category` | enum | See §6.1 |
| `is_free` | boolean | Default `false`; enables "Free events" filter |
| `price_note` | string | Optional free text (e.g. "80–120 DKK", "Pay what you can") |
| `source_url` | URL | Optional link to original announcement. Must be `http` or `https` scheme. |
| `external_source` | string | Optional; e.g. `"dansehallerne"`, `"manual"` |
| `submitted_by` | FK → User | Nullable (reserved for future scraper use) |
| `status` | enum | `pending`, `approved`, `rejected` |
| `rejection_note` | text | Optional; filled by moderator on rejection |
| `created_at` | datetime | |
| `updated_at` | datetime | |

#### Slug Generation

Auto-generate from `title` using `django.utils.text.slugify`. If a collision occurs, append a short random suffix (e.g. `summer-jam-a3f2`). The slug is immutable after creation — editing the title does not change the slug, so that URLs remain stable.

---

## 6. Domain Rules

### 6.1 Event Categories

| Value | Description |
|---|---|
| `performance` | Ticketed or public performance |
| `workshop` | Instructional session |
| `work_in_progress` | Showing of work in development |
| `open_practice` | Informal open floor / jam |
| `social` | Social dance event |
| `other` | Anything else; user may clarify in description |

This list will grow. Use a database-backed choice field or a separate `Category` model if you find yourself adding values more than twice a year.

### 6.2 Moderation Flow

1. New user registers → account flagged `is_approved = false`.
2. User submits an event → event created with `status = pending`.
3. Moderator approves the user's first event → event status becomes `approved`, user's `is_approved` is set to `true`.
4. All subsequent events by approved users are published immediately (`status = approved` on creation).
5. Moderators can reject or unpublish any event at any time.
6. On rejection, the moderator may provide a `rejection_note`. The submitter sees this note on their event management page.
7. A rejected event can be edited and resubmitted by the owner, which sets it back to `pending`.

### 6.3 Event Ownership

- Only the submitting user or a moderator may edit or delete an event.
- No re-moderation is triggered on edits by an already-approved user.
- Scraper-submitted events (`submitted_by = null`) are only editable by moderators.

### 6.4 Event Validation Rules

These are enforced at the model/form level:

- `start_datetime` must be in the future at time of creation. (Editing an existing event does not re-validate this.)
- `start_datetime` must not be more than 1 year from today.
- If `end_datetime` is provided, it must be after `start_datetime`.
- `title` is required and must be between 3 and 200 characters.
- `image` must be ≤ 4 MB and one of: JPEG, PNG, WebP.
- `source_url` must be a valid URL with `http` or `https` scheme if provided. Reject all other schemes (including `javascript:`).
- `slug` must be unique.

### 6.5 Timezone Handling

All datetimes are stored as UTC in the database (`USE_TZ = True`). The application timezone is `Europe/Copenhagen`. All user-facing display and form input uses Copenhagen local time. Be aware of DST transitions (last Sunday of March and October) — Django's timezone support handles this correctly as long as you always use `timezone.now()` and never `datetime.now()`.

---

## 7. Features

### 7.1 Event Listings (Public)

- Paginated list of upcoming approved events, sorted by `start_datetime` ascending.
- Toggle: **Upcoming** (default) vs **Past** events.
- Filter by **category** (multi-select checkboxes).
- Filter by **date range** (start date / end date pickers).
- Filter by **free events** (toggle).
- Each listing shows: title, date/time, venue, category badge, thumbnail (if image exists).
- Filtering is handled via HTMX partial page swaps — no full page reloads.

### 7.2 Event Detail Page

- Clean permalink: `/events/<slug>/`
- Full event info including sanitized Markdown-rendered description.
- Event image displayed if present.
- Link back to source if `source_url` is set.
- Attribution line if `external_source` is set.
- "Report" or "Suggest edit" mailto link to a moderator contact address (simple first step; no in-app reporting flow at POC).

### 7.3 User Authentication

- Register with email + password.
- Login / logout.
- Password reset via email. The reset view always displays "If an account with that email exists, we've sent a reset link" regardless of whether the email is registered, to prevent account enumeration.
- Django's built-in password validation (minimum length, common password check). Stronger enforcement deferred to post-POC.

### 7.4 Event Submission

- Authenticated users only.
- Form fields map to the Event model (§5.2).
- Description field uses `django-markdownx` for a live Markdown preview.
- Optional single image upload per event. On upload, the server validates format and size, resizes if wider than 1600px, and generates a 400px-wide thumbnail.
- Submitted event enters moderation queue if `user.is_approved` is `false`; otherwise published immediately.

### 7.5 Event Management (Authenticated)

- User can view all their submitted events with status indicators (`pending`, `approved`, `rejected`).
- Rejected events show the `rejection_note` from the moderator.
- User can edit their own events. Editing a rejected event resets its status to `pending`.
- User can delete their own events. Deletion is immediate and permanent (soft-delete is not implemented at POC).

### 7.6 Moderation (Admin / Moderator)

- Moderation queue listing all `status = pending` events, sorted oldest first.
- Approve / reject actions. Rejection requires a note.
- Edit any event.
- Promote users to moderator.
- Django admin panel is the primary moderation UI. A dedicated moderation page is a post-POC improvement.
- Django admin logs all moderator actions (approve, reject, edit, delete) automatically. Moderators should be informed that their actions are logged for accountability.

### 7.7 Feed Subscriptions

- **iCal feed:** `/feed/events.ics` — all upcoming approved events; subscribable in calendar apps.
- **RSS feed:** `/feed/events.rss` — recently approved events.

Both feeds support optional category filtering via query parameter, e.g. `?category=workshop`.

Feeds contain event data only (title, description, dates, venue). They never expose submitter identity — no username, no email.

### 7.8 Account Deletion

Authenticated users can delete their own account. On deletion:

- The user record is permanently deleted.
- All events submitted by the user have `submitted_by` set to `null` (anonymized), preserving community data.
- The user is logged out and redirected to the homepage.

This is required for GDPR compliance (see §9.7).

---

## 8. URL Structure

```
/                              → Upcoming events list (public)
/events/<slug>/                → Event detail (public)
/events/submit/                → Submit event form (auth required)
/events/<slug>/edit/           → Edit event (owner or mod)
/events/<slug>/delete/         → Confirm and delete event (owner or mod)
/my-events/                    → User's submitted events (auth required)
/accounts/register/            → Registration
/accounts/login/               → Login
/accounts/logout/              → Logout
/accounts/password-reset/      → Password reset
/accounts/delete/              → Account deletion (auth required)
/privacy/                      → Privacy notice (public)
/feed/events.ics               → iCal feed
/feed/events.rss               → RSS feed
/admin/                        → Django admin (superuser / moderator)
```

---

## 9. Security and Privacy

### 9.1 Markdown / XSS

Event descriptions are stored as raw Markdown and rendered to HTML on the server using `django-markdownx`. **The rendered HTML must be sanitized before output.** Use the `nh3` library (Rust-based, fast, secure) to strip all tags except a safe allowlist.

Allowed tags: `p`, `a`, `strong`, `em`, `ul`, `ol`, `li`, `h2`, `h3`, `h4`, `br`, `blockquote`, `code`, `pre`.

Allowed attributes: `href` on `a` only. All `href` values must be `http`, `https`, or `mailto` schemes.

This sanitization is applied in a custom template filter so that it is impossible to render unsanitized Markdown anywhere in the application.

### 9.2 Template Auto-escaping

Django's template auto-escaping is the primary defense against XSS for all non-Markdown user fields (`title`, `venue_name`, `price_note`, etc.). **Never use `|safe` or `{% autoescape off %}` on any user-provided field.** The only exception is the Markdown description output, which is pre-sanitized via `nh3` (§9.1).

### 9.3 URL Scheme Validation

The `source_url` field is rendered as a clickable link. Validate at the model/form level that the scheme is `http` or `https`. Reject all other schemes. A `javascript:` URL in this field is an XSS vector.

### 9.4 CSRF

Django's CSRF middleware is enabled (default). All POST forms include `{% csrf_token %}`. HTMX is configured to include the CSRF token in its headers via `hx-headers` on the `<body>` tag.

### 9.5 Image Upload

- Validate MIME type server-side using Pillow (do not trust the `Content-Type` header from the browser).
- Reject files > 4 MB.
- Strip EXIF metadata on upload by re-saving the image without EXIF data via Pillow. EXIF can contain GPS coordinates, device identifiers, and timestamps — stripping it protects submitter privacy.
- Serve images from R2, never from the application server.

### 9.6 User Email Privacy

User email addresses are collected solely for authentication and password recovery. They are **never** exposed in:

- Public event listings or detail pages.
- iCal or RSS feeds.
- Any future API responses.

Where event attribution is shown, use the `username` field. Email is visible only to the user themselves and to Django admin superusers.

### 9.7 GDPR Compliance

The application processes personal data of EU residents. Minimum requirements for POC:

- **Privacy notice** at `/privacy/` explaining: what data is collected (email, username, submitted content), why (account management, event attribution), how long it is retained, and who to contact for data requests.
- **Account deletion** (§7.8) — users can delete their account at any time. Events are anonymized, not deleted.
- **No analytics cookies.** The application uses only Django's session cookie, which is exempt from consent requirements as it is strictly necessary for functionality.
- **No third-party tracking.** No Google Analytics, no Facebook Pixel, no advertising scripts.

### 9.8 Authentication Security

**Session cookies.** Set in production settings:

```python
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
```

**Brute-force protection.** `django-axes` is included in dependencies. It locks out IP addresses after a configurable number of failed login attempts. Configure:

- Lockout after 5 failed attempts.
- Lockout duration: 30 minutes.
- Log all failed attempts.

**Account enumeration.** The password reset view is hardened (§7.3). The registration view will reject duplicate emails, which does leak that an email is registered. This is an accepted tradeoff at POC scale — the alternative (deferred registration confirmation) adds significant complexity.

### 9.9 Production Django Settings

These settings must be active when `DEBUG = False`:

```python
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
```

### 9.10 Content Security Policy

Set via Django middleware (`django-csp` or custom middleware):

```
default-src 'self';
img-src 'self' <R2_BUCKET_URL>;
style-src 'self' 'unsafe-inline';
script-src 'self' 'unsafe-inline';
```

Tighten `script-src` and `style-src` once you know the exact inline requirements of HTMX and Tailwind.

### 9.11 Rate Limiting

Deferred to post-POC. When implemented, apply to: registration, login (supplementing `django-axes`), event submission, and password reset. Use `django-ratelimit` or reverse proxy rules.

### 9.12 What Is Deferred

- CAPTCHA on registration — low abuse risk at POC scale.
- Two-factor authentication — overkill for a community calendar.
- Penetration testing — not warranted until there is real traffic.
- Cookie consent banner — no optional cookies are set (§9.7).

---

## 10. Infrastructure

### 10.1 Hosting

Railway is the primary host. A single web process runs gunicorn behind Railway's reverse proxy. Static files are served via WhiteNoise.

### 10.2 Image Storage

Event images and thumbnails are stored in a Cloudflare R2 bucket, accessed via the S3-compatible API through `django-storages`. R2 credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`) are stored as environment variables in Railway.

Public read access is enabled on the R2 bucket so images can be served directly via Cloudflare's CDN. The application never proxies image downloads.

### 10.3 Database

Railway managed PostgreSQL. Key settings:

- Automatic daily backups (included with Railway paid plan).
- Single instance; no replication needed at this scale.
- Optional: weekly `pg_dump` to R2 as an additional safety net (manual or via Railway cron).

### 10.4 Deployment

Railway builds from a `Dockerfile` or `nixpacks` (auto-detected). Deploy process:

1. Push to `main` branch triggers build.
2. Railway builds new container.
3. Health check passes.
4. Traffic swaps to new container.
5. Old container is killed.

This is effectively zero-downtime. Database migrations that require table locks should be run during low-traffic hours as a precaution, but at POC traffic levels this is not a real concern.

### 10.5 Environment Variables

All secrets and config are stored as Railway environment variables. Never commit secrets to the repository. Required variables:

```
SECRET_KEY
DATABASE_URL
ALLOWED_HOSTS
DEBUG
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME
AWS_S3_ENDPOINT_URL
SENTRY_DSN
EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
```

### 10.6 Monitoring

| Concern | Tool | Notes |
|---|---|---|
| Uptime | UptimeRobot | Free; 5-min interval; email alerts |
| Errors | Sentry | Free tier; catches unhandled exceptions |
| Logs | Railway dashboard | Streams stdout/stderr from the web process |

No APM, metrics, or log aggregation at POC stage.

### 10.7 Estimated Monthly Cost

| Service | Cost |
|---|---|
| Railway (app + Postgres) | ~$5–10 |
| Cloudflare R2 | Free tier |
| UptimeRobot | Free tier |
| Sentry | Free tier |
| **Total** | **~$5–10/mo** |

---

## 11. Testing Strategy

### 11.1 What to Test

| Area | Type | Priority | Examples |
|---|---|---|---|
| Moderation flow | Unit + integration | High | Unapproved user submits event → pending. Approve event → user becomes approved. Next event is auto-approved. Reject event → note visible. Resubmit → back to pending. |
| Permissions | Unit | High | Non-owner cannot edit. Non-mod cannot access moderation. Anonymous cannot submit. |
| Event validation | Unit | High | Past dates rejected. End before start rejected. Slug uniqueness. Image size limit. URL scheme validation. |
| Markdown sanitization | Unit | High | Script tags stripped. Allowed tags preserved. `javascript:` hrefs removed. |
| Account deletion | Integration | High | User deleted. Events anonymized. Session invalidated. |
| iCal/RSS feeds | Integration | Medium | Feed returns only approved upcoming events. Category filter works. Valid iCal/RSS output. No submitter identity exposed. |
| Image upload pipeline | Integration | Medium | Oversize rejected. EXIF stripped. Thumbnail generated. Invalid MIME rejected. |
| Authentication | Integration | Medium | Register, login, logout, password reset. Account enumeration hardened on reset. |
| Brute-force protection | Integration | Medium | Login locked after 5 failures. Unlocked after timeout. |

### 11.2 How to Test

Use `pytest` with `pytest-django`. Use `factory_boy` for creating test data. Run tests in CI (GitHub Actions) on every push. Enforce ≥80% coverage via `pytest-cov`.

### 11.3 What Not to Test at POC

- Frontend rendering / visual regression.
- Performance or load testing.
- End-to-end browser tests (Selenium, Playwright).

---

## 12. Edge Cases and Behavior Notes

These are decisions you should not have to make at implementation time. They are made here.

| Scenario | Behavior |
|---|---|
| User edits event title | Slug does not change. URL remains stable. |
| User edits a rejected event | Status resets to `pending`. Goes back into moderation queue. |
| User submits event with past `start_datetime` | Rejected by form validation. Error message shown. |
| User edits old event; `start_datetime` is now in the past | Allowed. The "must be future" rule only applies on creation. |
| Moderator rejects event without a note | Not allowed. Rejection note is required. |
| User deletes own approved event | Removed immediately from listings and feeds. Permanent. |
| User deletes own account | Account removed. All their events have `submitted_by` set to `null`. Events remain visible. |
| Two events with the same title | Different slugs (suffix appended to the second). |
| Image upload fails midway | Event is saved without an image. User can retry by editing. |
| User account is deactivated by admin | User's approved events remain visible. User cannot log in or submit/edit. |
| Approved user is later un-approved (set `is_approved = false`) | Subsequent events go to moderation queue again. Existing approved events remain. |

---

## 13. Future Features (Post-POC)

Listed roughly by priority. None of these should influence POC architecture decisions except where noted in the spec above.

1. **Registration approval flow** — users submit a short intro message at registration; moderator reviews before activating the account.
2. **Dedicated moderation UI** — a standalone page instead of relying on Django admin.
3. **REST API via DRF** — when a mobile client or third-party integration is needed.
4. **Rate limiting** — protect registration, login, submission, and password reset.
5. **Password strength enforcement** — `zxcvbn` or `django-password-validators`.
6. **Dansehallerne scraper** — Celery + Redis scheduled import; scraped events enter the moderation queue.
7. **Mastodon bot** — auto-post new approved events.
8. **Recurring events** — support for weekly/monthly repeat patterns.
9. **Map view** — venue locations on a map.
10. **Full-text search** — Postgres `tsvector` or a search service.
11. **Bilingual support (DA / EN)** — Django's `i18n` framework.
