from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView

from .forms import CustomUserCreationForm, PublisherProfileForm

User = get_user_model()


class RegisterView(CreateView):
    form_class = CustomUserCreationForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            "Account created. Please log in.",
        )
        return response

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("/")
        return super().dispatch(request, *args, **kwargs)


class AccountDeleteView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "accounts/account_delete_confirm.html")

    def post(self, request):
        user = request.user
        # Anonymize events (SET_NULL happens via FK, but let's be explicit)
        user.events.update(submitted_by=None)
        logout(request)
        user.delete()
        messages.success(request, "Your account has been deleted.")
        return redirect("/")


class AccountProfileView(LoginRequiredMixin, View):
    def get(self, request):
        form = PublisherProfileForm(instance=request.user)
        return render(request, "accounts/account_profile.html", {"form": form})

    def post(self, request):
        form = PublisherProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("account_profile")
        return render(request, "accounts/account_profile.html", {"form": form})


class PublisherProfileView(View):
    def get(self, request, username):
        from events.models import Event, EventStatus

        publisher = get_object_or_404(User, username=username)
        qs = Event.objects.filter(
            submitted_by=publisher, status=EventStatus.APPROVED
        ).select_related("submitted_by")

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
            },
        )
