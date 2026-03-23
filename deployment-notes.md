# Deployment Notes

## Weekly digest cron job (Railway)

The `weekly_digest` management command emails growth and activity stats to `ADMINS`.
Schedule it in Railway as a Cron Job service (separate from the web process):

- **Schedule:** `0 8 * * 1` (every Monday at 08:00 UTC)
- **Command:** `python manage.py weekly_digest`

The command requires `ADMINS` and `RESEND_API_KEY` to be set. Run a one-off test
before scheduling:

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
