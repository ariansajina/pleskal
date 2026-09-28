from django.contrib.auth import get_user_model
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Event


class EventSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7

    def items(self):
        # Only the URL and lastmod are rendered; skip the description columns.
        return (
            Event.objects.filter(is_draft=False)
            .only("slug", "updated_at")
            .order_by("-start_datetime", "-id")
        )

    def lastmod(self, obj):
        return obj.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.5

    def items(self):
        return ["event_list", "publisher_list", "subscribe", "about", "guide"]

    def location(self, item):
        return reverse(item)


class PublisherSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.4

    def items(self):
        return get_user_model().objects.publishers()

    def location(self, item):
        return reverse("publisher_profile", kwargs={"slug": item.display_name_slug})


sitemaps = {
    "events": EventSitemap,
    "publishers": PublisherSitemap,
    "static": StaticViewSitemap,
}
