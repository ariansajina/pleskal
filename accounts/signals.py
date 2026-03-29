import logging

from allauth.account.signals import email_confirmed
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

User = get_user_model()


@receiver(email_confirmed)
def add_to_resend_contacts(sender, request, email_address, **kwargs):
    """Add verified user to Resend contact list when they confirm their email."""
    api_key = getattr(settings, "RESEND_API_KEY", None)

    user = email_address.user
    if user.is_system_account:
        return

    try:
        import resend

        resend.api_key = api_key
        display_name = user.display_name or ""
        first_name, _, last_name = display_name.partition(" ")
        params: resend.Contacts.CreateParams = {
            "email": email_address.email,
            "first_name": first_name or "",
            "last_name": last_name or "",
            "unsubscribed": False,
        }
        resend.Contacts.create(params)
        segment_id = getattr(settings, "RESEND_SEGMENT_ID", None)
        if segment_id:
            resend.Contacts.Segments.add(
                {
                    "email": email_address.email,
                    "segment_id": segment_id,
                }
            )
    except Exception:
        logger.exception("Failed to add %s to Resend contacts", email_address.email)


@receiver(post_save, sender=User)
def notify_admins_on_new_user(sender, instance, created, **kwargs):
    """Send admins a notification email whenever a new user account is created.

    Fires only when created=True so updates don't trigger duplicate emails.
    """
    if not created or settings.DEBUG or instance.is_system_account:
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
