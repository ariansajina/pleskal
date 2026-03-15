from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email")


_INPUT_CLASSES = "w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"


class PublisherProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("bio", "website")
        widgets = {
            "bio": forms.Textarea(
                attrs={"rows": 4, "maxlength": 500, "class": _INPUT_CLASSES}
            ),
            "website": forms.URLInput(
                attrs={"placeholder": "https://", "class": _INPUT_CLASSES}
            ),
        }
        labels = {
            "bio": "Short bio",
            "website": "Website",
        }
        help_texts = {
            "bio": "Up to 500 characters. Displayed on your public profile.",
            "website": "Optional link displayed on your public profile.",
        }
