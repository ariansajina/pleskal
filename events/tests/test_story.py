import datetime
import io

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.tests.factories import UserFactory
from events.models import EventCategory
from events.story import (
    BADGES,
    STORY_SIZE,
    clamp,
    date_parts,
    font,
    render_card,
    render_story,
)
from events.tests.factories import EventFactory


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _local(*args):
    return timezone.make_aware(datetime.datetime(*args))


def _url(event):
    return reverse("event_story_image", kwargs={"slug": event.slug})


@pytest.mark.django_db
class TestStoryImageView:
    def test_returns_story_sized_jpeg(self, client):
        event = EventFactory.create()
        response = client.get(_url(event))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        image = Image.open(io.BytesIO(response.content))
        assert image.format == "JPEG"
        assert image.size == STORY_SIZE

    def test_is_cacheable(self, client):
        response = client.get(_url(EventFactory.create()))
        assert "public" in response["Cache-Control"]

    def test_unknown_event_is_404(self, client):
        response = client.get(
            reverse("event_story_image", kwargs={"slug": "no-such-event"})
        )
        assert response.status_code == 404

    def test_draft_is_hidden_from_others(self, client):
        event = EventFactory.create(is_draft=True)
        client.force_login(UserFactory.create())
        assert client.get(_url(event)).status_code == 404

    def test_draft_is_hidden_from_anonymous(self, client):
        event = EventFactory.create(is_draft=True)
        assert client.get(_url(event)).status_code == 404

    def test_draft_is_shown_to_owner(self, client):
        event = EventFactory.create(is_draft=True)
        client.force_login(event.submitted_by)
        assert client.get(_url(event)).status_code == 200

    def test_is_rate_limited(self, client, monkeypatch):
        from events.views import EventStoryImageView

        monkeypatch.setattr(EventStoryImageView, "rate_limit_limit", 1)
        event = EventFactory.create()
        assert client.get(_url(event)).status_code == 200
        assert client.get(_url(event)).status_code == 429

    def test_detail_page_links_to_story_image(self, client):
        event = EventFactory.create()
        response = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert f'href="{_url(event)}"' in response.content.decode()


@pytest.mark.django_db
class TestRenderCard:
    def test_uses_event_image(self):
        event = EventFactory.build(submitted_by=UserFactory.create())
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 675), (200, 30, 30)).save(buffer, format="WEBP")
        event.image.name = default_storage.save(
            "events/photo.webp", ContentFile(buffer.getvalue())
        )
        card = render_card(event)
        # The thumbnail fills the card's right-hand column.
        pixel = card.convert("RGB").getpixel((card.width - 40, card.height // 2))
        assert isinstance(pixel, tuple)
        assert all(
            abs(got - want) < 20 for got, want in zip(pixel, (200, 30, 30), strict=True)
        )

    def test_unreadable_image_falls_back_to_default(self):
        event = EventFactory.build(submitted_by=UserFactory.create())
        event.image.name = "events/missing.webp"
        card = render_card(event)
        assert card.size[0] > 0

    def test_long_venue_and_title_keep_card_height_bounded(self):
        short = render_card(EventFactory.build(submitted_by=None))
        long = render_card(
            EventFactory.build(
                title="Very long title " * 20,
                venue_name="Very long venue " * 20,
                submitted_by=None,
            )
        )
        # Title and venue are clamped to two lines each.
        assert long.height < short.height * 2

    def test_every_category_has_a_badge_style(self):
        assert set(EventCategory.values) <= set(BADGES)

    def test_render_story_with_free_workshop(self):
        event = EventFactory.create(is_free=True, category=EventCategory.WORKSHOP)
        assert render_story(event)[:3] == b"\xff\xd8\xff"


class TestClamp:
    def test_short_text_is_one_line(self):
        assert clamp("Dance", font(16), 1000, 2) == ["Dance"]

    def test_wraps_and_ellipsizes(self):
        lines = clamp("word " * 100, font(16), 300, 2)
        assert len(lines) == 2
        assert lines[-1].endswith("…")
        assert all(font(16).getlength(line) <= 300 for line in lines)

    def test_breaks_overlong_word(self):
        lines = clamp("x" * 200, font(16), 300, 3)
        assert len(lines) == 3
        assert all(font(16).getlength(line) <= 300 for line in lines)


class TestDateParts:
    def test_start_and_end_time(self):
        event = EventFactory.build(
            start_datetime=_local(2026, 11, 6, 19, 30),
            end_datetime=_local(2026, 11, 6, 21, 0),
        )
        assert date_parts(event) == ["Fri 6 Nov · 19:30", "–", "21:00"]

    def test_start_only(self):
        event = EventFactory.build(start_datetime=_local(2026, 11, 6, 19, 30))
        assert date_parts(event) == ["Fri 6 Nov · 19:30"]

    def test_ends_on_later_day(self):
        event = EventFactory.build(
            start_datetime=_local(2026, 11, 6, 19, 30),
            end_datetime=_local(2026, 11, 8, 18, 0),
        )
        assert date_parts(event) == ["Fri 6 Nov · 19:30", "–", "Sun 8 Nov · 18:00"]

    def test_all_day(self):
        event = EventFactory.build(
            start_datetime=_local(2026, 11, 6, 0, 0),
            end_datetime=_local(2026, 11, 8, 0, 0),
        )
        assert date_parts(event) == ["Fri 6 Nov", "–", "Sun 8 Nov"]
