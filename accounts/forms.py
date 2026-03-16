from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    intro_message = forms.CharField(
        required=True,
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 4, "maxlength": 500, "class": "form-textarea"}
        ),
        label="Tell us about yourself",
        help_text=(
            "Briefly describe who you are and why you want to post events "
            "(up to 500 characters). A moderator will review your account."
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2", "intro_message")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-input")


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-input")


class PublisherProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("bio", "website")
        widgets = {
            "bio": forms.Textarea(
                attrs={"rows": 4, "maxlength": 500, "class": "form-textarea"}
            ),
            "website": forms.URLInput(
                attrs={"placeholder": "https://", "class": "form-input"}
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
