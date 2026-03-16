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


class ProfileForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        label="Username",
        help_text="System username — letters, digits and @/./+/-/_ only.",
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
            "bio": "Up to 500 characters. Displayed on your public profile.",
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


# Keep old name as alias so existing imports don't break
PublisherProfileForm = ProfileForm
