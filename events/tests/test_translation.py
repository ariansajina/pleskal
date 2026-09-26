"""Tests for language detection / translation of scraped descriptions.

The real translation model isn't available in CI, so the model call
(``_translate_sentences``) is replaced by a fake that marks each sentence it
was given; language detection runs for real (lingua is a regular dependency).
"""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.urls import reverse

from events import translation
from events.models import Event
from events.tests.factories import EventFactory
from events.translation import DescriptionResult, process_description

DANISH = (
    "Forestillingen undersøger kroppens hukommelse og hvordan vi bevæger os "
    "gennem byen. Billetter kan købes i døren, og der er gratis adgang for "
    "studerende."
)
DANISH_2 = (
    "Efter forestillingen er der en samtale med kunstnerne, og baren er åben "
    "hele aftenen for alle som har lyst til at blive lidt længere."
)
ENGLISH = (
    "The performance explores the memory of the body and how we move through "
    "the city. Tickets can be bought at the door, and students get in free."
)
ENGLISH_2 = (
    "After the show there is a conversation with the artists, and the bar is "
    "open all evening for anyone who would like to stay a little longer."
)

ENGLISH_3 = (
    "The piece was developed in residency over two years and is performed by "
    "three dancers with live music."
)


def fake_translate(sentences: list[str]) -> list[str]:
    return [f"EN<{s}>" for s in sentences]


@pytest.fixture(autouse=True)
def _clear_memo():
    process_description.cache_clear()
    yield
    process_description.cache_clear()


@pytest.fixture
def fake_model():
    with patch.object(
        translation, "_translate_sentences", side_effect=fake_translate
    ) as mock:
        yield mock


@pytest.fixture
def translation_enabled(settings):
    settings.TRANSLATION_ENABLED = True
    return settings


# ── Detection ────────────────────────────────────────────────────────────────


class TestDetectLanguage:
    def test_danish(self):
        assert translation.detect_language(DANISH) == "da"

    def test_english(self):
        assert translation.detect_language(ENGLISH) == "en"

    def test_short_text_is_undetermined(self):
        assert translation.detect_language("Koncert") == ""

    def test_names_do_not_make_english_danish(self):
        text = (
            "After the successes of NOMAD and SUTRA, Sidi Larbi Cherkaoui "
            "returns to København Danser — this time with dancer Marc Brew."
        )
        assert translation.detect_language(text) == "en"

    def test_low_confidence_is_undetermined(self, settings):
        settings.TRANSLATION_MIN_CONFIDENCE = 1.01
        assert translation.detect_language(ENGLISH) == ""

    def test_markdown_is_stripped(self):
        assert translation.detect_language(f"## **{DANISH}**") == "da"


class TestParagraphLanguages:
    def test_heading_takes_following_language(self):
        paragraphs = [DANISH, "## English", ENGLISH]
        assert translation._paragraph_languages(paragraphs) == ["da", "en", "en"]

    def test_other_short_paragraph_takes_preceding_language(self):
        paragraphs = [DANISH, "Varighed ca. 35 min", ENGLISH]
        assert translation._paragraph_languages(paragraphs) == ["da", "da", "en"]

    def test_leading_short_paragraph_falls_back_to_following(self):
        paragraphs = ["*English below*", DANISH]
        assert translation._paragraph_languages(paragraphs) == ["da", "da"]

    def test_all_undetermined(self):
        assert translation._paragraph_languages(["Koncert", "Dans"]) == ["", ""]


# ── Markdown-preserving translation ──────────────────────────────────────────


class TestTranslateMarkdown:
    def test_keeps_block_structure(self, fake_model):
        md = "## Overskrift\n\n* Første punkt\n1. Andet punkt\n> Citat"
        assert translation.translate_markdown(md) == (
            "## EN<Overskrift>\n\n* EN<Første punkt>\n1. EN<Andet punkt>\n> EN<Citat>"
        )

    def test_splits_sentences_into_one_batch(self, fake_model):
        result = translation.translate_markdown("Første sætning. Anden sætning!")
        assert result == "EN<Første sætning.> EN<Anden sætning!>"
        fake_model.assert_called_once_with(["Første sætning.", "Anden sætning!"])

    def test_keeps_links_urls_and_emails(self, fake_model):
        md = (
            "Læs mere på [vores side](https://example.dk/a) eller "
            "https://example.dk/b og skriv til info@example.dk."
        )
        assert translation.translate_markdown(md) == (
            "EN<Læs mere på> [EN<vores side>](https://example.dk/a) EN<eller> "
            "https://example.dk/b EN<og skriv til> info@example.dk."
        )

    def test_keeps_whole_line_emphasis_and_hard_breaks(self, fake_model):
        md = "**Medbring vand**  \nVi ses"
        assert translation.translate_markdown(md) == (
            "**EN<Medbring vand>**  \nEN<Vi ses>"
        )

    def test_drops_inline_emphasis(self, fake_model):
        assert translation.translate_markdown("Kom og **dans** med os") == (
            "EN<Kom og dans med os>"
        )

    def test_keeps_text_without_letters(self, fake_model):
        md = "————\n\n2026"
        assert translation.translate_markdown(md) == md
        fake_model.assert_called_once_with([])


class TestTranslateSentences:
    def test_runs_tokenize_bpe_translate_detokenize(self):
        model = SimpleNamespace(
            tokenizer=SimpleNamespace(tokenize=lambda s, **kw: s.lower()),
            bpe=SimpleNamespace(process_line=lambda s: s.replace("hej", "h@@ ej")),
            translator=SimpleNamespace(
                translate_batch=lambda batch, **kw: [
                    SimpleNamespace(hypotheses=[["hel@@", "lo", "world"]])
                    for _ in batch
                ]
            ),
            detokenizer=SimpleNamespace(detokenize=lambda tokens: "|".join(tokens)),
        )
        with patch.object(translation, "_model", return_value=model):
            assert translation._translate_sentences(["Hej verden"]) == ["hello|world"]

    def test_empty_batch_skips_model(self):
        with patch.object(translation, "_model") as model:
            assert translation._translate_sentences([]) == []
        model.assert_not_called()

    def test_missing_model_raises(self, settings, tmp_path):
        settings.TRANSLATION_MODEL_DIR = str(tmp_path)
        translation._model.cache_clear()
        try:
            with pytest.raises(translation.TranslationUnavailableError):
                translation._translate_sentences(["Hej"])
        finally:
            translation._model.cache_clear()


# ── process_description ──────────────────────────────────────────────────────


class TestProcessDescription:
    def test_english(self, fake_model):
        assert process_description(f"{ENGLISH}\n\n{ENGLISH_2}") == DescriptionResult(
            language="en"
        )
        fake_model.assert_not_called()

    def test_danish_is_translated(self, fake_model):
        result = process_description(f"{DANISH}\n\n{DANISH_2}")
        assert result.language == "da"
        assert result.en_is_machine is True
        assert result.en.startswith("EN<Forestillingen")
        assert "\n\nEN<Efter forestillingen" in result.en
        assert result.da == ""

    def test_short_english_line_in_danish_text_is_kept_verbatim(self, fake_model):
        quote = "The body remembers what the mind forgets, always."
        result = process_description(f"{DANISH}\n\n{DANISH_2}\n\n{quote}")
        assert result.language == "da"
        assert result.en.endswith(f"\n\n{quote}")

    def test_bilingual_is_split(self, fake_model):
        english = f"## English\n\n{ENGLISH}\n\n{ENGLISH_2}\n\n{ENGLISH_3}"
        md = f"{DANISH}\n\n{DANISH_2}\n\n{english}"
        result = process_description(md)
        assert result == DescriptionResult(
            language="mixed", da=f"{DANISH}\n\n{DANISH_2}", en=english
        )
        fake_model.assert_not_called()

    def test_undetermined(self, fake_model):
        assert process_description("Koncert") == DescriptionResult()

    def test_empty(self):
        assert process_description("") == DescriptionResult()

    def test_translation_failure_leaves_unprocessed(self):
        with patch.object(
            translation, "_translate_sentences", side_effect=RuntimeError("boom")
        ):
            assert process_description(DANISH) == DescriptionResult()

    def test_missing_model_leaves_unprocessed(self):
        with patch.object(
            translation,
            "_translate_sentences",
            side_effect=translation.TranslationUnavailableError("no model"),
        ):
            assert process_description(DANISH) == DescriptionResult()

    def test_detection_failure_leaves_unprocessed(self):
        with patch.object(
            translation, "_paragraph_languages", side_effect=RuntimeError("boom")
        ):
            assert process_description(DANISH) == DescriptionResult()

    def test_memoized(self, fake_model):
        process_description(DANISH)
        process_description(DANISH)
        assert fake_model.call_count == 1


# ── Event model ──────────────────────────────────────────────────────────────


class TestEventDescriptionFor:
    def test_unprocessed(self):
        event = Event(description=DANISH)
        assert event.description_for("en") == DANISH
        assert event.description_for("da") == DANISH
        assert not event.is_machine_translated

    def test_english(self):
        event = Event(description=ENGLISH, description_language="en")
        assert event.description_for("en") == ENGLISH
        assert event.description_for("da") == ENGLISH

    def test_danish_translated(self):
        event = Event(
            description=DANISH,
            description_language="da",
            description_en="Translated",
            description_en_is_machine=True,
        )
        assert event.description_for("en") == "Translated"
        assert event.description_for("da") == DANISH
        assert event.is_machine_translated

    def test_danish_without_translation_falls_back(self):
        event = Event(description=DANISH, description_language="da")
        assert event.description_for("en") == DANISH
        assert not event.is_machine_translated

    def test_mixed(self):
        event = Event(
            description="both",
            description_language="mixed",
            description_da="dansk",
            description_en="english",
        )
        assert event.description_for("en") == "english"
        assert event.description_for("da") == "dansk"
        assert not event.is_machine_translated

    def test_display_description_uses_english(self, settings):
        settings.SCRAPED_EVENT_DISCLAIMER = "> Disclaimer"
        event = Event(
            description=DANISH,
            external_source="faar302",
            description_language="da",
            description_en="Translated",
            description_en_is_machine=True,
        )
        assert event.get_display_description() == "> Disclaimer\n\nTranslated"


# ── Importer ─────────────────────────────────────────────────────────────────

RECORD = {
    "source_url": "https://dansehallerne.dk/event/1",
    "start_datetime": "2030-06-01T18:00:00+02:00",
    "title": "Dansk forestilling",
    "description": DANISH,
    "venue_name": "Test Venue",
    "category": "performance",
    "image_url": "",
}


def _import(tmp_path: Path, records: list[dict], **options) -> None:
    f = tmp_path / "events.json"
    f.write_text(json.dumps(records), encoding="utf-8")
    call_command(
        "import_events", "dansehallerne", str(f), stdout=io.StringIO(), **options
    )


@pytest.mark.django_db
class TestImporter:
    def test_danish_record_is_translated(
        self, tmp_path, translation_enabled, fake_model
    ):
        _import(tmp_path, [RECORD])
        event = Event.objects.get()
        assert event.description == DANISH
        assert event.description_language == "da"
        assert event.description_en.startswith("EN<")
        assert event.is_machine_translated

    def test_english_record_gets_no_translation(
        self, tmp_path, translation_enabled, fake_model
    ):
        _import(tmp_path, [{**RECORD, "description": ENGLISH}])
        event = Event.objects.get()
        assert event.description_language == "en"
        assert event.description_en == ""
        assert not event.is_machine_translated

    def test_unchanged_record_is_not_reprocessed(self, tmp_path, translation_enabled):
        with patch(
            "events.management.commands.base_import.process_description",
            return_value=DescriptionResult(language="en"),
        ) as process:
            _import(tmp_path, [RECORD])
            _import(tmp_path, [RECORD])
        assert process.call_count == 1

    def test_changed_description_is_reprocessed(
        self, tmp_path, translation_enabled, fake_model
    ):
        _import(tmp_path, [RECORD])
        _import(tmp_path, [{**RECORD, "description": ENGLISH}])
        event = Event.objects.get()
        assert event.description_language == "en"
        assert event.description_en == ""

    def test_unprocessed_existing_event_is_processed(
        self, tmp_path, settings, fake_model
    ):
        _import(tmp_path, [RECORD])
        assert Event.objects.get().description_language == ""
        settings.TRANSLATION_ENABLED = True
        _import(tmp_path, [RECORD])
        assert Event.objects.get().description_language == "da"

    def test_disabled_resets_stale_translation(
        self, tmp_path, translation_enabled, fake_model
    ):
        _import(tmp_path, [RECORD])
        translation_enabled.TRANSLATION_ENABLED = False
        _import(tmp_path, [{**RECORD, "description": DANISH_2}])
        event = Event.objects.get()
        assert event.description == DANISH_2
        assert event.description_language == ""
        assert event.description_en == ""
        assert not event.description_en_is_machine

    def test_skip_translation_flag(self, tmp_path, translation_enabled, fake_model):
        _import(tmp_path, [RECORD], skip_translation=True)
        assert Event.objects.get().description_language == ""
        fake_model.assert_not_called()

    def test_translation_failure_still_imports(self, tmp_path, translation_enabled):
        with patch.object(
            translation, "_translate_sentences", side_effect=RuntimeError("boom")
        ):
            _import(tmp_path, [RECORD])
        event = Event.objects.get()
        assert event.description == DANISH
        assert event.description_language == ""


# ── Backfill ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestBackfillTranslations:
    def test_processes_unprocessed_scraped_events(
        self, translation_enabled, fake_model
    ):
        scraped = EventFactory.create(external_source="faar302", description=DANISH)
        user_event = EventFactory.create(description=DANISH)
        done = EventFactory.create(
            external_source="faar302", description=ENGLISH, description_language="en"
        )
        out = io.StringIO()
        call_command("backfill_translations", stdout=out)

        scraped.refresh_from_db()
        assert scraped.is_machine_translated
        user_event.refresh_from_db()
        assert user_event.description_language == ""
        done.refresh_from_db()
        assert done.description_en == ""
        assert "Processed 1 event(s): da=1." in out.getvalue()

    def test_dry_run_does_not_persist(self, translation_enabled, fake_model):
        event = EventFactory.create(external_source="faar302", description=DANISH)
        out = io.StringIO()
        call_command("backfill_translations", "--dry-run", stdout=out)
        event.refresh_from_db()
        assert event.description_language == ""
        assert "dry run" in out.getvalue()

    def test_limit(self, translation_enabled, fake_model):
        EventFactory.create_batch(3, external_source="faar302", description=ENGLISH)
        call_command("backfill_translations", "--limit", "2", stdout=io.StringIO())
        assert Event.objects.filter(description_language="en").count() == 2

    def test_undetermined_is_left_for_retry(self, translation_enabled, fake_model):
        event = EventFactory.create(external_source="faar302", description="Koncert")
        out = io.StringIO()
        call_command("backfill_translations", stdout=out)
        event.refresh_from_db()
        assert event.description_language == ""
        assert "undetermined=1" in out.getvalue()

    def test_disabled(self):
        out = io.StringIO()
        call_command("backfill_translations", stdout=out)
        assert "disabled" in out.getvalue()


# ── Pages, feeds, search ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDisplay:
    def _translated_event(self):
        return EventFactory.create(
            external_source="faar302",
            description=DANISH,
            description_language="da",
            description_en="Machine translated English text.",
            description_en_is_machine=True,
        )

    def test_detail_shows_translation_with_note(self, client):
        event = self._translated_event()
        response = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        content = response.content.decode()
        assert "Automatically translated from Danish" in content
        assert "Machine translated English text." in content
        assert "Forestillingen undersøger" not in content

    def test_detail_without_translation_has_no_note(self, client):
        event = EventFactory.create(
            external_source="faar302", description=ENGLISH, description_language="en"
        )
        response = client.get(reverse("event_detail", kwargs={"slug": event.slug}))
        assert "Automatically translated" not in response.content.decode()

    def test_feeds_use_english(self, client):
        self._translated_event()
        rss = client.get(reverse("event_rss_feed")).content.decode()
        assert "Machine translated English text." in rss
        ics = client.get(reverse("event_ical_feed")).content.decode()
        assert "Machine translated English text." in ics

    def test_search_matches_translation(self, client):
        event = self._translated_event()
        response = client.get(reverse("event_list"), {"q": "translated"})
        assert event.title in response.content.decode()
