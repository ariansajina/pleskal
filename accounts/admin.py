from django import forms
from django.contrib import admin, messages
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone

from .models import ClaimCode, User, generate_claim_code


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_active")
    search_fields = ("display_name", "email")
    readonly_fields = ("id", "date_joined", "last_login")
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profile", {"fields": ("display_name", "bio", "website")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )


class GenerateCodesForm(forms.Form):
    count = forms.IntegerField(min_value=1, max_value=100, initial=10)
    expires_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="When these codes expire.",
    )


@admin.register(ClaimCode)
class ClaimCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "created_by",
        "expires_at",
        "is_claimed_icon",
        "claimed_by",
        "claimed_at",
    )
    list_filter = ("claimed_at", "expires_at")
    readonly_fields = ("code", "created_at", "claimed_at", "claimed_by", "created_by")
    search_fields = ("code",)

    @admin.display(boolean=True, description="Claimed")
    def is_claimed_icon(self, obj):
        return obj.is_claimed

    def get_urls(self):
        custom_urls = [
            path(
                "generate/",
                self.admin_site.admin_view(self.generate_codes_view),
                name="accounts_claimcode_generate",
            ),
        ]
        return custom_urls + super().get_urls()

    def generate_codes_view(self, request):
        generated_codes = None
        if request.method == "POST":
            form = GenerateCodesForm(request.POST)
            if form.is_valid():
                count = form.cleaned_data["count"]
                expires_at = form.cleaned_data["expires_at"]
                if timezone.is_naive(expires_at):
                    expires_at = timezone.make_aware(expires_at)

                codes = []
                max_retries = count * 10
                attempts = 0
                while len(codes) < count and attempts < max_retries:
                    attempts += 1
                    code = generate_claim_code()
                    try:
                        ClaimCode.objects.create(
                            code=code,
                            expires_at=expires_at,
                            created_by=request.user,
                        )
                        codes.append(code)
                    except IntegrityError:
                        continue

                request.session["generated_claim_codes"] = codes
                messages.success(request, f"Generated {len(codes)} claim codes.")
                return redirect(reverse("admin:accounts_claimcode_generate"))
        else:
            form = GenerateCodesForm()

        generated_codes = request.session.pop("generated_claim_codes", None)
        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "generated_codes": generated_codes,
            "title": "Generate claim codes",
            "opts": self.model._meta,
        }
        return render(request, "admin/accounts/claimcode/generate.html", context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["generate_url"] = reverse("admin:accounts_claimcode_generate")
        return super().changelist_view(request, extra_context=extra_context)
