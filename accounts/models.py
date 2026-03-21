import secrets
import string
import uuid

from django import forms as django_forms
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone

from .managers import UserManager

# Characters for claim codes — excludes ambiguous O/0/I/1/L
CLAIM_CODE_ALPHABET = string.ascii_uppercase + string.digits
CLAIM_CODE_ALPHABET = "".join(c for c in CLAIM_CODE_ALPHABET if c not in "O0I1L")
CLAIM_CODE_LENGTH = 8


class EncryptedEmailField(models.BinaryField):
    """Store email as Fernet-encrypted bytes.

    Transparent encrypt/decrypt on DB read/write. Use ``email_hash`` (an
    HMAC blind index) for uniqueness constraints and all lookups — never
    filter on this field directly, since each encryption produces different
    ciphertext.
    """

    def __init__(self, *args, **kwargs):
        kwargs["editable"] = True
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("editable", None)
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        from .crypto import decrypt_email

        if value is None:
            return ""
        return decrypt_email(bytes(value))

    def get_db_prep_save(self, value, connection):
        from .crypto import encrypt_email

        if not value:
            return None
        return encrypt_email(str(value))

    def to_python(self, value):
        from .crypto import decrypt_email

        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, memoryview)):
            return decrypt_email(bytes(value))
        return value or ""

    def formfield(self, form_class=None, choices_form_class=None, **kwargs):
        return django_forms.EmailField(**kwargs)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = EncryptedEmailField(db_column="email_encrypted", null=True, blank=True)
    email_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    display_name = models.CharField(blank=True, max_length=100)
    bio = models.TextField(blank=True, max_length=500)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return str(self.email) or str(self.pk)

    def get_username(self):
        return str(self.email)

    def save(self, *args, **kwargs):
        from .crypto import hash_email

        email = str(self.email)
        if email:
            self.email_hash = hash_email(email)
        super().save(*args, **kwargs)

    @property
    def public_name(self):
        return self.display_name if self.display_name else str(self.email).split("@")[0]


def generate_claim_code():
    """Generate a single random claim code using secrets."""
    return "".join(
        secrets.choice(CLAIM_CODE_ALPHABET) for _ in range(CLAIM_CODE_LENGTH)
    )


class ClaimCode(models.Model):
    objects = models.Manager["ClaimCode"]()
    DoesNotExist: type[ObjectDoesNotExist]

    code = models.CharField(max_length=CLAIM_CODE_LENGTH, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claim_codes",
    )

    class Meta:
        db_table = "accounts_claimcode"

    def __str__(self):
        return self.code

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_claimed(self):
        return self.claimed_by is not None

    @property
    def is_valid(self):
        return not self.is_expired and not self.is_claimed
