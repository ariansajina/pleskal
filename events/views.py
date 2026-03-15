from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View
from django.views.generic.detail import DetailView

from .forms import EventForm
from .image_utils import process_event_image
from .models import Event, EventCategory, EventStatus

EVENTS_PER_PAGE = 20


# ---------------------------------------------------------------------------
# Helpers / mixins
# ---------------------------------------------------------------------------


class EventOwnerOrModeratorMixin:
    """Restrict access to the event owner or a moderator. Returns 403 otherwise."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore[misc]
        user = self.request.user  # type: ignore[attr-defined]
        if obj.submitted_by != user and not user.is_moderator:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        return obj


# ---------------------------------------------------------------------------
# Feature 6: Event Submission
# ---------------------------------------------------------------------------


class EventCreateView(LoginRequiredMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"

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
            processed, thumbnail = process_event_image(image_file)
            event.image = processed
            event.image_thumbnail = thumbnail

        event.save()

        messages.success(self.request, "Your event has been submitted.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Submit an Event"
        return ctx


# ---------------------------------------------------------------------------
# Feature 8: Public Event Listings with HTMX filtering
# ---------------------------------------------------------------------------


class EventListView(View):
    template_name = "events/event_list.html"
    partial_template_name = "events/partials/event_list_results.html"

    def get(self, request):
        from django.shortcuts import render

        qs = Event.objects.filter(status=EventStatus.APPROVED).select_related(
            "submitted_by"
        )

        # --- Filter: upcoming vs past ---
        show_past = request.GET.get("past") == "1"
        now = timezone.now()
        if show_past:
            qs = qs.filter(start_datetime__lt=now).order_by("-start_datetime")
        else:
            qs = qs.filter(start_datetime__gte=now).order_by("start_datetime")

        # --- Filter: category (multi-value) ---
        categories = request.GET.getlist("category")
        valid_categories = {c.value for c in EventCategory}
        categories = [c for c in categories if c in valid_categories]
        if categories:
            qs = qs.filter(category__in=categories)

        # --- Filter: date range ---
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")
        if date_from:
            try:
                from django.utils.dateparse import parse_date

                d = parse_date(date_from)
                if d:
                    qs = qs.filter(start_datetime__date__gte=d)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                from django.utils.dateparse import parse_date

                d = parse_date(date_to)
                if d:
                    qs = qs.filter(start_datetime__date__lte=d)
            except (ValueError, TypeError):
                pass

        # --- Filter: free events ---
        if request.GET.get("is_free") == "1":
            qs = qs.filter(is_free=True)

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
            "is_free": request.GET.get("is_free") == "1",
        }

        # HTMX: return only the results partial
        if request.headers.get("HX-Request"):
            return render(request, self.partial_template_name, ctx)

        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# Feature 9: Event Detail
# ---------------------------------------------------------------------------


class EventDetailView(DetailView):
    model = Event
    template_name = "events/event_detail.html"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_object(self, queryset=None):
        obj = get_object_or_404(Event, slug=self.kwargs["slug"])
        user = self.request.user

        # Approved events are public
        if obj.status == EventStatus.APPROVED:
            return obj

        # Owner can see their own pending/rejected events
        if user.is_authenticated and obj.submitted_by == user:
            return obj

        # Moderators can see everything
        if user.is_authenticated and user.is_moderator:
            return obj

        raise Http404


# ---------------------------------------------------------------------------
# Feature 10: Event Management (My Events, Edit, Delete)
# ---------------------------------------------------------------------------


class MyEventsView(LoginRequiredMixin, ListView):
    model = Event
    template_name = "events/my_events.html"
    context_object_name = "events"

    def get_queryset(self):
        return Event.objects.filter(submitted_by=self.request.user).order_by(
            "-created_at"
        )


class EventUpdateView(LoginRequiredMixin, EventOwnerOrModeratorMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = "events/event_form.html"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["creation"] = False
        return kwargs

    def form_valid(self, form):
        event = form.save(commit=False)

        # If editing a rejected event, reset to pending
        if event.status == EventStatus.REJECTED:
            event.status = EventStatus.PENDING
            event.rejection_note = ""

        # Process newly uploaded image
        image_file = form.cleaned_data.get("image")
        if image_file and hasattr(image_file, "read"):
            processed, thumbnail = process_event_image(image_file)
            event.image = processed
            event.image_thumbnail = thumbnail

        event.save()
        messages.success(self.request, "Event updated.")
        return redirect("event_detail", slug=event.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Event"
        return ctx


class EventDeleteView(LoginRequiredMixin, EventOwnerOrModeratorMixin, DeleteView):
    model = Event
    template_name = "events/event_confirm_delete.html"
    success_url = reverse_lazy("my_events")
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def form_valid(self, form):
        messages.success(self.request, "Event deleted.")
        return super().form_valid(form)
