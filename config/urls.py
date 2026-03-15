from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("markdownx/", include("markdownx.urls")),
    path(
        "privacy/",
        TemplateView.as_view(template_name="pages/privacy.html"),
        name="privacy",
    ),
    path("moderation/", include("events.moderation_urls")),
    path("", include("events.urls")),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass
