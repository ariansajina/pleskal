from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Authenticate with email + password."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        User = get_user_model()
        try:
            user = User.objects.get_by_email(username)
        except User.DoesNotExist:
            # Run the default password hasher to mitigate timing attacks.
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
