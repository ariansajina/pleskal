import calendar
import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView, View
from django.views.generic.detail import DetailView

from config.ratelimit import RateLimitMixin

from .forms import EventForm, EventSeriesForm
from .images import validate_and_process
from .models import Event, EventCategory, EventSeries

EVENTS_PER_PAGE = 30
EVENT_FORM_TEMPLATE = "events/event_form.html"
MAX_UPCOMING_EVENTS_PER_USER = settings.MAX_UPCOMING_EVENTS_PER_USER


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
    return {
        "this_week": (today.isoformat(), week_end.isoformat()),
        "next_week": (next_week_start.isoformat(), next_week_end.isoformat()),
        "this_month": (month_start.isoformat(), month_end.isoformat()),
        "next_month": (next_month_start.isoformat(), next_month_end.isoformat()),
    }


class EventOwnerMixin:
    """Restrict access to the event owner. Returns 403 otherwise."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore
        user = self.request.user  # type: ignore
        if obj.submitted_by != user:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        return obj


class EventSeriesOwnerMixin:
    """Restrict access to the series owner. Returns 403 otherwise."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore
        user = self.request.user  # type: ignore
        if obj.submitted_by != user:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        return obj


class EventCreateView(RateLimitMixin, LoginRequiredMixin, CreateView):
    rate_limit_key = "event_create"
    rate_limit_limit = 20
    rate_limit_window = 3600
    rate_limit_by_user = True

    model = Event
    form_class = EventForm
    template_name = EVENT_FORM_TEMPLATE

    def _upcoming_events_count(self):
        return Event.objects.filter(
            submitted_by=self.request.user,
            start_datetime__gte=timezone.now(),
        ).count()

    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and not request.user.is_system_account
            and self._upcoming_events_count() >= MAX_UPCOMING_EVENTS_PER_USER
        ):
            messages.error(
                request,
                f"You have reached the limit of {MAX_UPCOMING_EVENTS_PER_USER} "
                "upcoming events. Please delete or wait for some events to pass "
                "before submitting new ones.",
            )
            return redirect("my_events")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["creation"] = True
        kwargs["user"] = self.request.user
        return kwargs

    def form_invalid(self, form):
        # Preserve uploaded image in session for re-submission
        image = self.request.FILES.get("image")
        if image:
            self.request.session["pending_image"] = {
                "name": image.name,
                "content": image.read().hex(),
            }
        return super().form_invalid(form)

    def form_valid(self, form):
        event = form.save(commit=False)
        event.submitted_by = self.request.user
        event.is_draft = self.request.POST.get("submit_action") == "draft"

        # Process newly uploaded image or use pending image from failed submission
        image_file = form.cleaned_data.get("image")
        if not image_file and "pending_image" in self.request.session:
            from django.core.files.base import ContentFile

            pending = self.request.session.pop("pending_image")
            image_content = bytes.fromhex(pending["content"])
            image_file = ContentFile(image_content, name=pending["name"])

        if image_file:
            processed = validate_and_process(image_file)
            event.image.save(processed.name, processed, save=False)

        event.save()

        if event.is_draft:
            messages.success(self.request, "Your event has been saved as a draft.")
        else:
            messages.success(self.request, "Your event has been submitted.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Submit an Event"
        if "pending_image" in self.request.session:
            ctx["pending_image"] = self.request.session["pending_image"]
        return ctx


def _parse_date_safe(value):
    """Parse a date string, returning None on failure."""
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        return None


class EventListView(RateLimitMixin, View):
    rate_limit_key = "event_list"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per IP
    rate_limit_methods = ["GET"]

    template_name = "events/event_list.html"
    partial_template_name = "events/partials/event_list_results.html"

    def _apply_filters(self, qs, request):
        from django.db.models import Q

        # --- Filter: category (multi-value) ---
        categories = request.GET.getlist("category")
        valid_categories = {c.value for c in EventCategory}
        categories = [c for c in categories if c in valid_categories]
        if categories:
            qs = qs.filter(category__in=categories)

        # --- Filter: publisher (multi-value) ---
        from django.contrib.auth import get_user_model

        User = get_user_model()
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
                all_system_ids = User.objects.filter(
                    is_system_account=True
                ).values_list("id", flat=True)
                q |= ~Q(submitted_by__in=all_system_ids)
            qs = qs.filter(q)

        # --- Filter: date range ---
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")
        today_str = datetime.date.today().isoformat()
        date_range_active = False

        # Consider the date range "active" (non-default) only if:
        # - date_to is set (any value other than empty), OR
        # - date_from is set to something other than today
        if date_to or (date_from and date_from != today_str):
            date_range_active = True

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
        search_query = request.GET.get("q", "").strip()
        if search_query:
            qs = qs.filter(
                Q(title__icontains=search_query)
                | Q(venue_name__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(submitted_by__display_name__icontains=search_query)
            )

        return (
            qs,
            categories,
            publisher_slugs,
            date_from,
            date_to,
            search_query,
            date_range_active,
        )

    def get(self, request):
        from django.contrib.auth import get_user_model
        from django.shortcuts import render

        User = get_user_model()
        expiry_cutoff = timezone.now() - timezone.timedelta(days=2 * 365)
        qs = Event.objects.filter(
            start_datetime__gte=expiry_cutoff, is_draft=False
        ).select_related("submitted_by", "series")

        (
            qs,
            categories,
            publisher_slugs,
            date_from,
            date_to,
            search_query,
            date_range_active,
        ) = self._apply_filters(qs, request)

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

        # --- Series collapse ---
        # Collapse multi-session series into a single representative event by
        # default. Pass ?expand_series=1 to opt into the flat list. We collapse
        # by keeping the earliest event (in current ordering) per series, then
        # annotating the series-event count for the template.
        expand_series = request.GET.get("expand_series") == "1"
        collapsed_events = list(qs)
        if not expand_series:
            seen_series: set = set()
            unique: list[Event] = []
            series_counts: dict = {}
            for event in collapsed_events:
                series_pk = (
                    getattr(event.series, "pk", None)
                    if event.series is not None
                    else None
                )
                if series_pk is None:
                    unique.append(event)
                    continue
                series_counts[series_pk] = series_counts.get(series_pk, 0) + 1
                if series_pk not in seen_series:
                    seen_series.add(series_pk)
                    unique.append(event)
            for event in unique:
                pk = getattr(event.series, "pk", None)
                if pk is not None:
                    event.series_event_count = series_counts.get(  # ty: ignore[unresolved-attribute]
                        pk, 1
                    )
            collapsed_events = unique

        # --- Pagination ---
        paginator = Paginator(collapsed_events, EVENTS_PER_PAGE)
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
        system_publishers = User.objects.filter(is_system_account=True).order_by(
            "display_name"
        )
        ctx = {
            "page_obj": page_obj,
            "base_query_string": base_query_string,
            "events": page_obj.object_list,
            "category_choices": EventCategory.choices,
            "selected_categories": categories,
            "system_publishers": system_publishers,
            "selected_publishers": publisher_slugs,
            "show_past": show_past,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "today": today.isoformat(),
            "week_start": week_start,
            "week_end": week_end,
            "date_range_active": date_range_active,
            "is_free": request.GET.get("is_free") == "1",
            "is_wheelchair_accessible": request.GET.get("is_wheelchair_accessible")
            == "1",
            "search_query": search_query,
            "upcoming_count": upcoming_count,
            "past_count": past_count,
            "quick_date_ranges": quick_date_ranges,
            "expand_series": expand_series,
        }

        # HTMX: return only the results partial
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
        start = event.start_datetime.strftime("%Y%m%dT%H%M%S")
        end = (event.end_datetime or event.start_datetime).strftime("%Y%m%dT%H%M%S")
        location = event.venue_name
        if event.venue_address:
            location += f", {event.venue_address}"
        params: dict[str, str] = {
            "action": "TEMPLATE",
            "text": str(event.title),
            "dates": f"{start}/{end}",
            "location": location,
        }
        context["google_calendar_url"] = (
            "https://calendar.google.com/calendar/render?" + urlencode(params)
        )
        if event.image:
            context["og_image_url"] = self.request.build_absolute_uri(event.image.url)
        if event.series is not None:
            context["sibling_sessions"] = (
                Event.objects.filter(
                    series=event.series,
                    is_draft=False,
                    start_datetime__gte=timezone.now(),
                )
                .exclude(pk=event.pk)
                .order_by("start_datetime")[:5]
            )
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
        kwargs["user"] = self.request.user
        return kwargs

    def form_invalid(self, form):
        # Preserve uploaded image in session for re-submission
        image = self.request.FILES.get("image")
        if image:
            self.request.session["pending_image"] = {
                "name": image.name,
                "content": image.read().hex(),
            }
        return super().form_invalid(form)

    def form_valid(self, form):
        event = form.save(commit=False)

        submit_action = self.request.POST.get("submit_action")
        if submit_action == "draft":
            event.is_draft = True
        elif submit_action == "publish":
            event.is_draft = False
        # If neither button was used (fallback), keep existing value.

        # Process newly uploaded image or use pending image from failed submission
        image_file = form.cleaned_data.get("image")
        if not image_file and "pending_image" in self.request.session:
            from django.core.files.base import ContentFile

            pending = self.request.session.pop("pending_image")
            image_content = bytes.fromhex(pending["content"])
            image_file = ContentFile(image_content, name=pending["name"])

        if image_file and hasattr(image_file, "read"):
            processed = validate_and_process(image_file)
            event.image.save(processed.name, processed, save=False)

        event.save()
        if event.is_draft:
            messages.success(self.request, "Event saved as draft.")
        else:
            messages.success(self.request, "Event updated.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Event"
        if "pending_image" in self.request.session:
            ctx["pending_image"] = self.request.session["pending_image"]
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


class EventDuplicateView(RateLimitMixin, LoginRequiredMixin, View):
    rate_limit_key = "event_duplicate"
    rate_limit_limit = 20
    rate_limit_window = 60  # 20 requests per minute per user
    rate_limit_by_user = True

    def _check_owner(self, request, source):
        if source.submitted_by != request.user:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied

    def _upcoming_events_count(self, request):
        return Event.objects.filter(
            submitted_by=request.user,
            start_datetime__gte=timezone.now(),
        ).count()

    def _check_event_limit(self, request):
        if (
            not request.user.is_system_account
            and self._upcoming_events_count(request) >= MAX_UPCOMING_EVENTS_PER_USER
        ):
            messages.error(
                request,
                f"You have reached the limit of {MAX_UPCOMING_EVENTS_PER_USER} "
                "upcoming events. Please delete or wait for some events to pass "
                "before submitting new ones.",
            )
            return True
        return False

    def get(self, request, slug):
        from django.shortcuts import render

        source = get_object_or_404(Event, slug=slug)
        self._check_owner(request, source)
        if self._check_event_limit(request):
            return redirect("my_events")
        form = EventForm(
            creation=True,
            user=request.user,
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
                "series": source.series.pk if source.series is not None else None,
            },
        )
        return render(
            request,
            EVENT_FORM_TEMPLATE,
            {
                "form": form,
                "page_title": "Duplicate Event",
                "source_image": source.image or None,
            },
        )

    def post(self, request, slug):
        from django.core.files.base import ContentFile
        from django.shortcuts import render

        source = get_object_or_404(Event, slug=slug)
        self._check_owner(request, source)
        if self._check_event_limit(request):
            return redirect("my_events")
        form = EventForm(request.POST, request.FILES, creation=True, user=request.user)
        if form.is_valid():
            event = form.save(commit=False)
            event.submitted_by = request.user
            event.is_draft = request.POST.get("submit_action") == "draft"
            image_file = form.cleaned_data.get("image")
            if image_file:
                processed = validate_and_process(image_file)
                event.image.save(processed.name, processed, save=False)
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
        return render(
            request,
            EVENT_FORM_TEMPLATE,
            {
                "form": form,
                "page_title": "Duplicate Event",
                "source_image": source.image or None,
            },
        )


class EventToggleDraftView(RateLimitMixin, LoginRequiredMixin, View):
    rate_limit_key = "event_update"
    rate_limit_limit = 20
    rate_limit_window = 60
    rate_limit_by_user = True

    def post(self, request, slug):
        event = get_object_or_404(Event, slug=slug)
        if event.submitted_by != request.user:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
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
        from django.contrib.auth import get_user_model

        ctx = super().get_context_data(**kwargs)
        User = get_user_model()
        ctx["category_choices"] = EventCategory.choices
        upcoming_publisher_ids = (
            Event.objects.filter(
                start_datetime__gte=timezone.now(),
                is_draft=False,
                submitted_by__isnull=False,
            )
            .values_list("submitted_by_id", flat=True)
            .distinct()
        )
        ctx["publishers"] = User.objects.filter(
            pk__in=upcoming_publisher_ids, is_system_account=True
        ).order_by("display_name")
        ctx["has_community_publishers"] = User.objects.filter(
            pk__in=upcoming_publisher_ids, is_system_account=False
        ).exists()
        return ctx


# ---------------------------------------------------------------------------
# EventSeries views
# ---------------------------------------------------------------------------


SERIES_FORM_TEMPLATE = "events/series_form.html"


class EventSeriesDetailView(DetailView):
    model = EventSeries
    template_name = "events/series_detail.html"
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "series"

    def get_object(self, queryset=None):
        series = get_object_or_404(EventSeries, slug=self.kwargs["slug"])
        # A series is visible iff it has at least one published (non-draft)
        # event, OR the requesting user is the owner.
        user = self.request.user
        if user.is_authenticated and series.submitted_by_id == user.id:
            return series
        if not series.has_visible_events:
            from django.http import Http404

            raise Http404
        return series

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        series = self.object
        user = self.request.user
        is_owner = user.is_authenticated and series.submitted_by_id == user.id
        events_qs = series.events.all().order_by("start_datetime")
        if not is_owner:
            events_qs = events_qs.filter(is_draft=False)
        now = timezone.now()
        ctx["upcoming_events"] = events_qs.filter(start_datetime__gte=now)
        ctx["past_events"] = events_qs.filter(start_datetime__lt=now).order_by(
            "-start_datetime"
        )
        ctx["is_owner"] = is_owner
        return ctx


class EventSeriesCreateView(RateLimitMixin, LoginRequiredMixin, CreateView):
    rate_limit_key = "series_create"
    rate_limit_limit = 20
    rate_limit_window = 3600
    rate_limit_by_user = True

    model = EventSeries
    form_class = EventSeriesForm
    template_name = SERIES_FORM_TEMPLATE

    def form_valid(self, form):
        series = form.save(commit=False)
        series.submitted_by = self.request.user
        series.save()
        messages.success(self.request, "Series created.")
        return redirect("series_detail", slug=series.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Create Event Series"
        return ctx


class EventSeriesUpdateView(
    RateLimitMixin, LoginRequiredMixin, EventSeriesOwnerMixin, UpdateView
):
    rate_limit_key = "series_update"
    rate_limit_limit = 20
    rate_limit_window = 60
    rate_limit_by_user = True

    model = EventSeries
    form_class = EventSeriesForm
    template_name = SERIES_FORM_TEMPLATE
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def form_valid(self, form):
        series = form.save()
        messages.success(self.request, "Series updated.")
        return redirect("series_detail", slug=series.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Event Series"
        return ctx


class EventSeriesDeleteView(LoginRequiredMixin, EventSeriesOwnerMixin, DeleteView):
    model = EventSeries
    template_name = "events/series_confirm_delete.html"
    success_url = reverse_lazy("event_list")
    slug_field = "slug"
    slug_url_kwarg = "slug"
    context_object_name = "series"

    def form_valid(self, form):
        messages.success(self.request, "Series deleted. Sessions remain.")
        return super().form_valid(form)
