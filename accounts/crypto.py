import hashlib
import hmac

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet() -> Fernet:
    return Fernet(settings.EMAIL_ENCRYPTION_KEY.encode())


def encrypt_email(email: str) -> bytes:
    """Encrypt an email address using Fernet symmetric encryption."""
    return _fernet().encrypt(email.lower().encode())


def decrypt_email(ciphertext: bytes) -> str:
    """Decrypt a Fernet-encrypted email address."""
    return _fernet().decrypt(bytes(ciphertext)).decode()


def hash_email(email: str) -> str:
    """Compute an HMAC-SHA256 blind index of an email for DB lookups."""
    pepper = settings.EMAIL_BLIND_INDEX_PEPPER.encode()
    return hmac.new(pepper, email.lower().encode(), hashlib.sha256).hexdigest()
