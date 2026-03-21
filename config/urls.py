from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts.views import ClaimCodeView, ClaimRegisterView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Claim flow at top-level /claim/
    path("claim/", ClaimCodeView.as_view(), name="claim"),
    path("claim/register/", ClaimRegisterView.as_view(), name="claim_register"),
    # Custom views take priority (login, logout, password-reset have rate limiting).
    path("accounts/", include("accounts.urls")),
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
