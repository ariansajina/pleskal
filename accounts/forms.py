from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm

User = get_user_model()


class EmailHashPasswordResetForm(PasswordResetForm):
    """Password reset form that looks up users via the HMAC email_hash blind
    index rather than filtering on the encrypted email column directly."""

    def get_users(self, email):
        from .crypto import hash_email

        email_hash = hash_email(email)
        return User._default_manager.filter(
            email_hash=email_hash,
            is_active=True,
        )


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Username")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-input")


class ProfileForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        label="Username",
        help_text="System username — letters, digits and @/./+/-/_ only (no whitespace).",
    )

    class Meta:
        model = User
        fields = ("username", "display_name", "email", "bio", "website")
        widgets = {
            "display_name": forms.TextInput(
                attrs={"class": "form-input", "maxlength": 100}
            ),
            "bio": forms.Textarea(
                attrs={"rows": 4, "maxlength": 500, "class": "form-textarea"}
            ),
            "website": forms.URLInput(
                attrs={"placeholder": "https://", "class": "form-input"}
            ),
            "email": forms.EmailInput(attrs={"class": "form-input"}),
        }
        labels = {
            "display_name": "Display name",
            "bio": "Short bio",
            "website": "Website",
            "email": "Email address",
        }
        help_texts = {
            "display_name": "Optional. Shown instead of your username on events. Can include spaces and special characters.",
            "bio": "Up to 500 characters. Markdown supported. Displayed on your public profile.",
            "website": "Optional link displayed on your public profile.",
            "email": "Used for password resets.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.setdefault("class", "form-input")
        self.fields["email"].required = False

    def clean_username(self):
        username = self.cleaned_data["username"]
        qs = User.objects.filter(username=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        if not email:
            return email
        from .crypto import hash_email

        email_hash = hash_email(email)
        qs = User.objects.filter(email_hash=email_hash)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This email address is already in use.")
        return email


# Keep old name as alias so existing imports don't break
PublisherProfileForm = ProfileForm
