from django.contrib import admin
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
