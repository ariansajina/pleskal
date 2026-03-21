from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    def get_by_email(self, email):
        """Look up a user by email using the HMAC blind index."""
        from .crypto import hash_email

        return self.get(email_hash=hash_email(email))

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        extra_fields.setdefault("is_active", True)
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)
