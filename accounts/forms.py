from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.html import mark_safe
from markdownx.widgets import MarkdownxWidget

User = get_user_model()


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-input")
        self.fields["username"].widget.attrs.setdefault("autocomplete", "username")


class ProfileForm(forms.ModelForm):
    # Not a model field: changing email requires re-verification (see
    # EditProfileView.post), so it's handled separately from the model save
    # rather than written straight to User.email like the other fields.
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-input"}),
        label="Email address",
        help_text=(
            "Used for password resets. Changing this sends a confirmation "
            "link to the new address; it only takes effect once confirmed."
        ),
    )

    class Meta:
        model = User
        fields = ("display_name", "bio", "website")
        widgets = {
            "display_name": forms.TextInput(
                attrs={"class": "form-input", "maxlength": 100}
            ),
            "bio": MarkdownxWidget(attrs={"rows": 4, "maxlength": 2000}),
            "website": forms.URLInput(
                attrs={"placeholder": "https://", "class": "form-input"}
            ),
        }
        labels = {
            "display_name": "Display name",
            "bio": "Short bio",
            "website": "Website",
        }
        help_texts = {
            "display_name": "Shown next to your submitted events. Can include spaces and special characters.",
            "bio": mark_safe(
                'Up to 2,000 characters. <a href="https://www.markdownguide.org/cheat-sheet/" target="_blank" rel="noopener noreferrer">Markdown</a> supported. Displayed on your public profile.'
            ),
            "website": "Optional link displayed on your public profile.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["email"].initial = self.instance.email

    def clean_bio(self):
        bio = self.cleaned_data.get("bio", "")
        if len(bio) > 2000:
            raise forms.ValidationError(
                f"Bio must be 2,000 characters or fewer (currently {len(bio)})."
            )
        return bio

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        if not email:
            return email
        qs = User.objects.filter(email=email)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    @property
    def email_changed(self) -> bool:
        new_email = self.cleaned_data.get("email", "")
        return bool(new_email) and new_email != self.instance.email


class ClaimCodeForm(forms.Form):
    code = forms.CharField(
        max_length=8,
        label="Claim code",
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "e.g. K7XM4HRN",
                "autocomplete": "off",
                "style": "font-family:monospace;letter-spacing:0.15em;font-size:1.1rem;text-transform:uppercase;",
            }
        ),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class ClaimRegisterForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )
    display_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-input", "autocomplete": "nickname"}
        ),
        help_text="This is what other users see. Can include spaces and special characters.",
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "autocomplete": "new-password"}
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "autocomplete": "new-password"}
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"]
        if len(display_name) < 1:
            raise forms.ValidationError("Display name is required.")
        return display_name

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match.")
        return password2

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        if password1:
            temp_user = User(email=cleaned_data.get("email", ""))
            password_validation.validate_password(password1, user=temp_user)
        return cleaned_data
