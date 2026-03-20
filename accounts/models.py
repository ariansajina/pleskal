import uuid

from django import forms as django_forms
from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


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

    def formfield(self, **kwargs):
        return django_forms.EmailField(**kwargs)


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = EncryptedEmailField(db_column="email_encrypted")
    email_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    display_name = models.CharField(blank=True, max_length=100)
    bio = models.TextField(blank=True, max_length=500)
    website = models.URLField(blank=True)
    intro_message = models.TextField(blank=True, max_length=500)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        from .crypto import hash_email

        if self.email:
            self.email_hash = hash_email(self.email)
        super().save(*args, **kwargs)

    @property
    def public_name(self):
        return self.display_name if self.display_name else self.username
