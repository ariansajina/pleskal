# Deployment Notes

## Environments

The Railway project has two environments:

| Environment | Trigger | Purpose |
|---|---|---|
| `staging` | Auto-deploys on every push to `main` | Pre-production testing |
| `production` | Deploys only when a `v*` tag is pushed to GitHub | Live site |

Each environment has its own Postgres database, R2 bucket, and secrets. The two
must never share `PASSWORD_PEPPER` (different DBs require different peppers) or
`SECRET_KEY`.

### Staging environment specifics

- Only the web service is provisioned — there are no cron services in staging
- `DEBUG=false` (mirror production behaviour)
- `SENTRY_ENVIRONMENT=staging` so errors are tagged separately in Sentry
- `RESEND_API_KEY` **unset** — emails fall back to the console backend so staging
  never sends mail to real users or syncs contacts to the Resend CRM segment
- Run scrapers manually against staging when testing scraper changes:
  ```bash
  railway run --environment staging --service web-service python manage.py run_scrapers --dry-run
  ```
- `SITE_DOMAIN` / `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` point at the staging
  Railway subdomain

### Production environment specifics

- GitHub auto-deploy is **disabled** on the production service. Deploys only
  happen via the `Deploy to production` GitHub Actions workflow on tag push.
- `SENTRY_ENVIRONMENT=production`
- Scraper and backup cron services run on schedule (see below).

## Cutting a release

1. Merge changes to `main`. Staging auto-deploys; smoke-test there.
2. From a clean `main`, create an annotated tag:
   ```bash
   git pull origin main
   git tag -a v1.4.0 -m "Release 1.4.0"
   git push origin v1.4.0
   ```
3. The `Deploy to production` workflow triggers on the tag push and waits for
   manual approval (GitHub Environment: `production`). Approve it from the
   Actions tab and the workflow runs `railway up` against the production
   service.
4. If the deploy fails, fix forward on `main` and cut a new tag (e.g.
   `v1.4.1`). Do not re-tag the same commit.

### Required GitHub secrets

| Secret | Source |
|---|---|
| `RAILWAY_TOKEN` | Railway Account Settings → Tokens → project token, scoped to the production environment |
| `RAILWAY_PROD_SERVICE_ID` | Production web service Settings page (UUID) |
| `RAILWAY_PROD_SCRAPE_CRON_SERVICE_ID` | Production scrape-cron service Settings page (UUID) |
| `RAILWAY_PROD_BACKUP_CRON_SERVICE_ID` | Production backup-cron service Settings page (UUID) |

### Required GitHub configuration

- **Tag protection rule** for pattern `v*` (Settings → Tags) — restricts who can
  create release tags
- **Environment** named `production` (Settings → Environments) with a required
  reviewer — gates each prod deploy behind a manual approval click
- **Branch protection** on `main` — require CI to pass before merge so staging
  never auto-deploys broken code

## Rollback

To roll back production to a previous release, push the older tag to a fresh
tag name (Railway will rebuild from that commit):

```bash
git tag -a v1.3.9-rollback v1.3.9^{} -m "Rollback to v1.3.9"
git push origin v1.3.9-rollback
```

Approve the workflow run in GitHub Actions. Alternatively, redeploy the previous
successful build directly from the Railway dashboard (Deployments → Redeploy).

---

## Event scrapers cron job (Railway, production only)

The `run_scrapers` management command scrapes all external sources
(dansehallerne, dansehallerne\_workshops, hautscene, sydhavnteater, kbhdanser,
toastercph) and imports events into the database in a single run. It runs as a
scheduled Cron Job service in the **production** environment only.

### Setup

1. In the Railway dashboard, click **+ New** → **Cron Job** inside the production
   environment.
2. Connect the same GitHub repo and `main` branch as the web service.
3. Configure:

| Setting | Value |
|---|---|
| **Config file path** | `railway.scrape-cron.toml` |
| **Cron schedule** | `0 6 * * *` (daily at 06:00 UTC / 07:00–08:00 CET/CEST) |

   `railway.scrape-cron.toml` sets the start command (`python manage.py
   run_scrapers`) — no separate dashboard overrides needed.

   `run_scrapers` already calls all `import_*` commands internally: it scrapes
   each source, writes a temp JSON file, and invokes the corresponding
   importer.

4. Under **Variables**, reference the same environment variables as the web
   service. Required: `DATABASE_URL`, `SECRET_KEY`, `PASSWORD_PEPPER`.
   Optional: `R2_*` vars (if scraper images should upload to R2), `SENTRY_DSN`.

The staging environment has no scraper cron service. Test scraper changes
manually against staging via the web service:

```bash
railway run --environment staging --service web-service python manage.py run_scrapers --dry-run
railway run --environment staging --service web-service python manage.py run_scrapers --only hautscene
railway run --environment staging --service web-service python manage.py run_scrapers --skip-images
```

If `railway run` fails to resolve `postgres.railway.internal`, use
`railway shell` instead — internal DNS only works from inside Railway's network.

### Notes

- Each source runs independently; a failure in one does not block the others.
- The command exits with code 1 if any source fails, which Railway will flag as
  a failed run.
- Logs appear in the Railway service's **Logs** tab.
- To run twice daily instead, change the schedule to `0 6,18 * * *`.

---

## Weekly digest cron job (Railway, production only)

The `weekly_digest` management command emails growth and activity stats to
`ADMINS`. Schedule it in Railway as a Cron Job service in the production
environment (separate from the web process):

- **Schedule:** `0 8 * * 1` (every Monday at 08:00 UTC)
- **Command:** `python manage.py weekly_digest`

The command requires `ADMINS` and `RESEND_API_KEY` to be set. Run a one-off
test before scheduling:

```bash
python manage.py weekly_digest --dry-run   # prints to stdout, no email sent
python manage.py weekly_digest             # sends immediately
```

## Password hashing & disaster recovery

Passwords are hashed, not encrypted — they are never stored in a recoverable form.
On login, the same one-way derivation is re-run and the result is compared to the
stored hash. Nothing is ever "decrypted".

The derivation pipeline is:

```
raw_password → HMAC-SHA256(PASSWORD_PEPPER, raw_password) → PBKDF2-SHA256 → stored hash
```

### What to back up

| Secret | Where it lives | If lost |
|---|---|---|
| Database (password hashes) | DB backup | Passwords cannot be verified at all |
| `PASSWORD_PEPPER` | Env var / secrets manager | Passwords cannot be verified even with the DB |
| `SECRET_KEY` | Env var / secrets manager | Sessions invalidated, CSRF tokens broken |

To restore on a new machine you need both the DB backup **and** the secret
environment variables. Store them in a secrets manager (e.g. AWS Secrets Manager,
HashiCorp Vault, or Railway environment variables) that is independent of the
application server.

### Generating secrets

```bash
# PASSWORD_PEPPER — 32-byte hex string
python -c "import secrets; print(secrets.token_hex(32))"

# SECRET_KEY — Django secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### If PASSWORD_PEPPER is permanently lost

Existing password hashes become unverifiable. User accounts and all their data
survive in the database, but users will need to reset their passwords via the
forgot-password flow (which authenticates via email, not the stored hash).
