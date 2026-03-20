from allauth.account.adapter import DefaultAccountAdapter
from django import forms


class AccountAdapter(DefaultAccountAdapter):
    """Custom allauth adapter that enforces email uniqueness via the HMAC
    blind index (email_hash) rather than a direct plaintext comparison,
    since the email field is now stored encrypted.
    """

    def validate_unique_email(self, email: str) -> str:
        from django.contrib.auth import get_user_model

        from .crypto import hash_email

        User = get_user_model()
        if User.objects.filter(email_hash=hash_email(email)).exists():
            raise forms.ValidationError(
                self.error_messages["email_taken"],
                code="email_taken",
            )
        return email
