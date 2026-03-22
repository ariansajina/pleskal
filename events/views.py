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

from .forms import EventForm
from .images import validate_and_process
from .models import Event, EventCategory

EVENTS_PER_PAGE = 20
EVENT_FORM_TEMPLATE = "events/event_form.html"
MAX_UPCOMING_EVENTS_PER_USER = 50


# ---------------------------------------------------------------------------
# Helpers / mixins
# ---------------------------------------------------------------------------


class EventOwnerMixin:
    """Restrict access to the event owner. Returns 403 otherwise."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore[misc]
        user = self.request.user  # type: ignore[attr-defined]
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
        return kwargs

    def form_valid(self, form):
        event = form.save(commit=False)
        event.submitted_by = self.request.user

        # Process uploaded image
        image_file = form.cleaned_data.get("image")
        if image_file:
            processed = validate_and_process(image_file)
            event.image.save(processed.name, processed, save=False)

        event.save()

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

        # --- Filter: date range ---
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")
        date_range_active = False
        if date_from:
            d = _parse_date_safe(date_from)
            if d:
                qs = qs.filter(start_datetime__date__gte=d)
                date_range_active = True
        if date_to:
            d = _parse_date_safe(date_to)
            if d:
                qs = qs.filter(start_datetime__date__lte=d)
                date_range_active = True

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

        return qs, categories, date_from, date_to, search_query, date_range_active

    def get(self, request):
        from django.shortcuts import render

        expiry_cutoff = timezone.now() - timezone.timedelta(days=2 * 365)
        qs = Event.objects.filter(start_datetime__gte=expiry_cutoff).select_related(
            "submitted_by"
        )

        qs, categories, date_from, date_to, search_query, date_range_active = (
            self._apply_filters(qs, request)
        )

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

        ctx = {
            "page_obj": page_obj,
            "events": page_obj.object_list,
            "category_choices": EventCategory.choices,
            "selected_categories": categories,
            "show_past": show_past,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "date_range_active": date_range_active,
            "is_free": request.GET.get("is_free") == "1",
            "is_wheelchair_accessible": request.GET.get("is_wheelchair_accessible")
            == "1",
            "search_query": search_query,
            "upcoming_count": upcoming_count,
            "past_count": past_count,
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
        return get_object_or_404(Event, slug=self.kwargs["slug"])


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

    def form_valid(self, form):
        event = form.save(commit=False)

        # Process newly uploaded image
        image_file = form.cleaned_data.get("image")
        if image_file and hasattr(image_file, "read"):
            processed = validate_and_process(image_file)
            event.image.save(processed.name, processed, save=False)

        event.save()
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
        if self._upcoming_events_count(request) >= MAX_UPCOMING_EVENTS_PER_USER:
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
        return render(
            request,
            EVENT_FORM_TEMPLATE,
            {"form": form, "page_title": "Duplicate Event"},
        )

    def post(self, request, slug):
        from django.shortcuts import render

        source = get_object_or_404(Event, slug=slug)
        self._check_owner(request, source)
        if self._check_event_limit(request):
            return redirect("my_events")
        form = EventForm(request.POST, request.FILES, creation=True)
        if form.is_valid():
            event = form.save(commit=False)
            event.submitted_by = request.user
            image_file = form.cleaned_data.get("image")
            if image_file:
                processed = validate_and_process(image_file)
                event.image.save(processed.name, processed, save=False)
            event.save()
            messages.success(request, "Event duplicated.")
            return redirect("event_detail", slug=event.slug)
        return render(
            request,
            EVENT_FORM_TEMPLATE,
            {"form": form, "page_title": "Duplicate Event"},
        )


class SubscribeView(TemplateView):
    template_name = "events/subscribe.html"
