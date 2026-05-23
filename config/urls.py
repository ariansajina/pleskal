from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import include, path
from django.views.decorators.cache import cache_control

from accounts.views import ClaimCodeView, ClaimRegisterView
from config.pwa import manifest_view, offline_view, service_worker_view
from events.sitemaps import sitemaps


def health(request):
    return HttpResponse("ok")


@cache_control(max_age=86400)
def robots_txt(request):
    sitemap_url = request.build_absolute_uri("/sitemap.xml")
    # Publisher profiles (/accounts/publishers/) are public and indexable, so the
    # /accounts/ rules below target only the private/auth paths.
    lines = [
        "User-agent: *",
        "Disallow: /accounts/login/",
        "Disallow: /accounts/logout/",
        "Disallow: /accounts/password-reset/",
        "Disallow: /accounts/change-password/",
        "Disallow: /accounts/delete/",
        "Disallow: /accounts/profile/",
        "Disallow: /accounts/invites/",
        "Disallow: /accounts/email-verified/",
        "Disallow: /admin/",
        "Disallow: /claim/",
        "Disallow: /markdownx/",
        "Disallow: /events/submit/",
        "",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    path("health/", health, name="health"),
    # PWA: manifest + service worker must be served from the origin root so
    # the SW scope covers the whole site.
    path("manifest.webmanifest", manifest_view, name="pwa_manifest"),
    path("service-worker.js", service_worker_view, name="pwa_service_worker"),
    path("offline/", offline_view, name="pwa_offline"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("admin/", admin.site.urls),
    # Claim flow at top-level /claim/
    path("claim/", ClaimCodeView.as_view(), name="claim"),
    path("claim/register/", ClaimRegisterView.as_view(), name="claim_register"),
    # Custom views take priority (login, logout, password-reset have rate limiting).
    path("accounts/", include("accounts.urls")),
    # allauth provides email confirmation views (/accounts/confirm-email/<key>/).
    # Our custom views above shadow allauth's login/logout/signup routes.
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
