# pleskal

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)

A hyperlocal community-driven calendar for dance and performance art events in Copenhagen.

Inspired by [dukop.dk](https://dukop.dk/en/).

## Why pleskal?

Copenhagen has a vibrant dance scene spread across many venues, studios, and organizers — but no single place to find it all. _pleskal_ brings upcoming dance events together in one calendar that anyone can contribute to, with machine-readable feeds (iCal, RSS) for easy calendar integration.

## Tech Stack

- **Backend:** Django 6 · Python 3.13+
- **Database:** PostgreSQL (production) · SQLite (dev)
- **Frontend:** Django templates + HTMX
- **Styling:** Tailwind CSS 4
- **Deployment:** Railway
- **Image storage:** Cloudflare R2

## Getting Started

```bash
uv sync --dev            # Install dependencies
npm ci                   # Install Tailwind
npm run css:build        # Build CSS

uv run python manage.py migrate
uv run python manage.py runserver
```

Copy `.env.example` to `.env` for local configuration.

## Running Tests

```bash
uv run pytest
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
