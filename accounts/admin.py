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
        (
            "Moderation",
            {"fields": ("is_approved", "is_moderator", "intro_message")},
        ),
    )
    readonly_fields = ("intro_message",)
    actions = ["approve_users", "promote_to_moderator"]

    @admin.action(description="Approve selected users")
    def approve_users(self, request, queryset):
        count = queryset.filter(is_approved=False).update(is_approved=True)
        self.message_user(request, f"{count} user(s) approved.", messages.SUCCESS)

    @admin.action(description="Promote selected users to moderator")
    def promote_to_moderator(self, request, queryset):
        count = queryset.update(is_moderator=True)
        self.message_user(
            request, f"{count} user(s) promoted to moderator.", messages.SUCCESS
        )
