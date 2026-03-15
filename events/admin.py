from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import Event, EventStatus


class RejectionNoteForm(forms.Form):
    rejection_note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Rejection reason",
        help_text="Required. Explain why the event is being rejected.",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "submitted_by",
        "category",
        "status",
        "start_datetime",
        "created_at",
    )
    list_filter = ("status", "category", "is_free", "created_at")
    search_fields = ("title", "venue_name")
    readonly_fields = ("slug", "created_at", "updated_at", "rejection_note")
    ordering = ("created_at",)
    actions = ["approve_events", "reject_events"]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "reject-intermediate/",
                self.admin_site.admin_view(self.reject_intermediate_view),
                name="events_event_reject_intermediate",
            ),
        ]
        return custom + urls

    @admin.action(description="Approve selected events")
    def approve_events(self, request, queryset):
        count = 0
        for event in queryset.select_related("submitted_by"):
            event.approve()
            count += 1
        self.message_user(request, f"{count} event(s) approved.", messages.SUCCESS)

    @admin.action(description="Reject selected events…")
    def reject_events(self, request, queryset):
        selected_ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        request.session["reject_event_ids"] = selected_ids
        return redirect("admin:events_event_reject_intermediate")

    def reject_intermediate_view(self, request):
        event_ids = request.session.get("reject_event_ids", "")
        ids = [eid for eid in event_ids.split(",") if eid]
        queryset = Event.objects.filter(pk__in=ids)

        if request.method == "POST":
            form = RejectionNoteForm(request.POST)
            if form.is_valid():
                note = form.cleaned_data["rejection_note"]
                count = 0
                for event in queryset:
                    event.reject(note)
                    count += 1
                del request.session["reject_event_ids"]
                self.message_user(
                    request, f"{count} event(s) rejected.", messages.SUCCESS
                )
                return redirect("admin:events_event_changelist")
        else:
            form = RejectionNoteForm()

        ctx = {
            **self.admin_site.each_context(request),
            "form": form,
            "events": queryset,
            "title": "Reject events",
            "opts": self.model._meta,
        }
        return render(request, "admin/events/event/reject_intermediate.html", ctx)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        from django.db.models import Case, IntegerField, Value, When

        return qs.annotate(
            status_order=Case(
                When(status=EventStatus.PENDING, then=Value(0)),
                When(status=EventStatus.APPROVED, then=Value(1)),
                When(status=EventStatus.REJECTED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("status_order", "created_at")
