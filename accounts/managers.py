from django.contrib.auth.base_user import BaseUserManager
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)

    def publishers(self):
        """Users listed in the publisher directory and sitemap.

        Named, active accounts that are either a scraper source or have
        published at least one event. Accounts without a display name are left
        out: their page would read "Anonymous" and their slug comes from their
        email address.
        """
        from events.models import Event

        published = Event.objects.filter(submitted_by=OuterRef("pk"), is_draft=False)
        return (
            self.filter(is_active=True)
            .exclude(display_name="")
            .filter(Q(is_system_account=True) | Exists(published))
            .order_by(Lower("display_name"), "pk")
        )
