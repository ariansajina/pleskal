from django import forms
from django.utils import timezone
from markdownx.widgets import MarkdownxWidget

from .models import Event

DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class EventForm(forms.ModelForm):
    """Form for creating and editing events."""

    class Meta:
        model = Event
        fields = [
            "title",
            "description",
            "image",
            "start_datetime",
            "end_datetime",
            "venue_name",
            "venue_address",
            "category",
            "is_free",
            "is_wheelchair_accessible",
            "price_note",
            "source_url",
        ]
        widgets = {
            "start_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-input"},
                format=DATETIME_LOCAL_FORMAT,
            ),
            "end_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-input"},
                format=DATETIME_LOCAL_FORMAT,
            ),
            "description": MarkdownxWidget(attrs={"rows": 8}),
        }

    def __init__(self, *args, creation=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_creation = creation
        # Apply new style CSS classes to remaining fields
        _text_fields = [
            "title",
            "venue_name",
            "venue_address",
            "price_note",
            "source_url",
        ]
        for fname in _text_fields:
            if fname in self.fields:
                self.fields[fname].widget.attrs.setdefault("class", "form-input")
        if "category" in self.fields:
            self.fields["category"].widget.attrs.setdefault("class", "form-select")
        # Make datetime fields input_formats aware of the local format
        self.fields["start_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]
        self.fields["end_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]
        self.fields["end_datetime"].required = False
        self.fields["image"].required = False
        self.fields["description"].required = False
        self.fields["venue_address"].required = False
        self.fields["price_note"].required = False
        self.fields["source_url"].required = False

    def clean_start_datetime(self):
        dt = self.cleaned_data.get("start_datetime")
        if dt and self._is_creation:
            if dt <= timezone.now():
                raise forms.ValidationError(
                    "Events cannot be created in the past. "
                    "Please choose a future start date and time."
                )
            one_year = timezone.now() + timezone.timedelta(days=365)
            if dt > one_year:
                raise forms.ValidationError(
                    "Start date must not be more than 1 year in the future."
                )
        return dt

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_datetime")
        end = cleaned.get("end_datetime")
        if start and end and end <= start:
            self.add_error(
                "end_datetime",
                "End date and time must be after start date and time.",
            )
        return cleaned
