from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Custom views take priority (login, logout, password-reset have rate limiting).
    path("accounts/", include("accounts.urls")),
    # allauth provides signup and email-confirmation; its login/logout/password-reset
    # are shadowed by the custom views above.
    path("accounts/", include("allauth.urls")),
    path("markdownx/", include("markdownx.urls")),
    path("", include("events.urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass
