import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

_django_app = get_wsgi_application()


def application(environ, start_response):
    if environ.get("PATH_INFO") == "/health/":
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]
    return _django_app(environ, start_response)
