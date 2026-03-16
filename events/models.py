import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .validators import validate_image_file, validate_url_scheme


class EventCategory(models.TextChoices):
    PERFORMANCE = "performance", "Performance"
    TALK = "talk", "Talk"
    WORKSHOP = "workshop", "Workshop"
    OPEN_PRACTICE = "open_practice", "Open Practice"
    SOCIAL = "social", "Social"
    OTHER = "other", "Other"


class Event(models.Model):
    objects = models.Manager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=250, unique=True, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="events/images/",
        blank=True,
        validators=[validate_image_file],
    )
    image_thumbnail = models.ImageField(
        upload_to="events/thumbnails/",
        blank=True,
        editable=False,
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(blank=True, null=True)
    venue_name = models.CharField(max_length=200)
    venue_address = models.CharField(max_length=200, blank=True)
    category = models.CharField(
        max_length=20,
        choices=EventCategory.choices,
        default=EventCategory.OTHER,
    )
    is_free = models.BooleanField(default=False)
    is_wheelchair_accessible = models.BooleanField(default=False)
    price_note = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(
        blank=True,
        validators=[validate_url_scheme],
    )
    external_source = models.CharField(max_length=100, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return self.title

    def _generate_unique_slug(self):
        """Generate a unique slug from the title, appending a suffix on collision."""
        base_slug = slugify(self.title)[:200]
        if not base_slug:
            base_slug = "event"
        slug = base_slug
        while Event.objects.filter(slug=slug).exists():
            suffix = secrets.token_hex(2)
            slug = f"{base_slug}-{suffix}"
        return slug

    def clean(self):
        errors = {}

        # Title length
        if self.title and len(str(self.title)) < 3:
            errors["title"] = "Title must be at least 3 characters."

        # Start datetime must be in the future (only on creation)
        if self._state.adding and self.start_datetime:
            if self.start_datetime <= timezone.now():
                errors["start_datetime"] = "Start date and time must be in the future."
            # Must not be more than 1 year in the future
            one_year = timezone.now() + timezone.timedelta(days=365)
            if self.start_datetime > one_year:
                errors["start_datetime"] = (
                    "Start date must not be more than 1 year in the future."
                )

        # End datetime must be after start datetime
        if (
            self.end_datetime
            and self.start_datetime
            and self.end_datetime <= self.start_datetime
        ):
            errors["end_datetime"] = (
                "End date and time must be after start date and time."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)
