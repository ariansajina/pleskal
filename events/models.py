import logging
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .validators import validate_url_scheme

logger = logging.getLogger(__name__)

# Field length constraints; need to makemigrations if this is updated
MAX_TITLE_LENGTH = 250
MAX_VENUE_LENGTH = 200
MAX_PRICE_NOTE_LENGTH = 200
MAX_SOURCE_URL_LENGTH = 200


class EventCategory(models.TextChoices):
    PERFORMANCE = "performance", "Performance"
    WORKSHARING = "worksharing", "Worksharing"
    WORKSHOP = "workshop", "Workshop"
    OPENPRACTICE = "openpractice", "Open Practice"
    TALK = "talk", "Talk"
    SOCIAL = "social", "Social"
    OTHER = "other", "Other"


class Event(models.Model):
    objects = models.Manager()
    DoesNotExist: type[ObjectDoesNotExist]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=250, unique=True, editable=False)
    title = models.CharField(max_length=MAX_TITLE_LENGTH)
    description = models.TextField(blank=True, max_length=4000)
    image = models.ImageField(
        upload_to="events/",
        blank=True,
        null=True,
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(blank=True, null=True)
    venue_name = models.CharField(max_length=MAX_VENUE_LENGTH)
    venue_address = models.CharField(max_length=MAX_VENUE_LENGTH, blank=True)
    category = models.CharField(
        max_length=20,
        choices=EventCategory.choices,
        default=EventCategory.OTHER,
    )
    is_free = models.BooleanField(default=False)
    is_wheelchair_accessible = models.BooleanField(default=False)
    price_note = models.CharField(max_length=MAX_PRICE_NOTE_LENGTH, blank=True)
    source_url = models.URLField(
        max_length=MAX_SOURCE_URL_LENGTH,
        blank=True,
        validators=[validate_url_scheme],
    )
    external_source = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    is_draft = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "start_datetime"],
                name="unique_event_title_start_datetime",
            )
        ]

    def __str__(self):
        return self.title

    def _generate_unique_slug(self):
        """Generate a unique slug from the title, appending a suffix on collision."""
        base_slug = slugify(self.title)[:MAX_TITLE_LENGTH]
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

    @property
    def has_map_location(self) -> bool:
        """True when the venue has been successfully geocoded to lat/lon."""
        return self.latitude is not None and self.longitude is not None

    def _build_geocode_query(self) -> str:
        """Build the Nominatim query string for this event's venue."""
        if self.venue_address:
            return f"{self.venue_name}, {self.venue_address}, Copenhagen, Denmark"
        return f"{self.venue_name}, Copenhagen, Denmark"

    def get_display_description(self):
        """Return description with scraped event disclaimer prepended."""
        from django.conf import settings

        if not self.external_source or not settings.SCRAPED_EVENT_DISCLAIMER:
            return self.description
        disclaimer = settings.SCRAPED_EVENT_DISCLAIMER
        if self.description:
            return f"{disclaimer}\n\n{self.description}"
        return disclaimer

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        self._maybe_geocode_venue()
        super().save(*args, **kwargs)

    def _maybe_geocode_venue(self) -> None:
        """Populate latitude/longitude from Nominatim when the address changes.

        Runs on insert, or on update when venue_name/venue_address changed since
        the row was last saved. Failures are swallowed — geocoding must never
        block saving an event.
        """
        if not getattr(settings, "GEOCODING_ENABLED", True):
            return
        if not self.venue_name:
            return

        needs_geocode = self._state.adding
        if not needs_geocode:
            try:
                previous = Event.objects.only("venue_name", "venue_address").get(
                    pk=self.pk
                )
            except Event.DoesNotExist:
                needs_geocode = True
            else:
                needs_geocode = (
                    previous.venue_name != self.venue_name
                    or previous.venue_address != self.venue_address
                )

        if not needs_geocode:
            return

        from .geocoding import geocode

        try:
            result = geocode(self._build_geocode_query())
        except Exception:  # pragma: no cover - defensive; geocode already swallows
            logger.warning("Geocoding raised for event %s", self.pk, exc_info=True)
            return

        if result is None:
            logger.info(
                "Geocoding returned no result for event %s (%s)",
                self.pk,
                self.venue_name,
            )
            return

        self.latitude, self.longitude = result


class FeedHit(models.Model):
    """Daily hit counter for each feed type, used by the weekly digest."""

    ICAL = "ical"
    RSS = "rss"
    FEED_CHOICES = [(ICAL, "iCal"), (RSS, "RSS")]

    objects = models.Manager()

    feed_type = models.CharField(max_length=10, choices=FEED_CHOICES)
    date = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("feed_type", "date")]

    def __str__(self):
        return f"{self.feed_type} {self.date}: {self.count}"

    @classmethod
    def record(cls, feed_type: str) -> None:
        """Atomically increment the hit counter for today."""
        from django.db.models import F
        from django.utils import timezone

        cls.objects.update_or_create(
            feed_type=feed_type,
            date=timezone.localdate(),
            create_defaults={"count": 1},
            defaults={"count": F("count") + 1},
        )
