import secrets
import string
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .managers import UserManager

# Characters for claim codes — excludes ambiguous O/0/I/1/L
CLAIM_CODE_ALPHABET = string.ascii_uppercase + string.digits
CLAIM_CODE_ALPHABET = "".join(c for c in CLAIM_CODE_ALPHABET if c not in "O0I1L")
CLAIM_CODE_LENGTH = 8


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(blank=True, max_length=100)
    display_name_slug = models.SlugField(max_length=110, unique=True, blank=True)
    bio = models.TextField(blank=True, max_length=2000)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_system_account = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.display_name_slug:
            base = (
                slugify(self.display_name)
                if self.display_name
                else f"user-{secrets.token_hex(4)}"
            )
            slug = base or str(self.pk)[:8]
            # Ensure uniqueness by appending a counter if needed.
            candidate = slug
            counter = 1
            while (
                User.objects.filter(display_name_slug=candidate)
                .exclude(pk=self.pk)
                .exists()
            ):
                candidate = f"{slug}-{counter}"
                counter += 1
            self.display_name_slug = candidate
        super().save(*args, **kwargs)

    @property
    def public_name(self):
        return self.display_name if self.display_name else "Anonymous"


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
    claimed_by_email = models.EmailField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_claim_codes",
    )
    created_by_email = models.EmailField(blank=True, default="")

    class Meta:
        db_table = "accounts_claimcode"

    def __str__(self):
        return self.code

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_claimed(self):
        return self.claimed_at is not None

    @property
    def is_valid(self):
        return not self.is_expired and not self.is_claimed
