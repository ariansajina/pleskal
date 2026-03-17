# Pleskal — Copenhagen Dance Calendar

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=ariansajina_pleskal&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=ariansajina_pleskal)

A local-first, crowd-sourced web application for discovering and sharing dance events in Copenhagen. Anyone can submit an event; approved users can post freely. Community-maintained and editorially neutral.

Inspired by [dukop.dk](https://dukop.dk/en/).

## Why Pleskal?

Copenhagen has a vibrant dance scene spread across many venues, studios, and organizers — but no single place to find it all. Pleskal brings upcoming dance events together in one calendar that anyone can contribute to, with machine-readable feeds (iCal, RSS) for easy calendar integration.

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
uv run pytest            # Run all tests
uv run pytest --cov      # With coverage report
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
