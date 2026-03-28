import datetime

from django import forms
from django.conf import settings
from django.utils import timezone
from markdownx.widgets import MarkdownxWidget

from .models import Event

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


class EventForm(forms.ModelForm):
    """Form for creating and editing events."""

    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-input"},
            format=DATE_FORMAT,
        ),
        input_formats=[DATE_FORMAT],
    )
    start_time = forms.TimeField(
        label="Start time",
        widget=forms.TimeInput(
            attrs={"type": "time", "class": "form-input", "lang": "en"},
            format=TIME_FORMAT,
        ),
        input_formats=[TIME_FORMAT],
    )
    end_time = forms.TimeField(
        label="End time",
        widget=forms.TimeInput(
            attrs={"type": "time", "class": "form-input", "lang": "en"},
            format=TIME_FORMAT,
        ),
        input_formats=[TIME_FORMAT],
        required=False,
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "description",
            "image",
            "venue_name",
            "venue_address",
            "category",
            "is_free",
            "is_wheelchair_accessible",
            "price_note",
            "source_url",
        ]
        widgets = {
            "description": MarkdownxWidget(attrs={"rows": 8, "maxlength": 1500}),
        }

    def __init__(self, *args, creation=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_creation = creation
        # Pre-populate date/time fields from existing instance when editing
        if self.instance and self.instance.pk and self.instance.start_datetime:
            local_start = timezone.localtime(self.instance.start_datetime)
            self.initial["date"] = local_start.date()
            self.initial["start_time"] = local_start.strftime(TIME_FORMAT)
            if self.instance.end_datetime:
                local_end = timezone.localtime(self.instance.end_datetime)
                self.initial["end_time"] = local_end.strftime(TIME_FORMAT)
        elif creation:
            # Default to today and next full hour for new events
            now = timezone.localtime(timezone.now())
            self.initial["date"] = now.date()
            next_hour = now.replace(
                minute=0, second=0, microsecond=0
            ) + datetime.timedelta(hours=1)
            self.initial["start_time"] = next_hour.strftime(TIME_FORMAT)
        # Apply CSS classes to text fields
        for fname in [
            "title",
            "venue_name",
            "venue_address",
            "price_note",
            "source_url",
        ]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.setdefault("class", "form-input")
        if "category" in self.fields:
            self.fields["category"].widget.attrs.setdefault("class", "form-select")
        self.fields["image"].required = False
        self.fields["description"].required = False
        self.fields["venue_address"].required = False
        self.fields["price_note"].required = False
        self.fields["source_url"].required = False

    def clean_description(self):
        description = self.cleaned_data.get("description", "")
        if len(description) > 1500:
            raise forms.ValidationError(
                f"Description must be 1500 characters or fewer (currently {len(description)})."
            )
        return description

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if (
            image
            and hasattr(image, "size")
            and image.size > settings.MAX_IMAGE_SIZE_BYTES
        ):
            raise forms.ValidationError("Image must be under 10 MB.")
        return image

    def _validate_start_for_creation(self, start_dt):
        if start_dt <= timezone.now():
            self.add_error(
                "date",
                "Events cannot be created in the past. "
                "Please choose a future date and time.",
            )
        one_year = timezone.now() + timezone.timedelta(days=365)
        if start_dt > one_year:
            self.add_error(
                "date",
                "Start date must not be more than 1 year in the future.",
            )

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")

        if date and start_time:
            start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
            if self._is_creation:
                self._validate_start_for_creation(start_dt)
            cleaned["start_datetime"] = start_dt
            cleaned["end_datetime"] = None
            if end_time:
                end_dt = timezone.make_aware(datetime.datetime.combine(date, end_time))
                if end_dt <= start_dt:
                    self.add_error("end_time", "End time must be after start time.")
                else:
                    cleaned["end_datetime"] = end_dt

            title = cleaned.get("title")
            if title:
                qs = Event.objects.filter(title=title, start_datetime=start_dt)
                if self.instance and self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise forms.ValidationError(
                        "An event with this title already exists at the same date and time."
                    )

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.start_datetime = self.cleaned_data["start_datetime"]
        instance.end_datetime = self.cleaned_data.get("end_datetime")
        if commit:
            instance.save()
        return instance
