import calendar
import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView, View
from django.views.generic.detail import DetailView

from config.ratelimit import RateLimitMixin

from .forms import EventForm
from .images import validate_and_process
from .models import Event, EventCategory
from .sharing import apple_calendar_url, google_calendar_url, outlook_calendar_url

EVENTS_PER_PAGE = 30
EVENT_FORM_TEMPLATE = "events/event_form.html"
MAX_UPCOMING_EVENTS_PER_USER = settings.MAX_UPCOMING_EVENTS_PER_USER
SEARCH_QUERY_MAX_LENGTH = 200


# ---------------------------------------------------------------------------
# Helpers / mixins
# ---------------------------------------------------------------------------


def _get_quick_date_ranges():
    """Return ISO date strings for common quick-filter ranges."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    next_week_start = week_start + datetime.timedelta(days=7)
    next_week_end = next_week_start + datetime.timedelta(days=6)
    month_start = today.replace(day=1)
    month_last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=month_last_day)
    next_month_start = month_end + datetime.timedelta(days=1)
    next_month_last_day = calendar.monthrange(
        next_month_start.year, next_month_start.month
    )[1]
    next_month_end = next_month_start.replace(day=next_month_last_day)
    saturday = week_start + datetime.timedelta(days=5)
    sunday = week_start + datetime.timedelta(days=6)
    weekend_start = max(today, saturday)
    return {
        "this_week": (today.isoformat(), week_end.isoformat()),
        "this_weekend": (weekend_start.isoformat(), sunday.isoformat()),
        "next_week": (next_week_start.isoformat(), next_week_end.isoformat()),
        "this_month": (month_start.isoformat(), month_end.isoformat()),
        "next_month": (next_month_start.isoformat(), next_month_end.isoformat()),
    }


def _advanced_filters_open(
    *,
    search_query,
    categories,
    publisher_slugs,
    is_free,
    is_wheelchair_accessible,
    date_from,
    date_to,
    quick_date_ranges,
):
    """True when a filter that only lives inside the "More filters" panel is
    active, so the disclosure should render open on page load."""
    if (
        search_query
        or categories
        or publisher_slugs
        or is_free
        or is_wheelchair_accessible
    ):
        return True
    if date_from or date_to:
        quickbar_ranges = {
            quick_date_ranges["this_week"],
            quick_date_ranges["next_week"],
        }
        if (date_from or "", date_to or "") not in quickbar_ranges:
            return True
    return False


def _attach_processed_image(form, event, image_file) -> bool:
    """Process the upload onto event.image; on invalid image, add a form error."""
    try:
        processed = validate_and_process(image_file)
    except ValidationError as exc:
        form.add_error("image", exc)
        return False
    event.image.save(processed.name, processed, save=False)
    return True


def _publisher_ids_with_events():
    """User ids with at least one published (non-draft) event — past or present."""
    return (
        Event.objects.filter(is_draft=False, submitted_by__isnull=False)
        .values_list("submitted_by_id", flat=True)
        .distinct()
    )


def _has_community_publishers():
    """True if any community (non-system) publisher has a published event.

    Gates the catch-all "Other"/community badge on both pages: it only makes
    sense to subscribe to or filter by community events when some exist.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.filter(
        is_system_account=False, pk__in=_publisher_ids_with_events()
    ).exists()


def _list_filter_publishers():
    """Publisher badges for the event list / map filters.

    The filter narrows the *visible* event set, so only system publishers that
    actually have events (past or present) get a badge — a publisher with no
    events (e.g. a retired scraper whose events were purged) would be a dead
    filter. Returns ``(system_publishers, has_community_publishers)``.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    system_publishers = User.objects.filter(
        is_system_account=True, pk__in=_publisher_ids_with_events()
    ).order_by("display_name")
    return system_publishers, _has_community_publishers()


def _subscribe_publishers():
    """Publisher badges for the subscribe page.

    Forward-looking: every active (non-disabled) system publisher is shown even
    when it has no current events, because it may publish future ones. Retired
    sources are deactivated (``is_active=False``) and therefore hidden. Returns
    ``(system_publishers, has_community_publishers)``.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    system_publishers = User.objects.filter(
        is_system_account=True, is_active=True
    ).order_by("display_name")
    return system_publishers, _has_community_publishers()


def _require_owner(request, obj) -> None:
    """Raise PermissionDenied unless *request.user* submitted *obj*."""
    if obj.submitted_by != request.user:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied


class EventOwnerMixin:
    """Restrict access to the event owner. Returns 403 otherwise."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore
        _require_owner(self.request, obj)  # type: ignore
        return obj


class UpcomingEventLimitMixin:
    """Blocks event creation/duplication once a user is at MAX_UPCOMING_EVENTS_PER_USER.

    System accounts (scrapers) are exempt.
    """

    def _upcoming_events_count(self, user) -> int:
        return Event.objects.filter(
            submitted_by=user,
            start_datetime__gte=timezone.now(),
        ).count()

    def _reject_if_over_event_limit(self, request):
        """Return a redirect response if *request.user* is at the limit, else None."""
        if (
            not request.user.is_system_account
            and self._upcoming_events_count(request.user)
            >= MAX_UPCOMING_EVENTS_PER_USER
        ):
            messages.error(
                request,
                f"You have reached the limit of {MAX_UPCOMING_EVENTS_PER_USER} "
                "upcoming events. Please delete or wait for some events to pass "
                "before submitting new ones.",
            )
            return redirect("my_events")
        return None


def _reprompt_image_if_needed(request, form) -> None:
    """Warn the user to re-attach their image after an unrelated validation error.

    Uploaded files aren't preserved across a failed submission, so if the
    image itself was valid but other fields weren't, the browser will have
    cleared the file input and the user needs to re-select it.
    """
    if "image" in request.FILES and "image" not in form.errors:
        messages.warning(
            request,
            "Please re-select your image — it wasn't kept after the "
            "form errors below were fixed.",
        )


class EventCreateView(
    RateLimitMixin, LoginRequiredMixin, UpcomingEventLimitMixin, CreateView
):
    rate_limit_key = "event_create"
    rate_limit_limit = 20
    rate_limit_window = 3600
    rate_limit_by_user = True

    model = Event
    form_class = EventForm
    template_name = EVENT_FORM_TEMPLATE

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            over_limit_response = self._reject_if_over_event_limit(request)
            if over_limit_response:
                return over_limit_response
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["creation"] = True
        return kwargs

    def form_invalid(self, form):
        _reprompt_image_if_needed(self.request, form)
        return super().form_invalid(form)

    def form_valid(self, form):
        event = form.save(commit=False)
        event.submitted_by = self.request.user
        event.is_draft = self.request.POST.get("submit_action") == "draft"

        image_file = form.cleaned_data.get("image")

        if image_file and not _attach_processed_image(form, event, image_file):
            return self.form_invalid(form)

        event.save()

        if event.is_draft:
            messages.success(self.request, "Your event has been saved as a draft.")
        else:
            messages.success(self.request, "Your event has been submitted.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Submit an Event"
        return ctx


def _parse_date_safe(value):
    """Parse a date string, returning None on failure."""
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        return None


def _filtered_event_queryset(request):
    """Return `(queryset, filter_state)` for the shared event filter UI.

    Applies the same filters as the event list view (category, publisher,
    date range, is_free, is_wheelchair_accessible, search) to a base
    queryset that excludes drafts and events older than two years. Callers
    are responsible for any upcoming/past toggle and ordering.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    expiry_cutoff = timezone.now() - timezone.timedelta(days=2 * 365)
    qs = Event.objects.filter(
        start_datetime__gte=expiry_cutoff, is_draft=False
    ).select_related("submitted_by")

    # --- Filter: category (multi-value) ---
    categories = request.GET.getlist("category")
    valid_categories = {c.value for c in EventCategory}
    categories = [c for c in categories if c in valid_categories]
    if categories:
        qs = qs.filter(category__in=categories)

    # --- Filter: publisher (multi-value) ---
    publisher_slugs = request.GET.getlist("publisher")
    if publisher_slugs:
        system_user_ids = User.objects.filter(
            is_system_account=True,
            display_name_slug__in=[s for s in publisher_slugs if s != "other"],
        ).values_list("id", flat=True)

        q = Q()
        if any(s != "other" for s in publisher_slugs):
            q |= Q(submitted_by__in=system_user_ids)
        if "other" in publisher_slugs:
            all_system_ids = User.objects.filter(is_system_account=True).values_list(
                "id", flat=True
            )
            q |= ~Q(submitted_by__in=all_system_ids)
        qs = qs.filter(q)

    # --- Filter: date range ---
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    today_str = datetime.date.today().isoformat()
    # The date range is "active" (non-default) only if date_to is set or
    # date_from is something other than today's date.
    date_range_active = bool(date_to or (date_from and date_from != today_str))

    if date_from:
        d = _parse_date_safe(date_from)
        if d:
            qs = qs.filter(start_datetime__date__gte=d)
    if date_to:
        d = _parse_date_safe(date_to)
        if d:
            qs = qs.filter(start_datetime__date__lte=d)

    # --- Filter: free / wheelchair accessible ---
    if request.GET.get("is_free") == "1":
        qs = qs.filter(is_free=True)
    if request.GET.get("is_wheelchair_accessible") == "1":
        qs = qs.filter(is_wheelchair_accessible=True)

    # --- Filter: search ---
    search_query = request.GET.get("q", "").strip()[:SEARCH_QUERY_MAX_LENGTH]
    for term in search_query.split():
        qs = qs.filter(
            Q(title__icontains=term)
            | Q(venue_name__icontains=term)
            | Q(description__icontains=term)
            | Q(submitted_by__display_name__icontains=term)
        )

    filter_state = {
        "categories": categories,
        "publisher_slugs": publisher_slugs,
        "date_from": date_from,
        "date_to": date_to,
        "search_query": search_query,
        "date_range_active": date_range_active,
    }
    return qs, filter_state


class EventListView(RateLimitMixin, View):
    rate_limit_key = "event_list"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per IP
    rate_limit_methods = ["GET"]

    template_name = "events/event_list.html"
    partial_template_name = "events/partials/event_list_results.html"

    def get(self, request):
        from django.shortcuts import render

        qs, filter_state = _filtered_event_queryset(request)
        categories = filter_state["categories"]
        publisher_slugs = filter_state["publisher_slugs"]
        date_from = filter_state["date_from"]
        date_to = filter_state["date_to"]
        search_query = filter_state["search_query"]
        date_range_active = filter_state["date_range_active"]

        # --- Counts for upcoming/past toggle (computed after other filters) ---
        now = timezone.now()
        upcoming_count = qs.filter(start_datetime__gte=now).count()
        past_count = qs.filter(start_datetime__lt=now).count()

        # --- Filter: upcoming vs past ---
        # When a date range is explicitly set, bypass the toggle — the user has
        # already specified the time window and applying past/upcoming on top would
        # silently discard half the results with no visible explanation.
        show_past = request.GET.get("past") == "1"
        if date_range_active:
            qs = qs.order_by("start_datetime")
        elif show_past:
            qs = qs.filter(start_datetime__lt=now).order_by("-start_datetime")
        else:
            qs = qs.filter(start_datetime__gte=now).order_by("start_datetime")

        # --- Pagination ---
        paginator = Paginator(qs, EVENTS_PER_PAGE)
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Build a query string with all current params except `page`, so
        # pagination links preserve active filters.
        params = request.GET.copy()
        params.pop("page", None)
        base_query_string = params.urlencode()

        quick_date_ranges = _get_quick_date_ranges()
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        system_publishers, has_community_publishers = _list_filter_publishers()
        is_free = request.GET.get("is_free") == "1"
        is_wheelchair_accessible = request.GET.get("is_wheelchair_accessible") == "1"
        ctx = {
            "page_obj": page_obj,
            "base_query_string": base_query_string,
            "events": page_obj.object_list,
            "category_choices": EventCategory.choices,
            "selected_categories": categories,
            "system_publishers": system_publishers,
            "has_community_publishers": has_community_publishers,
            "selected_publishers": publisher_slugs,
            "show_past": show_past,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "today": today.isoformat(),
            "week_start": week_start,
            "week_end": week_end,
            "date_range_active": date_range_active,
            "is_free": is_free,
            "is_wheelchair_accessible": is_wheelchair_accessible,
            "search_query": search_query,
            "upcoming_count": upcoming_count,
            "past_count": past_count,
            "quick_date_ranges": quick_date_ranges,
            "advanced_filters_open": _advanced_filters_open(
                search_query=search_query,
                categories=categories,
                publisher_slugs=publisher_slugs,
                is_free=is_free,
                is_wheelchair_accessible=is_wheelchair_accessible,
                date_from=date_from,
                date_to=date_to,
                quick_date_ranges=quick_date_ranges,
            ),
        }

        # HTMX: return only the results partial
        if request.headers.get("HX-Request"):
            return render(request, self.partial_template_name, ctx)

        return render(request, self.template_name, ctx)


class EventMapView(RateLimitMixin, View):
    rate_limit_key = "event_map"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per IP
    rate_limit_methods = ["GET"]

    template_name = "events/event_map.html"
    partial_template_name = "events/partials/event_map_results.html"

    # ~1m precision; events sharing an address geocode to identical floats and
    # collapse to one marker, but coordinates that differ by more than a metre
    # stay on separate pins.
    LOCATION_GROUP_PRECISION = 5

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "MAP_VIEW_ENABLED", False):
            from django.http import Http404

            raise Http404("Map view is disabled")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from collections import OrderedDict

        from django.shortcuts import render

        qs, filter_state = _filtered_event_queryset(request)

        # Map view shows upcoming events only — past events are browsed via the
        # list view's "past" toggle.
        now = timezone.now()
        events = list(qs.filter(start_datetime__gte=now).order_by("start_datetime"))

        with_coords = [e for e in events if e.has_map_location]
        without_coords = [e for e in events if not e.has_map_location]

        groups: OrderedDict[tuple[float, float], list[dict]] = OrderedDict()
        group_meta: dict[tuple[float, float], dict] = {}
        for event in with_coords:
            lat = float(event.latitude)
            lng = float(event.longitude)
            key = (
                round(lat, self.LOCATION_GROUP_PRECISION),
                round(lng, self.LOCATION_GROUP_PRECISION),
            )
            if key not in groups:
                groups[key] = []
                group_meta[key] = {
                    "lat": lat,
                    "lng": lng,
                    "venue_name": event.venue_name,
                }
            groups[key].append(
                {
                    "slug": event.slug,
                    "title": event.title,
                    "venue_name": event.venue_name,
                    "category": event.category,
                    "category_display": event.get_category_display(),
                    "start_datetime": event.start_datetime.isoformat(),
                    "url": reverse("event_detail", args=[event.slug]),
                }
            )
        pin_data = [
            {**group_meta[key], "events": events} for key, events in groups.items()
        ]

        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        system_publishers, has_community_publishers = _list_filter_publishers()
        quick_date_ranges = _get_quick_date_ranges()
        is_free = request.GET.get("is_free") == "1"
        is_wheelchair_accessible = request.GET.get("is_wheelchair_accessible") == "1"

        ctx = {
            "events_with_coords": with_coords,
            "events_without_coords": without_coords,
            "pin_data": pin_data,
            "category_choices": EventCategory.choices,
            "selected_categories": filter_state["categories"],
            "system_publishers": system_publishers,
            "has_community_publishers": has_community_publishers,
            "selected_publishers": filter_state["publisher_slugs"],
            "date_from": filter_state["date_from"] or "",
            "date_to": filter_state["date_to"] or "",
            "today": today.isoformat(),
            "week_start": week_start,
            "week_end": week_end,
            "date_range_active": filter_state["date_range_active"],
            "is_free": is_free,
            "is_wheelchair_accessible": is_wheelchair_accessible,
            "search_query": filter_state["search_query"],
            "quick_date_ranges": quick_date_ranges,
            "advanced_filters_open": _advanced_filters_open(
                search_query=filter_state["search_query"],
                categories=filter_state["categories"],
                publisher_slugs=filter_state["publisher_slugs"],
                is_free=is_free,
                is_wheelchair_accessible=is_wheelchair_accessible,
                date_from=filter_state["date_from"],
                date_to=filter_state["date_to"],
                quick_date_ranges=quick_date_ranges,
            ),
        }

        if request.headers.get("HX-Request"):
            return render(request, self.partial_template_name, ctx)
        return render(request, self.template_name, ctx)


class EventDetailView(DetailView):
    model = Event
    template_name = "events/event_detail.html"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_object(self, queryset=None):
        event = get_object_or_404(Event, slug=self.kwargs["slug"])
        if event.is_draft:
            user = self.request.user
            if not user.is_authenticated or user != event.submitted_by:
                from django.http import Http404

                raise Http404
        return event

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        ical_absolute = self.request.build_absolute_uri(
            reverse("event_ical_single", kwargs={"slug": event.slug})
        )
        context["google_calendar_url"] = google_calendar_url(event)
        context["outlook_calendar_url"] = outlook_calendar_url(event)
        context["apple_calendar_url"] = apple_calendar_url(ical_absolute)
        context["og_image_url"] = self.request.build_absolute_uri(
            event.display_image_url
        )
        if not event.is_draft:
            from .structured_data import event_jsonld

            context["event_jsonld"] = event_jsonld(event, self.request)
        return context


class MyEventsView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect("publisher_profile", slug=request.user.display_name_slug)


class EventUpdateView(RateLimitMixin, LoginRequiredMixin, EventOwnerMixin, UpdateView):
    rate_limit_key = "event_update"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per user
    rate_limit_by_user = True
    model = Event
    form_class = EventForm
    template_name = EVENT_FORM_TEMPLATE
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["creation"] = False
        return kwargs

    def form_invalid(self, form):
        _reprompt_image_if_needed(self.request, form)
        return super().form_invalid(form)

    def form_valid(self, form):
        event = form.save(commit=False)

        submit_action = self.request.POST.get("submit_action")
        if submit_action == "draft":
            event.is_draft = True
        elif submit_action == "publish":
            event.is_draft = False
        # If neither button was used (fallback), keep existing value.

        image_file = form.cleaned_data.get("image")

        if image_file and not _attach_processed_image(form, event, image_file):
            return self.form_invalid(form)

        event.save()
        if event.is_draft:
            messages.success(self.request, "Event saved as draft.")
        else:
            messages.success(self.request, "Event updated.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Event"
        return ctx


class EventDeleteView(LoginRequiredMixin, EventOwnerMixin, DeleteView):
    model = Event
    template_name = "events/event_confirm_delete.html"
    success_url = reverse_lazy("my_events")
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def form_valid(self, form):
        messages.success(self.request, "Event deleted.")
        return super().form_valid(form)


class EventDuplicateView(
    RateLimitMixin, LoginRequiredMixin, UpcomingEventLimitMixin, View
):
    rate_limit_key = "event_duplicate"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per user
    rate_limit_by_user = True

    def _render_form(self, request, form, source):
        from django.shortcuts import render

        return render(
            request,
            EVENT_FORM_TEMPLATE,
            {
                "form": form,
                "page_title": "Duplicate Event",
                "source_image": source.image or None,
            },
        )

    def get(self, request, slug):
        source = get_object_or_404(Event, slug=slug)
        _require_owner(request, source)
        over_limit_response = self._reject_if_over_event_limit(request)
        if over_limit_response:
            return over_limit_response
        form = EventForm(
            creation=True,
            initial={
                "title": source.title,
                "description": source.description,
                "venue_name": source.venue_name,
                "venue_address": source.venue_address,
                "category": source.category,
                "is_free": source.is_free,
                "is_wheelchair_accessible": source.is_wheelchair_accessible,
                "price_note": source.price_note,
                "source_url": source.source_url,
            },
        )
        return self._render_form(request, form, source)

    def post(self, request, slug):
        from django.core.files.base import ContentFile

        source = get_object_or_404(Event, slug=slug)
        _require_owner(request, source)
        over_limit_response = self._reject_if_over_event_limit(request)
        if over_limit_response:
            return over_limit_response
        form = EventForm(request.POST, request.FILES, creation=True)
        if not form.is_valid():
            return self._render_form(request, form, source)

        event = form.save(commit=False)
        event.submitted_by = request.user
        event.is_draft = request.POST.get("submit_action") == "draft"
        image_file = form.cleaned_data.get("image")
        if image_file:
            if not _attach_processed_image(form, event, image_file):
                return self._render_form(request, form, source)
        elif source.image and request.POST.get("copy_source_image"):
            source.image.open()
            event.image.save(
                source.image.name.split("/")[-1],
                ContentFile(source.image.read()),
                save=False,
            )
            source.image.close()
        event.save()
        if event.is_draft:
            messages.success(request, "Event duplicated and saved as draft.")
        else:
            messages.success(request, "Event duplicated.")
        return redirect("event_detail", slug=event.slug)


class EventToggleDraftView(RateLimitMixin, LoginRequiredMixin, View):
    rate_limit_key = "event_update"
    rate_limit_limit = 20
    rate_limit_window = 60
    rate_limit_by_user = True

    def post(self, request, slug):
        event = get_object_or_404(Event, slug=slug)
        _require_owner(request, event)
        event.is_draft = not event.is_draft
        event.save(update_fields=["is_draft", "updated_at"])
        if event.is_draft:
            messages.success(request, "Event saved as draft.")
        else:
            messages.success(request, "Event published.")
        return redirect("event_detail", slug=event.slug)


class SubscribeView(TemplateView):
    template_name = "events/subscribe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["category_choices"] = EventCategory.choices
        publishers, has_community_publishers = _subscribe_publishers()
        ctx["publishers"] = publishers
        ctx["has_community_publishers"] = has_community_publishers
        return ctx


GUIDE_MARKDOWN_PATH = Path(__file__).resolve().parent / "content" / "guide.md"


class GuideView(TemplateView):
    """Render the static Guide page from a Markdown source file."""

    template_name = "guide.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["guide_markdown"] = GUIDE_MARKDOWN_PATH.read_text(encoding="utf-8")
        return ctx
