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

    Note: this fires at object-creation time, before the user confirms their
    email address.  If you want the notification to fire only after email
    confirmation, switch to allauth's ``email_confirmed`` signal instead:

        from allauth.account.signals import email_confirmed

        @receiver(email_confirmed)
        def notify_admins_on_email_confirmed(sender, request, email_address, **kwargs):
            ...

    Future: consider allauth passwordless / email-OTP once transactional
    email provider is confirmed (see settings.ANYMAIL).
    """
    if not created:
        return

    admin_emails = list(settings.ADMINS)
    if not admin_emails:
        return

    subject = f"New user signup: {instance.username}"
    message = (
        f"A new user has signed up on pleskal.\n\n"
        f"Username:  {instance.username}\n"
        f"Email:     {instance.email}\n"
        f"Joined:    {instance.date_joined:%Y-%m-%d %H:%M UTC}\n"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.SERVER_EMAIL,
        recipient_list=admin_emails,
        fail_silently=True,
    )
