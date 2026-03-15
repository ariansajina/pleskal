from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView

from .forms import CustomUserCreationForm

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
        from django.shortcuts import render

        return render(request, "accounts/account_delete_confirm.html")

    def post(self, request):
        user = request.user
        # Anonymize events (SET_NULL happens via FK, but let's be explicit)
        user.events.update(submitted_by=None)
        logout(request)
        user.delete()
        messages.success(request, "Your account has been deleted.")
        return redirect("/")
