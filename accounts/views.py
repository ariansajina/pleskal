import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from config.ratelimit import RateLimitMixin

from .forms import (
    ClaimCodeForm,
    ClaimRegisterForm,
    CustomAuthenticationForm,
    EmailHashPasswordResetForm,
    ProfileForm,
)
from .models import ClaimCode

User = get_user_model()
logger = logging.getLogger(__name__)


class AccountDeleteView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "accounts/account_delete_confirm.html")

    def post(self, request):
        user = request.user
        if request.POST.get("delete_posts"):
            user.events.all().delete()
        else:
            user.events.update(submitted_by=None)
        logout(request)
        user.delete()
        messages.success(request, "Your account has been deleted.")
        return redirect("/")


class AccountProfileView(LoginRequiredMixin, View):
    """Redirects to the user's public profile page."""

    def get(self, request):
        return redirect("publisher_profile", pk=request.user.pk)


class EditProfileView(LoginRequiredMixin, View):
    def get(self, request):
        form = ProfileForm(instance=request.user)
        return render(request, "accounts/account_profile.html", {"form": form})

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("publisher_profile", pk=request.user.pk)
        return render(request, "accounts/account_profile.html", {"form": form})


def _styled_password_change_form(user, data=None):
    form = PasswordChangeForm(user=user, data=data)
    for field in form.fields.values():
        field.widget.attrs.setdefault("class", "form-input")
    return form


class ChangePasswordView(LoginRequiredMixin, View):
    def get(self, request):
        form = _styled_password_change_form(request.user)
        return render(request, "accounts/change_password.html", {"form": form})

    def post(self, request):
        form = _styled_password_change_form(request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Password changed successfully.")
            return redirect("publisher_profile", pk=request.user.pk)
        return render(request, "accounts/change_password.html", {"form": form})


class RateLimitedLoginView(RateLimitMixin, auth_views.LoginView):
    rate_limit_key = "login"
    rate_limit_limit = 20
    rate_limit_window = 3600

    template_name = "accounts/login.html"
    authentication_form = CustomAuthenticationForm


class RateLimitedPasswordResetView(RateLimitMixin, auth_views.PasswordResetView):
    rate_limit_key = "password_reset"
    rate_limit_limit = 5
    rate_limit_window = 3600

    template_name = "accounts/password_reset.html"
    success_url = "/accounts/password-reset/done/"
    form_class = EmailHashPasswordResetForm


class PublisherProfileView(View):
    def get(self, request, pk):
        from events.models import Event

        publisher = get_object_or_404(User, pk=pk)
        is_own_profile = request.user.is_authenticated and request.user == publisher

        qs = Event.objects.filter(submitted_by=publisher).select_related("submitted_by")

        show_past = request.GET.get("past") == "1"
        now = timezone.now()
        if show_past:
            qs = qs.filter(start_datetime__lt=now).order_by("-start_datetime")
        else:
            qs = qs.filter(start_datetime__gte=now).order_by("start_datetime")

        return render(
            request,
            "accounts/publisher_profile.html",
            {
                "publisher": publisher,
                "events": qs,
                "show_past": show_past,
                "is_own_profile": is_own_profile,
            },
        )


class ClaimCodeView(RateLimitMixin, View):
    rate_limit_key = "claim"
    rate_limit_limit = 5
    rate_limit_window = 3600

    def get(self, request):
        form = ClaimCodeForm()
        return render(request, "accounts/claim.html", {"form": form})

    def post(self, request):
        form = ClaimCodeForm(request.POST)
        if not form.is_valid():
            return render(request, "accounts/claim.html", {"form": form})

        code_value = form.cleaned_data["code"]
        try:
            claim_code = ClaimCode.objects.get(code__iexact=code_value)
        except ClaimCode.DoesNotExist:
            logger.warning(
                "Invalid claim code attempt: %s from %s",
                code_value,
                request.META.get("REMOTE_ADDR"),
            )
            form.add_error("code", "Invalid code.")
            return render(request, "accounts/claim.html", {"form": form})

        if claim_code.is_claimed:
            form.add_error("code", "This code has already been used.")
            return render(request, "accounts/claim.html", {"form": form})

        if claim_code.is_expired:
            form.add_error("code", "This code has expired.")
            return render(request, "accounts/claim.html", {"form": form})

        request.session["claim_code"] = claim_code.code
        return redirect("claim_register")


class ClaimRegisterView(View):
    def dispatch(self, request, *args, **kwargs):
        code_value = request.session.get("claim_code")
        if not code_value:
            return redirect("claim")
        try:
            self.claim_code = ClaimCode.objects.get(code=code_value)
        except ClaimCode.DoesNotExist:
            request.session.pop("claim_code", None)
            messages.error(request, "Invalid claim code. Please try again.")
            return redirect("claim")
        if not self.claim_code.is_valid:
            request.session.pop("claim_code", None)
            messages.error(request, "This code is no longer valid. Please try again.")
            return redirect("claim")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = ClaimRegisterForm()
        return render(request, "accounts/register.html", {"form": form})

    def post(self, request):
        form = ClaimRegisterForm(request.POST)
        if not form.is_valid():
            return render(request, "accounts/register.html", {"form": form})

        # Re-check code validity inside a transaction to prevent races
        try:
            with transaction.atomic():
                claim_code = ClaimCode.objects.select_for_update().get(
                    pk=self.claim_code.pk
                )
                if not claim_code.is_valid:
                    request.session.pop("claim_code", None)
                    messages.error(
                        request, "This code is no longer valid. Please try again."
                    )
                    return redirect("claim")

                user = User.objects.create_user(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password1"],
                )
                user.display_name = form.cleaned_data["display_name"]
                user.save(update_fields=["display_name"])

                claim_code.claimed_by = user
                claim_code.claimed_at = timezone.now()
                claim_code.save(update_fields=["claimed_by", "claimed_at"])
        except Exception:
            logger.exception("Error during claim registration")
            messages.error(request, "Something went wrong. Please try again.")
            return redirect("claim")

        request.session.pop("claim_code", None)
        login(request, user, backend="accounts.backends.EmailBackend")
        messages.success(request, "Welcome! Your account has been created.")
        return redirect("/")
