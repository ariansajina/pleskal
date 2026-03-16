import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_approved = models.BooleanField(default=False)
    is_moderator = models.BooleanField(default=False)
    display_name = models.CharField(blank=True, max_length=100)
    bio = models.TextField(blank=True, max_length=500)
    website = models.URLField(blank=True)
    intro_message = models.TextField(blank=True, max_length=500)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.username

    @property
    def public_name(self):
        return self.display_name if self.display_name else self.username
