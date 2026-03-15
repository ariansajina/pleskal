import secrets
import uuid
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .validators import validate_image_file, validate_url_scheme

if TYPE_CHECKING:
    from accounts.models import User


class EventCategory(models.TextChoices):
    PERFORMANCE = "performance", "Performance"
    WORKSHOP = "workshop", "Workshop"
    WORK_IN_PROGRESS = "work_in_progress", "Work in Progress"
    OPEN_PRACTICE = "open_practice", "Open Practice"
    SOCIAL = "social", "Social"
    OTHER = "other", "Other"


class EventStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


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
    submitted_by_id: (
        uuid.UUID | None
    )  # Django adds this attribute for ForeignKey fields
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.PENDING,
    )
    rejection_note = models.TextField(blank=True)
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

    def approve(self):
        """Approve the event and auto-approve the submitting user."""
        self.status = EventStatus.APPROVED
        self.rejection_note = ""
        self.save(update_fields=["status", "rejection_note", "updated_at"])
        user = cast("User | None", self.submitted_by)
        if user and not user.is_approved:
            user.is_approved = True
            user.save(update_fields=["is_approved"])

    def reject(self, note):
        """Reject the event with a required note."""
        if not note or not note.strip():
            raise ValueError("Rejection note is required.")
        self.status = EventStatus.REJECTED
        self.rejection_note = note.strip()
        self.save(update_fields=["status", "rejection_note", "updated_at"])

    def resubmit(self):
        """Resubmit a rejected event for moderation."""
        if self.status != EventStatus.REJECTED:
            raise ValueError("Only rejected events can be resubmitted.")
        self.status = EventStatus.PENDING
        self.rejection_note = ""
        self.save(update_fields=["status", "rejection_note", "updated_at"])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        # Auto-approve on creation if user is approved
        if self._state.adding and self.submitted_by_id:
            # Need to check is_approved; use cached submitted_by if loaded
            try:
                user = cast("User | None", self.submitted_by)
            except Exception:
                user = None
            if user and user.is_approved:
                self.status = EventStatus.APPROVED
        super().save(*args, **kwargs)
