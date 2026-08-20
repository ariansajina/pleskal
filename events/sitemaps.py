from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Event


class EventSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        return Event.objects.filter(is_draft=False).order_by("-start_datetime", "-id")

    def lastmod(self, obj):
        return obj.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.5

    def items(self):
        names = ["event_list", "subscribe", "about", "guide"]
        if getattr(settings, "MAP_VIEW_ENABLED", False):
            names.append("event_map")
        return names

    def location(self, item):
        return reverse(item)


class PublisherSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.4

    def items(self):
        user_model = get_user_model()
        return (
            user_model.objects.filter(display_name_slug__gt="", events__is_draft=False)
            .distinct()
            .order_by("display_name_slug")
        )

    def location(self, item):
        return reverse("publisher_profile", kwargs={"slug": item.display_name_slug})


sitemaps = {
    "events": EventSitemap,
    "publishers": PublisherSitemap,
    "static": StaticViewSitemap,
}
