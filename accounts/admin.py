from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "is_approved",
        "is_moderator",
        "date_joined",
    )
    list_filter = ("is_approved", "is_moderator", "is_staff", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Moderation", {"fields": ("is_approved", "is_moderator")}),
    )
    actions = ["promote_to_moderator"]

    @admin.action(description="Promote selected users to moderator")
    def promote_to_moderator(self, request, queryset):
        count = queryset.update(is_moderator=True)
        self.message_user(
            request, f"{count} user(s) promoted to moderator.", messages.SUCCESS
        )
