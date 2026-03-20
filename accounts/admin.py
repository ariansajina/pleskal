from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "date_joined",
    )
    list_filter = ("is_staff", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Profile",
            {"fields": ("display_name", "bio", "website", "intro_message")},
        ),
    )
    readonly_fields = ("intro_message",)
