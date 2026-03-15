from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from .models import Event, EventCategory, EventStatus

User = get_user_model()

MODERATION_PER_PAGE = 30


class ModeratorRequiredMixin(LoginRequiredMixin):
    """Restrict access to moderators only."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_moderator:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class ModerationDashboardView(ModeratorRequiredMixin, View):
    def get(self, request):
        pending_events = (
            Event.objects.filter(status=EventStatus.PENDING)
            .select_related("submitted_by")
            .order_by("created_at")
        )
        pending_users = User.objects.filter(is_approved=False, is_active=True).order_by(
            "date_joined"
        )

        stats = {
            "pending_events": pending_events.count(),
            "pending_users": pending_users.count(),
            "approved_today": Event.objects.filter(
                status=EventStatus.APPROVED,
                updated_at__date=timezone.now().date(),
            ).count(),
        }

        return render(
            request,
            "events/moderation/dashboard.html",
            {
                "pending_events": pending_events[:10],
                "pending_users": pending_users[:10],
                "stats": stats,
                "active_tab": "dashboard",
            },
        )


# ---------------------------------------------------------------------------
# Event moderation actions (HTMX)
# ---------------------------------------------------------------------------


class ModerationEventApproveView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        event.approve()
        if request.headers.get("HX-Request"):
            return render(
                request,
                "events/moderation/partials/event_row.html",
                {"event": event},
            )
        messages.success(request, f'"{event.title}" approved.')
        return redirect("moderation_dashboard")


class ModerationEventRejectView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        note = request.POST.get("rejection_note", "").strip()
        if not note:
            if request.headers.get("HX-Request"):
                return HttpResponse(
                    '<p class="text-red-600 text-xs mt-1">Rejection reason is required.</p>',
                    status=422,
                )
            messages.error(request, "Rejection reason is required.")
            return redirect("moderation_dashboard")
        event.reject(note)
        if request.headers.get("HX-Request"):
            return render(
                request,
                "events/moderation/partials/event_row.html",
                {"event": event},
            )
        messages.success(request, f'"{event.title}" rejected.')
        return redirect("moderation_dashboard")


class ModerationEventDeleteView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        title = event.title
        event.delete()
        if request.headers.get("HX-Request"):
            return HttpResponse("")
        messages.success(request, f'"{title}" deleted.')
        return redirect("moderation_dashboard")


# ---------------------------------------------------------------------------
# Event list (all statuses, filtered)
# ---------------------------------------------------------------------------


class ModerationEventListView(ModeratorRequiredMixin, View):
    def get(self, request):
        qs = Event.objects.select_related("submitted_by").order_by("-created_at")

        # Status filter
        status = request.GET.get("status", "")
        if status in {s.value for s in EventStatus}:
            qs = qs.filter(status=status)

        # Category filter
        category = request.GET.get("category", "")
        if category in {c.value for c in EventCategory}:
            qs = qs.filter(category=category)

        # Search
        search = request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(venue_name__icontains=search)
                | Q(submitted_by__username__icontains=search)
            )

        paginator = Paginator(qs, MODERATION_PER_PAGE)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        ctx = {
            "page_obj": page_obj,
            "events": page_obj.object_list,
            "status_choices": EventStatus.choices,
            "category_choices": EventCategory.choices,
            "selected_status": status,
            "selected_category": category,
            "search_query": search,
            "active_tab": "events",
        }

        if request.headers.get("HX-Request"):
            return render(
                request,
                "events/moderation/partials/event_list_results.html",
                ctx,
            )
        return render(request, "events/moderation/event_list.html", ctx)


# ---------------------------------------------------------------------------
# Moderation history
# ---------------------------------------------------------------------------


class ModerationHistoryView(ModeratorRequiredMixin, View):
    def get(self, request):
        qs = (
            Event.objects.filter(
                status__in=[EventStatus.APPROVED, EventStatus.REJECTED]
            )
            .select_related("submitted_by")
            .order_by("-updated_at")
        )

        status = request.GET.get("status", "")
        if status in {EventStatus.APPROVED, EventStatus.REJECTED}:
            qs = qs.filter(status=status)

        paginator = Paginator(qs, MODERATION_PER_PAGE)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        ctx = {
            "page_obj": page_obj,
            "events": page_obj.object_list,
            "selected_status": status,
            "active_tab": "history",
        }

        if request.headers.get("HX-Request"):
            return render(
                request,
                "events/moderation/partials/history_results.html",
                ctx,
            )
        return render(request, "events/moderation/history.html", ctx)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


class ModerationUserListView(ModeratorRequiredMixin, View):
    def get(self, request):
        qs = User.objects.annotate(event_count=Count("events")).order_by("-date_joined")

        # Filter
        filter_type = request.GET.get("filter", "")
        if filter_type == "pending":
            qs = qs.filter(is_approved=False, is_active=True)
        elif filter_type == "approved":
            qs = qs.filter(is_approved=True)
        elif filter_type == "moderators":
            qs = qs.filter(is_moderator=True)

        # Search
        search = request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(Q(username__icontains=search) | Q(email__icontains=search))

        paginator = Paginator(qs, MODERATION_PER_PAGE)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        ctx = {
            "page_obj": page_obj,
            "users": page_obj.object_list,
            "selected_filter": filter_type,
            "search_query": search,
            "active_tab": "users",
        }

        if request.headers.get("HX-Request"):
            return render(
                request,
                "events/moderation/partials/user_list_results.html",
                ctx,
            )
        return render(request, "events/moderation/user_list.html", ctx)


class ModerationUserApproveView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        user.is_approved = True
        user.save(update_fields=["is_approved"])
        if request.headers.get("HX-Request"):
            user.event_count = user.events.count()
            return render(
                request,
                "events/moderation/partials/user_row.html",
                {"u": user},
            )
        messages.success(request, f'"{user.username}" approved.')
        return redirect("moderation_users")


class ModerationUserRevokeView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        user.is_approved = False
        user.save(update_fields=["is_approved"])
        if request.headers.get("HX-Request"):
            user.event_count = user.events.count()
            return render(
                request,
                "events/moderation/partials/user_row.html",
                {"u": user},
            )
        messages.success(request, f'"{user.username}" approval revoked.')
        return redirect("moderation_users")


class ModerationUserToggleModeratorView(ModeratorRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            if request.headers.get("HX-Request"):
                return HttpResponse(
                    '<p class="text-red-600 text-xs">Cannot change your own moderator status.</p>',
                    status=422,
                )
            messages.error(request, "Cannot change your own moderator status.")
            return redirect("moderation_users")
        user.is_moderator = not user.is_moderator
        if user.is_moderator:
            user.is_approved = True
        user.save(update_fields=["is_moderator", "is_approved"])
        if request.headers.get("HX-Request"):
            user.event_count = user.events.count()
            return render(
                request,
                "events/moderation/partials/user_row.html",
                {"u": user},
            )
        action = (
            "promoted to moderator" if user.is_moderator else "demoted from moderator"
        )
        messages.success(request, f'"{user.username}" {action}.')
        return redirect("moderation_users")
