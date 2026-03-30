import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from config.ratelimit import RateLimitMixin

from .forms import (
    ClaimCodeForm,
    ClaimRegisterForm,
    CustomAuthenticationForm,
    ProfileForm,
)
from .models import ClaimCode, generate_claim_code

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
        return redirect("publisher_profile", slug=request.user.display_name_slug)


class EditProfileView(LoginRequiredMixin, View):
    def get(self, request):
        form = ProfileForm(instance=request.user)
        return render(request, "accounts/account_profile.html", {"form": form})

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("publisher_profile", slug=request.user.display_name_slug)
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
            return redirect("publisher_profile", slug=request.user.display_name_slug)
        return render(request, "accounts/change_password.html", {"form": form})


class RateLimitedLoginView(RateLimitMixin, auth_views.LoginView):
    rate_limit_key = "login"
    rate_limit_limit = 20
    rate_limit_window = 3600

    template_name = "accounts/login.html"
    authentication_form = CustomAuthenticationForm

    def form_valid(self, form):
        from allauth.account.models import EmailAddress

        user = form.get_user()
        # Block login if the user has an unverified EmailAddress record.
        # Users without an EmailAddress record (e.g. created via management
        # commands or before allauth was added) are allowed through.
        if EmailAddress.objects.filter(user=user, verified=False).exists():
            messages.error(
                self.request,
                "Please verify your email address before logging in. "
                "Check your inbox for the verification link.",
            )
            return self.form_invalid(form)
        return super().form_valid(form)


class RateLimitedPasswordResetView(RateLimitMixin, auth_views.PasswordResetView):
    rate_limit_key = "password_reset"
    rate_limit_limit = 5
    rate_limit_window = 3600

    template_name = "accounts/password_reset.html"
    success_url = "/accounts/password-reset/done/"


class PublisherProfileView(View):
    def get(self, request, slug):
        from events.models import Event

        publisher = get_object_or_404(User, display_name_slug=slug)
        is_own_profile = request.user.is_authenticated and request.user == publisher

        # Base queryset: published events only (drafts shown separately for own profile)
        qs = Event.objects.filter(
            submitted_by=publisher, is_draft=False
        ).select_related("submitted_by")

        show_past = request.GET.get("past") == "1"
        now = timezone.now()
        if show_past:
            qs = qs.filter(start_datetime__lt=now).order_by("-start_datetime")
        else:
            qs = qs.filter(start_datetime__gte=now).order_by("start_datetime")

        drafts = None
        if is_own_profile:
            drafts = (
                Event.objects.filter(submitted_by=publisher, is_draft=True)
                .select_related("submitted_by")
                .order_by("start_datetime")
            )

        return render(
            request,
            "accounts/publisher_profile.html",
            {
                "publisher": publisher,
                "events": qs,
                "show_past": show_past,
                "is_own_profile": is_own_profile,
                "drafts": drafts,
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
        invalid_msg = "Invalid or expired code."
        try:
            claim_code = ClaimCode.objects.get(code__iexact=code_value)
        except ClaimCode.DoesNotExist:
            logger.warning(
                "Invalid claim code attempt: %s from %s",
                code_value,
                request.META.get("REMOTE_ADDR"),
            )
            form.add_error("code", invalid_msg)
            return render(request, "accounts/claim.html", {"form": form})

        if claim_code.is_claimed or claim_code.is_expired:
            form.add_error("code", invalid_msg)
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
                    display_name=form.cleaned_data["display_name"],
                )

                claim_code.claimed_by = user
                claim_code.claimed_at = timezone.now()
                claim_code.save(update_fields=["claimed_by", "claimed_at"])
        except Exception:
            logger.exception("Error during claim registration")
            messages.error(request, "Something went wrong. Please try again.")
            return redirect("claim")

        request.session.pop("claim_code", None)

        # Trigger allauth email verification before allowing login.
        from allauth.account.models import EmailAddress

        email_address = EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=False,
        )
        email_address.send_confirmation(request)

        messages.info(
            request,
            "Account created! Please check your email and click the verification "
            "link before logging in.",
        )
        return redirect("login")


class MyInvitesView(LoginRequiredMixin, View):
    def _get_filter_and_codes(self, request):
        now = timezone.now()
        active_filter = request.GET.get("filter", "all")
        qs = ClaimCode.objects.filter(created_by=request.user).order_by("-created_at")

        if active_filter == "active":
            qs = qs.filter(claimed_at__isnull=True, expires_at__gt=now)
        elif active_filter == "claimed":
            qs = qs.filter(claimed_at__isnull=False)
        else:
            # Hide expired, unclaimed codes from all view
            qs = qs.exclude(claimed_at__isnull=True, expires_at__lte=now)

        return active_filter, qs

    def _can_generate(self, user):
        now = timezone.now()
        return not ClaimCode.objects.filter(
            created_by=user,
            created_at__year=now.year,
            created_at__month=now.month,
        ).exists()

    def get(self, request):
        active_filter, codes = self._get_filter_and_codes(request)
        context = {
            "codes": codes,
            "active_filter": active_filter,
            "can_generate": self._can_generate(request.user),
            "batch_size": settings.CLAIM_CODES_PER_BATCH,
            "expiry_days": settings.CLAIM_CODE_EXPIRY_DAYS,
        }

        if request.headers.get("HX-Request"):
            return render(
                request, "accounts/partials/invite_list_results.html", context
            )
        return render(request, "accounts/my_invites.html", context)

    def post(self, request):
        if not self._can_generate(request.user):
            messages.warning(
                request,
                "You have already generated invite codes this month. "
                "Your allowance resets on the 1st of next month.",
            )
            return redirect("my_invites")

        batch_size = settings.CLAIM_CODES_PER_BATCH
        expires_at = timezone.now() + timedelta(days=settings.CLAIM_CODE_EXPIRY_DAYS)

        codes = []
        max_retries = batch_size * 10
        attempts = 0
        while len(codes) < batch_size and attempts < max_retries:
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

        messages.success(request, f"Generated {len(codes)} invite codes.")
        return redirect("my_invites")
