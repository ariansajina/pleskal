from django.contrib import admin

from .models import Event


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
    list_filter = ("status", "category", "is_free")
    search_fields = ("title", "venue_name")
    readonly_fields = ("slug", "created_at", "updated_at")
