"""Custom Django password hasher using HMAC-SHA256 as a server-side pepper.

Passwords are processed in two stages before storage:

1. **Pepper** — the raw password is passed through HMAC-SHA256 keyed with a
   server-side secret (``PASSWORD_PEPPER`` in settings).  This means that even
   a full database dump is useless to an attacker without the pepper key.

2. **Hash** — the peppered value is fed into Django's standard PBKDF2-SHA256
   hasher, providing the usual brute-force resistance.

Migration path for existing password hashes
--------------------------------------------
``PASSWORD_HASHERS`` lists this hasher *first* (new/updated passwords) and the
plain ``PBKDF2PasswordHasher`` *second* (legacy hashes).  Django automatically
re-hashes a legacy password with the primary hasher on the next successful
login, so the transition is transparent to users.
"""

import base64

from django.conf import settings
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.exceptions import ImproperlyConfigured

from config.crypto import hmac_sha256

# Insecure all-zeros pepper used in development when PASSWORD_PEPPER is unset.
_DEV_PEPPER_HEX = "00" * 32


def _get_pepper() -> bytes:
    """Return the pepper key as raw bytes.

    Raises :class:`~django.core.exceptions.ImproperlyConfigured` in production
    if ``PASSWORD_PEPPER`` is not set.
    """
    pepper_hex: str = getattr(settings, "PASSWORD_PEPPER", "")
    if not pepper_hex:
        if settings.DEBUG:
            return bytes.fromhex(_DEV_PEPPER_HEX)
        raise ImproperlyConfigured(
            "PASSWORD_PEPPER must be set in production. "
            "Generate a value with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    try:
        key = bytes.fromhex(pepper_hex)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "PASSWORD_PEPPER must be a hex-encoded string (e.g. 64 hex characters "
            "for a 32-byte key)."
        ) from exc
    if len(key) != 32:
        raise ImproperlyConfigured(
            f"PASSWORD_PEPPER must decode to exactly 32 bytes; got {len(key)}."
        )
    return key


def _apply_pepper(password: str) -> str:
    """Apply HMAC-SHA256 pepper to *password* and return a base64-encoded string."""
    peppered = hmac_sha256(_get_pepper(), password.encode())
    return base64.b64encode(peppered).decode()


class HmacPepperedPasswordHasher(PBKDF2PasswordHasher):
    """PBKDF2-SHA256 with an HMAC-SHA256 server-side pepper.

    Stored hashes are prefixed with ``hmac_pbkdf2_sha256$`` so they are
    clearly distinct from un-peppered hashes and the right hasher is always
    selected automatically by Django.
    """

    algorithm = "hmac_pbkdf2_sha256"

    def encode(self, password: str, salt: str, iterations: int | None = None) -> str:
        return super().encode(_apply_pepper(password), salt, iterations)

    # verify() is intentionally NOT overridden: PBKDF2PasswordHasher.verify()
    # calls self.encode() internally, which already applies the pepper.
