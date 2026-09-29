import logging
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.templatetags.static import static
from django.utils import timezone
from django.utils.text import slugify

from .limits import (
    MAX_PRICE_NOTE_LENGTH,
    MAX_SLUG_LENGTH,
    MAX_SOURCE_URL_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_VENUE_LENGTH,
)
from .validators import validate_url_scheme

logger = logging.getLogger(__name__)

# Field length constraints are defined in events.limits (Django-free, so
# scrapers can use them standalone); need to makemigrations if they change.

# Default images shown when an event has no scraped/uploaded image of its own.
# Keyed by Event.external_source; static paths under static/images/defaults/.
# Sources without an entry and user-created events (blank external_source)
# fall back to DEFAULT_EVENT_IMAGE.
DEFAULT_PUBLISHER_IMAGES = {
    "dansehallerne": "images/defaults/dansehallerne.webp",
    "hautscene": "images/defaults/hautscene.webp",
    "kbhdanser": "images/defaults/kbhdanser.webp",
    "sort-hvid": "images/defaults/sort-hvid.webp",
    "sydhavnteater": "images/defaults/sydhavnteater.webp",
    "toastercph": "images/defaults/toastercph.webp",
    "warehouse9": "images/defaults/warehouse9.webp",
}
DEFAULT_EVENT_IMAGE = "images/logo.png"
# List-card sizes of the defaults above (see events.images.make_thumbnail),
# at the same path under a thumbs/ directory. Regenerate them when a default
# image changes; test_static_manifest checks they exist.
DEFAULT_THUMBNAIL_DIR = "thumbs"


def default_thumbnail_path(path: str) -> str:
    """Static path of the list-card thumbnail of default image *path*."""
    directory, _, filename = path.rpartition("/")
    return f"{directory}/{DEFAULT_THUMBNAIL_DIR}/{filename}"


def _ended_before(now, days) -> models.Q:
    """Events that ended more than *days* before *now*.

    An event with no end time counts as ending when it starts, so a
    long-running event is never treated as over while it is still on.
    """
    cutoff = now - timezone.timedelta(days=days)
    return models.Q(end_datetime__lt=cutoff) | models.Q(
        end_datetime__isnull=True, start_datetime__lt=cutoff
    )


_SCRAPED = ~models.Q(external_source="")


def expired_events_q(now=None) -> models.Q:
    """Scraped events past SCRAPED_EVENT_RETENTION_DAYS, due for deletion.

    Only scraped events (non-blank external_source) ever expire;
    user-published events are never deleted.
    """
    now = now or timezone.now()
    return _SCRAPED & _ended_before(now, settings.SCRAPED_EVENT_RETENTION_DAYS)


def hidden_events_q(now=None) -> models.Q:
    """Past events too old to show in the event list.

    Expired scraped events (hidden before the daily purge gets to them) and
    user-published events that ended more than USER_EVENT_HIDE_AFTER_DAYS ago.
    """
    now = now or timezone.now()
    return expired_events_q(now) | (
        ~_SCRAPED & _ended_before(now, settings.USER_EVENT_HIDE_AFTER_DAYS)
    )


class EventCategory(models.TextChoices):
    PERFORMANCE = "performance", "Performance"
    WORKSHARING = "worksharing", "Worksharing"
    WORKSHOP = "workshop", "Workshop"
    OPENPRACTICE = "openpractice", "Open Practice"
    TALK = "talk", "Talk"
    SOCIAL = "social", "Social"
    OTHER = "other", "Other"


class DescriptionLanguage(models.TextChoices):
    DANISH = "da", "Danish"
    ENGLISH = "en", "English"
    MIXED = "mixed", "Danish and English"


class EventSeries(models.Model):
    """A recurring event: its occurrences are ordinary Event rows linking here.

    Stores what repeats (`rrule`, an RFC 5545 RRULE without COUNT/UNTIL, as
    written by events.recurrence.Pattern) and from when (`dtstart`, which
    fixes the phase of e.g. "every 2 weeks"). Where it ends isn't stored: the
    series ends at its last occurrence, so the owner can extend or shorten it
    (events/series.py). Deleted with its last occurrence (events/signals.py).
    """

    objects = models.Manager()
    DoesNotExist: type[ObjectDoesNotExist]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rrule = models.CharField(max_length=200)
    dtstart = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "event series"

    def __str__(self):
        return f"{self.rrule} from {self.dtstart:%Y-%m-%d}"

    @property
    def pattern(self):
        from .recurrence import Pattern

        return Pattern.from_rrule(str(self.rrule))


class Event(models.Model):
    objects = models.Manager()
    DoesNotExist: type[ObjectDoesNotExist]
    series_id: uuid.UUID | None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=MAX_SLUG_LENGTH, unique=True, editable=False)
    title = models.CharField(max_length=MAX_TITLE_LENGTH)
    description = models.TextField(blank=True, max_length=4000)
    image = models.ImageField(
        upload_to="events/",
        blank=True,
        null=True,
    )
    # List-card rendition of `image`, kept in sync by save() (see
    # _sync_thumbnail); content-addressed, so events sharing an image share it.
    thumbnail = models.ImageField(
        upload_to="events/thumbs/",
        blank=True,
        null=True,
        editable=False,
    )
    # Scraped events only: the source URL `image` was downloaded from, so the
    # importer can tell when the venue swaps the image (e.g. replaces an
    # "image coming soon" placeholder) and re-download it.
    image_source_url = models.URLField(max_length=2000, blank=True, editable=False)
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
    # Set on the occurrences of a recurring event (see EventSeries).
    series = models.ForeignKey(
        EventSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="occurrences",
        editable=False,
    )
    # Language processing of scraped descriptions (events/translation.py).
    # `description` always keeps the scraped original; these fields hold the
    # per-language versions derived from it, so a bilingual site can later
    # serve either language via description_for().
    description_language = models.CharField(
        max_length=5,
        choices=DescriptionLanguage.choices,
        blank=True,
        help_text="Language of the original description; blank = not processed.",
    )
    description_da = models.TextField(
        blank=True,
        help_text="Danish part of a mixed-language description.",
    )
    description_en = models.TextField(
        blank=True,
        help_text=(
            "English version: machine translation of a Danish description, "
            "or the English part of a mixed-language one."
        ),
    )
    description_en_is_machine = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime", "id"]
        constraints = [
            # Dedupes the same event arriving twice (two scrapers, or a
            # scraper and a manual submission). The venue is part of the key
            # so that generic titles ("Open Practice") at the same time in
            # different venues don't collide.
            models.UniqueConstraint(
                fields=["title", "start_datetime", "venue_name"],
                name="unique_event_title_start_datetime_venue",
            )
        ]
        indexes = [
            # Every public listing query filters is_draft + start_datetime and
            # sorts by start_datetime (event list, map, feeds).
            models.Index(fields=["is_draft", "start_datetime"]),
        ]

    # Storage name of `image` as last loaded from / saved to the database, so
    # save() can tell when it changed. None when unknown (image deferred).
    _saved_image_name: str | None = None

    def __str__(self):
        return self.title

    @classmethod
    def from_db(cls, db, field_names, values, *, fetch_mode=None):
        instance = super().from_db(db, field_names, values, fetch_mode=fetch_mode)
        if "image" in field_names:
            instance._saved_image_name = instance.image.name or ""
        return instance

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("event_detail", kwargs={"slug": self.slug})

    def _generate_unique_slug(self):
        """Generate a unique slug from the title, appending a suffix on collision."""
        # Reserve room for "-<4 hex chars>" so a colliding slug never exceeds
        # the slug column's max_length.
        suffix_room = 5
        base_slug = slugify(self.title)[: MAX_SLUG_LENGTH - suffix_room]
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

    @property
    def local_start_date(self):
        """start_datetime's date in the local timezone (for day grouping)."""
        return timezone.localtime(self.start_datetime).date()

    @property
    def display_image_url(self) -> str:
        """URL of the event image, with per-publisher / logo fallbacks.

        Returns the event's own image when set, otherwise the publisher
        default for its external_source, otherwise the pleskal logo.
        """
        if self.image:
            return self.image.url  # ty: ignore[unresolved-attribute]
        return static(self._default_image_path())

    @property
    def display_thumbnail_url(self) -> str:
        """Small rendition of display_image_url for the event list cards.

        Falls back to the full image while its thumbnail hasn't been
        generated yet (see the backfill_thumbnails command).
        """
        if self.thumbnail:
            return self.thumbnail.url  # ty: ignore[unresolved-attribute]
        if self.image:
            return self.image.url  # ty: ignore[unresolved-attribute]
        return static(default_thumbnail_path(self._default_image_path()))

    def _default_image_path(self) -> str:
        source = str(self.external_source)
        return DEFAULT_PUBLISHER_IMAGES.get(source, DEFAULT_EVENT_IMAGE)

    def _build_geocode_query(self) -> str:
        """Build the Nominatim query string for this event's venue.

        venue_address/venue_name are expected to be a bare street (no city or
        country); those are appended here. If a scraper's address already
        includes them, appending again would duplicate tokens and confuse
        Nominatim, so skip it in that case.
        """
        base = str(self.venue_address or self.venue_name)
        if "denmark" in base.lower():
            return base
        return f"{base}, Copenhagen, Denmark"

    def description_for(self, lang: str) -> str:
        """Return the description in *lang* ("en" or "da"), as best available.

        Falls back to the original when there's no version in that language
        (an English-only event has no Danish text, and a Danish one whose
        translation failed or hasn't run yet has no English).
        """
        language = self.description_language
        if lang == DescriptionLanguage.ENGLISH and language in (
            DescriptionLanguage.DANISH,
            DescriptionLanguage.MIXED,
        ):
            return str(self.description_en or self.description)
        if lang == DescriptionLanguage.DANISH and language == DescriptionLanguage.MIXED:
            return str(self.description_da or self.description)
        return str(self.description)

    @property
    def is_machine_translated(self) -> bool:
        """True when the English description shown is a machine translation."""
        return (
            self.description_language == DescriptionLanguage.DANISH
            and bool(self.description_en_is_machine)
            and bool(self.description_en)
        )

    def get_display_description(self):
        """Return the English description with scraped event disclaimer prepended."""
        from django.conf import settings

        description = self.description_for(DescriptionLanguage.ENGLISH)
        if not self.external_source or not settings.SCRAPED_EVENT_DISCLAIMER:
            return description
        disclaimer = settings.SCRAPED_EVENT_DISCLAIMER
        if description:
            return f"{disclaimer}\n\n{description}"
        return disclaimer

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        self._maybe_geocode_venue()
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "image" in update_fields:
            thumbnail_changed = self._sync_thumbnail()
            if thumbnail_changed and update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "thumbnail"}
        super().save(*args, **kwargs)
        self._saved_image_name = self.image.name or ""

    def _sync_thumbnail(self) -> bool:
        """Point `thumbnail` at a rendition of the current `image`.

        Regenerates when the image changed, or is set without a thumbnail
        (e.g. an earlier attempt failed); clears it when the image is removed.
        Failures are logged and leave the thumbnail empty, so the list falls
        back to the full image — they never block saving the event. Returns
        True when `thumbnail` was changed.
        """
        image = self.image
        if image and not image._committed:  # ty: ignore[unresolved-attribute]
            # An upload assigned directly (e.g. through the admin) is only
            # written to storage by Model.save(); write it now so it can be
            # read back for the thumbnail. This is what FileField.pre_save
            # would do.
            image.save(image.name, image.file, save=False)  # ty: ignore[unresolved-attribute]
        image_name = self.image.name or ""
        changed = self._state.adding or (
            self._saved_image_name is not None and image_name != self._saved_image_name
        )
        if not changed and bool(self.thumbnail) == bool(image_name):
            return False
        self.thumbnail = thumbnail_for_image(self.image) if image_name else None  # ty: ignore[invalid-assignment]
        return True

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

        if not self._state.adding:
            self.latitude = self.longitude = None  # ty: ignore[invalid-assignment]

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

        self.latitude, self.longitude = result  # ty: ignore[invalid-assignment]


def thumbnail_for_image(image_file) -> str | None:
    """Storage name of the thumbnail for the stored *image_file*, or None.

    Reuses the thumbnail of another event with the same image (the importer
    shares one image file across a production's performances); otherwise
    generates one. Failures are logged and return None.
    """
    existing = (
        Event.objects.filter(image=image_file.name)
        .exclude(thumbnail="")
        .exclude(thumbnail__isnull=True)
        .values_list("thumbnail", flat=True)
        .first()
    )
    if existing:
        return existing
    from .images import store_thumbnail

    try:
        return store_thumbnail(image_file)
    except Exception:
        logger.warning(
            "Could not generate a thumbnail for %s", image_file.name, exc_info=True
        )
        return None


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
