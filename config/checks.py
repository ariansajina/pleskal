"""Project system checks (registered in events.apps.EventsConfig.ready)."""

from django.conf import settings
from django.core.checks import Warning


def check_media_domain(app_configs, **kwargs):
    """Warn when R2 media would be served from the r2.dev development URL.

    Cloudflare rate-limits ``*.r2.dev`` and never caches it; production media
    needs a custom domain connected to the bucket, set as ``CDN_DOMAIN``.
    """
    if not getattr(settings, "AWS_STORAGE_BUCKET_NAME", None):
        return []  # local filesystem storage
    domain = (getattr(settings, "AWS_S3_CUSTOM_DOMAIN", None) or "").lower()
    if domain and not domain.endswith(".r2.dev"):
        return []
    return [
        Warning(
            "Event images are served from "
            + (domain or "the R2 API endpoint")
            + ", which Cloudflare rate-limits and does not cache.",
            hint=(
                "Connect a custom domain to the R2 bucket and set CDN_DOMAIN "
                "to it (see deployment-notes.md, 'Media domain')."
            ),
            id="pleskal.W001",
        )
    ]
