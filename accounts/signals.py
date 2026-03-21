from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

User = get_user_model()


@receiver(post_save, sender=User)
def notify_admins_on_new_user(sender, instance, created, **kwargs):
    """Send admins a notification email whenever a new user account is created.

    Fires only when created=True so updates don't trigger duplicate emails.
    """
    if not created:
        return

    admin_emails = list(settings.ADMINS)
    if not admin_emails:
        return

    subject = f"New user signup: {instance.display_name or instance.email}"
    message = (
        f"A new user has signed up on pleskal.\n\n"
        f"Display name: {instance.display_name}\n"
        f"Email:        {instance.email}\n"
        f"Joined:       {instance.date_joined:%Y-%m-%d %H:%M UTC}\n"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.SERVER_EMAIL,
        recipient_list=admin_emails,
        fail_silently=True,
    )
