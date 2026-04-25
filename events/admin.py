from django.contrib import admin

from .models import Event, EventSeries


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "submitted_by",
        "category",
        "start_datetime",
        "series",
        "created_at",
    )
    list_filter = ("category", "is_free", "created_at")
    search_fields = ("title", "venue_name")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("created_at",)


@admin.register(EventSeries)
class EventSeriesAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "submitted_by",
        "external_source",
        "external_key",
        "created_at",
    )
    list_filter = ("external_source", "created_at")
    search_fields = ("title",)
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("-created_at",)
