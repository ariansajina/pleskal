from django.contrib import messages
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from config.ratelimit import RateLimitMixin

from .forms import (
    CustomAuthenticationForm,
    EmailHashPasswordResetForm,
    ProfileForm,
)

User = get_user_model()


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
        return redirect("publisher_profile", username=request.user.username)


class EditProfileView(LoginRequiredMixin, View):
    def get(self, request):
        form = ProfileForm(instance=request.user)
        return render(request, "accounts/account_profile.html", {"form": form})

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("publisher_profile", username=request.user.username)
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
            return redirect("publisher_profile", username=request.user.username)
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
    def get(self, request, username):
        from events.models import Event

        publisher = get_object_or_404(User, username=username)
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
