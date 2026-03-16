from django.contrib.auth.models import UserManager as BaseUserManager


class UserManager(BaseUserManager):
    def create_user(self, username=None, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        return super().create_user(
            username=username, email=email, password=password, **extra_fields
        )

    def create_superuser(
        self, username=None, email=None, password=None, **extra_fields
    ):
        if not email:
            raise ValueError("Email is required.")
        return super().create_superuser(
            username=username, email=email, password=password, **extra_fields
        )
