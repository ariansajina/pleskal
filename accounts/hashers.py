"""Custom Django password hasher using HMAC-SHA256 as a server-side pepper,
applied before Argon2id hashing.

Passwords are processed in two stages before storage:

1. **Pepper** — the raw password is passed through HMAC-SHA256 keyed with a
   server-side secret (``PASSWORD_PEPPER`` in settings).  This means that even
   a full database dump is useless to an attacker without the pepper key.

2. **Hash** — the peppered value is fed into Django's Argon2id hasher,
   providing strong brute-force resistance.

``PASSWORD_HASHERS`` lists this hasher first (new/updated passwords) and plain
``PBKDF2PasswordHasher`` as a fallback for any legacy hashes.  Django
automatically re-hashes a legacy password with the primary hasher on the next
successful login, so the transition is transparent to users.
"""

import base64
import hashlib
import hmac

from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher
from django.core.exceptions import ImproperlyConfigured

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
    peppered = hmac.new(_get_pepper(), password.encode(), hashlib.sha256).digest()
    return base64.b64encode(peppered).decode()


class HmacPepperedArgon2PasswordHasher(Argon2PasswordHasher):
    """Argon2id with an HMAC-SHA256 server-side pepper.

    The parent's ``encode`` returns ``self.algorithm + "$argon2id$..."``.
    Setting ``algorithm = "hmac_argon2"`` makes stored hashes begin with
    ``hmac_argon2$argon2id$…``, distinguishing them from plain Argon2 hashes
    and ensuring Django always selects this hasher when reading them back.

    ``verify`` and ``must_update`` strip the custom prefix before delegating
    to the parent, which expects the raw ``argon2$argon2id$…`` format.
    """

    algorithm = "hmac_argon2"

    def encode(self, password: str, salt: str) -> str:
        return super().encode(_apply_pepper(password), salt)

    def _argon2_rest(self, encoded: str) -> str:
        """Return the argon2 hash string without our custom algorithm prefix."""
        # encoded: "hmac_argon2$argon2id$..."  →  "$argon2id$..."
        return encoded[len("hmac_argon2") :]

    def verify(self, password: str, encoded: str) -> bool:
        argon2 = self._load_library()
        try:
            return argon2.PasswordHasher().verify(
                self._argon2_rest(encoded), _apply_pepper(password)
            )
        except argon2.exceptions.VerificationError:
            return False

    def decode(self, encoded: str) -> dict:
        argon2 = self._load_library()
        rest = self._argon2_rest(encoded)  # "$argon2id$..."
        params = argon2.extract_parameters(rest)
        variety, *_, b64salt, hash_ = rest.lstrip("$").split("$")
        b64salt += "=" * (-len(b64salt) % 4)
        salt = __import__("base64").b64decode(b64salt).decode("latin1")
        return {
            "algorithm": self.algorithm,
            "hash": hash_,
            "memory_cost": params.memory_cost,
            "parallelism": params.parallelism,
            "salt": salt,
            "time_cost": params.time_cost,
            "variety": variety,
            "version": params.version,
            "params": params,
        }
