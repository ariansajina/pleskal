from django.urls import path

from .feeds import EventICalFeed, EventRSSFeed
from .views import (
    EventCreateView,
    EventDeleteView,
    EventDetailView,
    EventDuplicateView,
    EventListView,
    EventUpdateView,
    MyEventsView,
)

urlpatterns = [
    # Homepage / event listing
    path("", EventListView.as_view(), name="event_list"),
    # Event submission
    path("events/submit/", EventCreateView.as_view(), name="event_create"),
    # Event detail
    path("events/<slug:slug>/", EventDetailView.as_view(), name="event_detail"),
    # Event management
    path("events/<slug:slug>/edit/", EventUpdateView.as_view(), name="event_edit"),
    path("events/<slug:slug>/delete/", EventDeleteView.as_view(), name="event_delete"),
    path(
        "events/<slug:slug>/duplicate/",
        EventDuplicateView.as_view(),
        name="event_duplicate",
    ),
    path("my-events/", MyEventsView.as_view(), name="my_events"),
    # Feeds
    path("feed/events.ics", EventICalFeed.as_view(), name="event_ical_feed"),
    path("feed/events.rss", EventRSSFeed(), name="event_rss_feed"),
]
