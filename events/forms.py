import datetime

from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.dateformat import format as date_format
from markdownx.widgets import MarkdownxWidget

from . import recurrence
from .models import Event
from .recurrence import (
    EVENT_HORIZON,
    MAX_INTERVAL,
    ORDINALS,
    WEEKDAY_NAMES,
    Ends,
    Freq,
    Pattern,
    nth_weekday_of,
)
from .series import (
    SCOPE_CHOICES,
    Scope,
    check_conflicts,
    plan_creation,
    plan_dates,
)

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"

REPEAT_CUSTOM = "custom"
REPEAT_DATES = "dates"
DATES_PREFIX = "dates"
UNIT_DAY, UNIT_WEEK, UNIT_MONTH = "day", "week", "month"
UNIT_FREQ = {UNIT_DAY: Freq.DAILY, UNIT_WEEK: Freq.WEEKLY, UNIT_MONTH: Freq.MONTHLY}
MONTHLY_DAY, MONTHLY_NTH, MONTHLY_LAST = "day", "nth", "last"
ENDS_NEVER, ENDS_ON, ENDS_AFTER = "never", "on", "after"
MAX_REPEAT_COUNT = 999
# Form fields that only matter for a repeating event.
RECURRENCE_FIELDS = (
    "repeat",
    "repeat_interval",
    "repeat_unit",
    "repeat_weekdays",
    "repeat_monthly",
    "repeat_ends",
    "repeat_until",
    "repeat_count",
)


class _OptionalChoicesMixin:
    """Renders the choices in `unavailable` hidden and disabled; the event
    form's script re-enables them when the date changes."""

    unavailable: frozenset = frozenset()

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)  # ty: ignore[unresolved-attribute]
        if str(value) in self.unavailable:
            option["attrs"]["disabled"] = True
            option["attrs"]["hidden"] = True
        return option


class RepeatSelect(_OptionalChoicesMixin, forms.Select):
    pass


class MonthlyRadioSelect(_OptionalChoicesMixin, forms.RadioSelect):
    pass


def _unavailable_presets(day: datetime.date) -> frozenset:
    presets = recurrence.preset_patterns(day)
    return frozenset(
        key
        for key in (recurrence.PRESET_MONTHLY_NTH, recurrence.PRESET_MONTHLY_LAST)
        if key not in presets
    )


def _repeat_choices(day: datetime.date) -> list[tuple[str, str]]:
    """The "Repeat" options, labelled for start date *day*.

    static/js/event-form.js relabels them when the date changes, and hides
    the monthly ones that don't apply to it.
    """
    weekday = WEEKDAY_NAMES[day.weekday()]
    return [
        ("", "Does not repeat"),
        (recurrence.PRESET_DAILY, "Daily"),
        (recurrence.PRESET_WEEKDAYS, "Every weekday (Monday to Friday)"),
        (recurrence.PRESET_WEEKLY, f"Weekly on {weekday}"),
        (recurrence.PRESET_MONTHLY_DAY, f"Monthly on day {day.day}"),
        (
            recurrence.PRESET_MONTHLY_NTH,
            f"Monthly on the {ORDINALS.get(nth_weekday_of(day), '')} {weekday}",
        ),
        (recurrence.PRESET_MONTHLY_LAST, f"Monthly on the last {weekday}"),
        (REPEAT_CUSTOM, "Custom…"),
        (REPEAT_DATES, "On specific dates…"),
    ]


def _monthly_choices(day: datetime.date) -> list[tuple[str, str]]:
    weekday = WEEKDAY_NAMES[day.weekday()]
    return [
        (MONTHLY_DAY, f"On day {day.day}"),
        (MONTHLY_NTH, f"On the {ORDINALS[nth_weekday_of(day)]} {weekday}"),
        (MONTHLY_LAST, f"On the last {weekday}"),
    ]


def _date_row(event: Event) -> dict:
    """Initial values of a specific-dates row for *event*."""
    start = timezone.localtime(event.start_datetime)
    row = {"date": start.date(), "start_time": start.strftime(TIME_FORMAT)}
    if event.end_datetime:
        row["end_time"] = timezone.localtime(event.end_datetime).strftime(TIME_FORMAT)
    return row


class ExtraDateForm(forms.Form):
    """One more date of an event listed "on specific dates", each with its
    own times. A blank row is ignored (clearing a row removes its date); an
    end time before the start time ends the next day (a night out)."""

    date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-input", "aria-label": "Date"},
            format=DATE_FORMAT,
        ),
        input_formats=[DATE_FORMAT],
    )
    start_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(
            attrs={
                "type": "time",
                "class": "form-input",
                "lang": "en",
                "aria-label": "Start time",
            },
            format=TIME_FORMAT,
        ),
        input_formats=[TIME_FORMAT],
    )
    end_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(
            attrs={
                "type": "time",
                "class": "form-input",
                "lang": "en",
                "aria-label": "End time",
            },
            format=TIME_FORMAT,
        ),
        input_formats=[TIME_FORMAT],
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def clean(self):
        cleaned = super().clean()
        day, start_time = cleaned.get("date"), cleaned.get("start_time")
        cleaned["span"] = None
        if self.errors or (day is None and start_time is None):
            return cleaned
        if day is None:
            raise forms.ValidationError("Enter the date.")
        if start_time is None:
            raise forms.ValidationError("Enter the start time.")
        start = datetime.datetime.combine(day, start_time)
        end = None
        if end_time := cleaned.get("end_time"):
            end = datetime.datetime.combine(day, end_time)
            if end == start:
                raise forms.ValidationError("The end time must differ from the start.")
            if end < start:
                end += datetime.timedelta(days=1)
        start_dt = timezone.make_aware(start)
        if start_dt <= timezone.now():
            raise forms.ValidationError("This date is in the past.")
        unlimited = self._user is not None and self._user.is_system_account
        if start_dt > timezone.now() + EVENT_HORIZON and not unlimited:
            raise forms.ValidationError("Dates can be at most one year ahead.")
        cleaned["span"] = (start_dt, timezone.make_aware(end) if end else None)
        return cleaned


ExtraDateFormSet = forms.formset_factory(ExtraDateForm, extra=2)


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
    end_date = forms.DateField(
        label="End date",
        help_text="For an event that runs without a break into a later day.",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-input"},
            format=DATE_FORMAT,
        ),
        input_formats=[DATE_FORMAT],
        required=False,
    )
    # Repeat (see events.recurrence). The labels of `repeat` and
    # `repeat_monthly` depend on the date and are set in __init__.
    repeat = forms.ChoiceField(
        label="Repeat",
        required=False,
        choices=[],
        widget=RepeatSelect(attrs={"class": "form-select"}),
    )
    repeat_interval = forms.IntegerField(
        label="Repeat every",
        required=False,
        min_value=1,
        max_value=MAX_INTERVAL,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-input", "style": "width:5rem"}),
    )
    repeat_unit = forms.ChoiceField(
        label="Unit",
        required=False,
        initial=UNIT_WEEK,
        choices=[(UNIT_DAY, "days"), (UNIT_WEEK, "weeks"), (UNIT_MONTH, "months")],
        widget=forms.Select(attrs={"class": "form-select", "style": "width:auto"}),
    )
    repeat_weekdays = forms.TypedMultipleChoiceField(
        label="On",
        required=False,
        coerce=int,
        choices=[(i, name[:3]) for i, name in enumerate(WEEKDAY_NAMES)],
        widget=forms.CheckboxSelectMultiple,
    )
    repeat_monthly = forms.ChoiceField(
        label="On",
        required=False,
        initial=MONTHLY_DAY,
        choices=[],
        widget=MonthlyRadioSelect,
    )
    repeat_ends = forms.ChoiceField(
        label="Ends",
        required=False,
        initial=ENDS_NEVER,
        choices=[
            (ENDS_NEVER, "Never (as far as allowed)"),
            (ENDS_ON, "Until"),
            (ENDS_AFTER, "After a number of dates"),
        ],
        widget=forms.RadioSelect,
    )
    repeat_until = forms.DateField(
        label="Repeat until",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-input",
                "aria-label": "Repeat until",
            },
            format=DATE_FORMAT,
        ),
        input_formats=[DATE_FORMAT],
    )
    repeat_count = forms.IntegerField(
        label="Number of dates",
        required=False,
        min_value=1,
        max_value=MAX_REPEAT_COUNT,
        widget=forms.NumberInput(
            attrs={
                "class": "form-input",
                "style": "width:6rem",
                "aria-label": "Number of dates",
            }
        ),
    )
    # Editing an occurrence of a repeating event: which occurrences to change.
    scope = forms.ChoiceField(
        label="Apply changes to",
        required=False,
        initial=Scope.THIS,
        choices=SCOPE_CHOICES,
        widget=forms.RadioSelect,
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
            "description": MarkdownxWidget(attrs={"rows": 8, "maxlength": 4000}),
        }

    def __init__(self, *args, creation=True, user=None, scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_creation = creation
        self._user = user
        self.max_occurrences = settings.MAX_UPCOMING_OCCURRENCES_PER_SERIES
        # Pre-populate date/time fields from existing instance when editing
        if self.instance and self.instance.pk and self.instance.start_datetime:
            local_start = timezone.localtime(self.instance.start_datetime)
            self.initial["date"] = local_start.date()
            self.initial["start_time"] = local_start.strftime(TIME_FORMAT)
            if self.instance.end_datetime:
                local_end = timezone.localtime(self.instance.end_datetime)
                self.initial["end_time"] = local_end.strftime(TIME_FORMAT)
                if local_end.date() != local_start.date():
                    self.initial["end_date"] = local_end.date()
        elif creation:
            # Default to today and next full hour for new events
            now = timezone.localtime(timezone.now())
            self.initial["date"] = now.date()
            next_hour = now.replace(
                minute=0, second=0, microsecond=0
            ) + datetime.timedelta(hours=1)
            self.initial["start_time"] = next_hour.strftime(TIME_FORMAT)
        self.series = None if creation else self.instance.series
        extra_dates = []
        if self.series is not None:
            extra_dates = self._init_series_fields(self.series, scope)
        self.extra_dates = ExtraDateFormSet(
            self.data if self.is_bound else None,
            prefix=DATES_PREFIX,
            initial=extra_dates,
            form_kwargs={"user": user},
        )
        if extra_dates:
            self.extra_dates.extra = 1
        label_day = self._label_date()
        self.fields["repeat"].choices = _repeat_choices(label_day)
        self.fields["repeat"].widget.unavailable = _unavailable_presets(label_day)
        self.fields["repeat_monthly"].choices = _monthly_choices(label_day)
        if not recurrence.is_last_weekday_of_month(label_day):
            self.fields["repeat_monthly"].widget.unavailable = frozenset({MONTHLY_LAST})
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
        self.fields["is_free"].widget.attrs.setdefault("data-free-toggle", "1")
        self.fields["image"].required = False
        self.fields["description"].required = False
        self.fields["venue_address"].required = False
        self.fields["price_note"].required = False
        self.fields["source_url"].required = False

    def _label_date(self) -> datetime.date:
        """The start date the repeat options are labelled for."""
        if self.is_bound:
            try:
                return datetime.datetime.strptime(
                    self.data.get("date", ""), DATE_FORMAT
                ).date()
            except ValueError:
                pass
        day = self.initial.get("date")
        return day if isinstance(day, datetime.date) else timezone.localdate()

    def _init_series_fields(self, series, scope) -> list[dict]:
        """Fill the repeat fields from the series of the event being edited,
        ending on its last date (so a later end date extends it).

        Returns the initial rows of the specific-dates list: the series'
        other upcoming dates. A series without a rule (dates listed one by
        one, or a scraped show) has only those, and no "this and following"
        scope: its edits apply to one date or to all of them.
        """
        pattern = series.pattern
        if pattern is None:
            self.fields["scope"].choices = [
                choice for choice in SCOPE_CHOICES if choice[0] != Scope.FOLLOWING
            ]
        if scope == Scope.ALL or (scope == Scope.FOLLOWING and pattern is not None):
            self.initial["scope"] = scope
        others = (
            Event.objects.filter(series=series, start_datetime__gte=timezone.now())
            .exclude(pk=self.instance.pk)
            .order_by("start_datetime")
        )
        extra_dates = [_date_row(other) for other in others]
        if pattern is None:
            self.initial["repeat"] = REPEAT_DATES
            return extra_dates
        day = self.initial["date"]
        presets = recurrence.preset_patterns(day)
        preset = next((key for key, p in presets.items() if p == pattern), None)
        self.initial["repeat"] = preset or REPEAT_CUSTOM
        self.initial["repeat_interval"] = pattern.interval
        self.initial["repeat_unit"] = {
            Freq.DAILY: UNIT_DAY,
            Freq.WEEKLY: UNIT_WEEK,
            Freq.MONTHLY: UNIT_MONTH,
        }[pattern.freq]
        self.initial["repeat_weekdays"] = list(pattern.weekdays)
        if pattern.month_day is not None:
            self.initial["repeat_monthly"] = MONTHLY_DAY
        elif pattern.nth == -1:
            self.initial["repeat_monthly"] = MONTHLY_LAST
        elif pattern.nth is not None:
            self.initial["repeat_monthly"] = MONTHLY_NTH
        last = Event.objects.filter(series=series).latest("start_datetime")
        self.initial["repeat_ends"] = ENDS_ON
        self.initial["repeat_until"] = timezone.localtime(last.start_datetime).date()
        return extra_dates

    @property
    def repeat_applies(self) -> bool:
        """Whether the repeat fields take effect: on creation, when editing a
        single event (it can become a series), or when editing a series with
        scope "this and following" / "all"."""
        if self._is_creation or self.series is None:
            return True
        return self.data.get("scope") in (Scope.FOLLOWING, Scope.ALL)

    def _clean_pattern(self, cleaned, day: datetime.date) -> Pattern | None:
        repeat = cleaned.get("repeat") or ""
        if not repeat:
            return None
        if repeat != REPEAT_CUSTOM:
            pattern = recurrence.preset_patterns(day).get(repeat)
            if pattern is None:
                self.add_error("repeat", "This option doesn't fit the chosen date.")
            return pattern
        interval = cleaned.get("repeat_interval") or 1
        unit = cleaned.get("repeat_unit") or UNIT_WEEK
        freq = UNIT_FREQ[unit]
        if freq == Freq.DAILY:
            return Pattern(freq, interval)
        if freq == Freq.WEEKLY:
            weekdays = sorted(set(cleaned.get("repeat_weekdays") or [day.weekday()]))
            return Pattern(freq, interval, weekdays=tuple(weekdays))
        monthly = cleaned.get("repeat_monthly") or MONTHLY_DAY
        if monthly == MONTHLY_DAY:
            return Pattern(freq, interval, month_day=day.day)
        if monthly == MONTHLY_LAST:
            if not recurrence.is_last_weekday_of_month(day):
                self.add_error(
                    "repeat_monthly",
                    "The chosen date isn't the last of its weekday in the month.",
                )
                return None
            return Pattern(freq, interval, nth=-1, nth_weekday=day.weekday())
        return Pattern(
            freq, interval, nth=nth_weekday_of(day), nth_weekday=day.weekday()
        )

    def _clean_ends(self, cleaned, day: datetime.date) -> Ends | None:
        kind = cleaned.get("repeat_ends") or ENDS_NEVER
        if kind == ENDS_ON:
            until = cleaned.get("repeat_until")
            if until is None:
                self.add_error("repeat_until", "Choose when the event stops repeating.")
                return None
            if until < day:
                self.add_error("repeat_until", "The end date must be after the start.")
                return None
            return Ends(until=until)
        if kind == ENDS_AFTER:
            count = cleaned.get("repeat_count")
            if count is None:
                self.add_error("repeat_count", "Enter how many dates to create.")
                return None
            return Ends(count=count)
        return Ends()

    @property
    def ends_changed(self) -> bool:
        """Whether the repeat end differs from the series' current last date."""
        changed = set(self.changed_data)
        if "repeat_ends" in changed:
            return True
        return (
            self.cleaned_data.get("repeat_ends") == ENDS_ON
            and "repeat_until" in changed
        )

    def clean_description(self):
        description = self.cleaned_data.get("description", "")
        if len(description) > 4000:
            raise forms.ValidationError(
                f"Description must be 4000 characters or fewer (currently {len(description)})."
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
        # Scraper (system) accounts list whatever their source publishes.
        unlimited = self._user is not None and self._user.is_system_account
        if start_dt > timezone.now() + EVENT_HORIZON and not unlimited:
            self.add_error(
                "date",
                "Start date must not be more than 1 year in the future.",
            )

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        end_date = cleaned.get("end_date") or date

        if date and start_time:
            start_dt = timezone.make_aware(datetime.datetime.combine(date, start_time))
            if self._is_creation:
                self._validate_start_for_creation(start_dt)
            cleaned["start_datetime"] = start_dt
            cleaned["end_datetime"] = None
            if end_time:
                end_dt = timezone.make_aware(
                    datetime.datetime.combine(end_date, end_time)
                )
                if end_dt <= start_dt:
                    self.add_error("end_time", self._end_time_error(cleaned))
                else:
                    cleaned["end_datetime"] = end_dt

            self._clean_recurrence(cleaned, date, start_dt)
            title = cleaned.get("title")
            venue_name = cleaned.get("venue_name")
            plan = cleaned.get("series_plan")
            if plan is not None and title and venue_name:
                check_conflicts([(title, start, venue_name) for start, _ in plan.spans])
            elif title and venue_name:
                qs = Event.objects.filter(
                    title=title, start_datetime=start_dt, venue_name=venue_name
                )
                if self.instance and self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise forms.ValidationError(
                        "An event with this title already exists at this venue "
                        "at the same date and time."
                    )

        return cleaned

    @staticmethod
    def _end_time_error(cleaned) -> str:
        if cleaned.get("end_date"):
            return "End time must be after start time."
        # Most likely an event running past midnight without its end date.
        return (
            "End time must be after start time. If the event ends on a later "
            "day, tick “Ends on a later day” and choose the end date."
        )

    def _clean_recurrence(self, cleaned, day, start_dt) -> None:
        """Set cleaned "pattern" and "ends", or "dates" (the other dates of an
        event on specific dates); on creation also "series_plan" (the
        occurrences to create). Leaves them None for a single event."""
        cleaned["pattern"] = cleaned["ends"] = cleaned["series_plan"] = None
        cleaned["dates"] = None
        if not self.repeat_applies:
            # Editing only this occurrence: the (hidden) repeat fields are
            # ignored, so their errors shouldn't block saving.
            for name in RECURRENCE_FIELDS:
                self.errors.pop(name, None)
            return
        if cleaned.get("repeat") == REPEAT_DATES:
            self._clean_dates(cleaned, start_dt)
            return
        pattern = self._clean_pattern(cleaned, day)
        ends = self._clean_ends(cleaned, day) if pattern else None
        if pattern is None or ends is None:
            return
        cleaned["pattern"], cleaned["ends"] = pattern, ends
        date_fields = ("date", "start_time", "end_time", "end_date")
        if not self._is_creation or any(
            name in self.errors for name in date_fields + RECURRENCE_FIELDS
        ):
            return
        try:
            cleaned["series_plan"] = plan_creation(
                pattern, ends, start_dt, cleaned.get("end_datetime"), self._user
            )
        except forms.ValidationError as exc:
            self.add_error("repeat", exc)

    def _clean_dates(self, cleaned, start_dt) -> None:
        """Validate the specific-dates list into cleaned "dates" (sorted spans
        of the other dates) and, on creation, "series_plan"."""
        formset = self.extra_dates
        if not formset.is_valid():
            # Shown at the repeat field and in the live preview, so each
            # names its row by date.
            errors = list(formset.non_form_errors())
            for form in formset:
                day = form.cleaned_data.get("date")
                label = date_format(day, "D j M") if day else "Date"
                errors += [f"{label}: {error}" for error in form.non_field_errors()]
                errors += [
                    f"{label}: {error}"
                    for name in form.fields
                    for error in form.errors.get(name, [])
                ]
            self.add_error("repeat", errors)
            return
        spans = sorted(
            (
                form.cleaned_data["span"]
                for form in formset
                if form.cleaned_data.get("span")
            ),
            key=lambda span: span[0],
        )
        if not spans:
            self.add_error(
                "repeat",
                "Add at least one more date, or choose “Does not repeat”.",
            )
            return
        cleaned["dates"] = spans
        if not self._is_creation or any(
            name in self.errors
            for name in ("date", "start_time", "end_time", "end_date")
        ):
            return
        try:
            cleaned["series_plan"] = plan_dates(
                [(start_dt, cleaned.get("end_datetime")), *spans], self._user
            )
        except forms.ValidationError as exc:
            self.add_error("repeat", exc)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.start_datetime = self.cleaned_data["start_datetime"]
        instance.end_datetime = self.cleaned_data.get("end_datetime")
        if commit:
            instance.save()
        return instance
