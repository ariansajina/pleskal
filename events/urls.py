from django.urls import path
from django.views.generic import TemplateView

# Stub views — will be replaced by real views in subsequent features
urlpatterns = [
    path(
        "events/submit/",
        TemplateView.as_view(template_name="base.html"),
        name="event_create",
    ),
    path(
        "my-events/",
        TemplateView.as_view(template_name="base.html"),
        name="my_events",
    ),
    path(
        "feed/events.ics",
        TemplateView.as_view(template_name="base.html"),
        name="event_ical_feed",
    ),
    path(
        "feed/events.rss",
        TemplateView.as_view(template_name="base.html"),
        name="event_rss_feed",
    ),
    path(
        "privacy/",
        TemplateView.as_view(template_name="base.html"),
        name="privacy",
    ),
]
