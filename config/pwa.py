"""
PWA views: web app manifest and service worker.

Served as Django views (not static files) so the cache-bust token can be
templated in. Both responses set Cache-Control headers appropriate to their
roles:
  - manifest: short cache so installs pick up icon/name changes quickly.
  - service worker: no-cache so browsers always re-fetch and compare byte-for-byte.
    (The browser's own SW update algorithm handles the byte-comparison.)
"""

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string


def offline_view(request):
    content = render_to_string("pwa/offline.html", {}, request=request)
    return HttpResponse(content, content_type="text/html")


def manifest_view(request):
    content = render_to_string("pwa/manifest.webmanifest", {}, request=request)
    response = HttpResponse(content, content_type="application/manifest+json")
    response["Cache-Control"] = "public, max-age=86400"
    return response


def service_worker_view(request):
    context = {"DEPLOY_SHA": settings.DEPLOY_SHA}
    content = render_to_string("pwa/service-worker.js", context, request=request)
    response = HttpResponse(content, content_type="application/javascript")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Service-Worker-Allowed"] = "/"
    return response
