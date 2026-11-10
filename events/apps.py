from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "events"

    def ready(self):
        from django.core.checks import register

        import events.signals  # noqa: F401
        from config.checks import check_media_domain

        register(check_media_domain)
