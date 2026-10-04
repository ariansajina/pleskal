# pleskal

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/C0C01WCJDK)

A hyperlocal community-driven calendar for dance and performance art events in Copenhagen.

Inspired by [dukop.dk](https://dukop.dk/en/).

## Why pleskal?

Copenhagen has a vibrant dance scene spread across many venues, studios, and organizers — but no single place to find it all. _pleskal_ brings upcoming dance events together in one calendar that anyone can contribute to, with machine-readable feeds (iCal, RSS) for easy calendar integration.

## Features

- **Event calendar** with filters (category, publisher, dates, free, wheelchair accessible) and search
- **Recurring events** (daily / weekly / monthly rules, edited per date, from a date on, or all) and multi-date shows, listed as one card
- **Scraped venue programmes** from about ten Copenhagen venues, imported daily, with Danish descriptions machine-translated to English offline
- **Feeds:** iCal and RSS (filterable by category and publisher), per-event and per-series `.ics` downloads, Apple/Google calendar links
- **Invite-only publishing** via claim codes; drafts, publisher profiles and a publisher directory
- **Installable PWA** with light and dark themes
- **Cookieless analytics**, so no consent banner

## Tech Stack

- **Backend:** Django 6 · Python 3.14+
- **Database:** PostgreSQL (production) · SQLite (dev fallback)
- **Frontend:** Django templates + HTMX
- **Styling:** Tailwind CSS 4
- **Translation:** lingua + an Argos Translate da→en model via CTranslate2
- **Deployment:** Railway
- **Image storage:** Cloudflare R2

## Getting Started

Requires [uv](https://docs.astral.sh/uv/) and Node.js (for the Tailwind build).

```bash
cp .env.example .env     # then set SECRET_KEY and PASSWORD_PEPPER
docker compose up -d     # local PostgreSQL (or set DATABASE_URL=sqlite:///db.sqlite3 in .env)

uv sync --dev            # Install Python dependencies
npm ci                   # Install Tailwind
npm run css:build        # Build CSS (or `npm run css:watch` while editing templates)

uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Generate a pepper with `python -c "import secrets; print(secrets.token_hex(32))"`. Registration is invite-only: create codes with `uv run python manage.py generate_claim_codes --count 5 --expires 2027-12-31`.

To fill the calendar with real events, create the scraper accounts and run the scrapers:

```bash
uv run python manage.py create_source_accounts
uv run python manage.py run_scrapers --skip-images
```

## Running Tests

```bash
uv run pytest            # parallel (-n 8), reuses the test DB
uv run pytest --cov      # with coverage
```

Lint, format and type checks run as pre-commit hooks (`uv run pre-commit install`): ruff and [ty](https://github.com/astral-sh/ty).

## Documentation

- [`CLAUDE.md`](CLAUDE.md): architecture, models, conventions and commands in detail
- [`deployment-notes.md`](deployment-notes.md): production setup on Railway, crons and monitoring

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
