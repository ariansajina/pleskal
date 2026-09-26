"""Offline language detection and Danish → English translation.

Scraped descriptions arrive in English, Danish, or both ("English below"
pages). ``process_description`` splits a description into its Danish and
English paragraphs and, when there is no substantial English text, machine
translates the Danish paragraphs. Everything runs in-process, with no external
service:

* Detection: lingua, restricted to Danish and English.
* Translation: the Argos Translate da→en model (a CTranslate2 model plus
  subword-nmt BPE codes), run directly through ctranslate2, which avoids the
  ``argostranslate`` package and its PyTorch dependency chain. The model
  directory (``TRANSLATION_MODEL_DIR``) is baked into the Docker image, or
  fetched locally with ``manage.py download_translation_model``.

The original description is never modified; results are stored alongside it
on the Event (see ``Event.description_for``). Failures are logged and swallowed
so a translation problem never blocks an import.
"""

import functools
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

DANISH = "da"
ENGLISH = "en"
MIXED = "mixed"

# Below this many characters of (name-stripped) text a paragraph is too short
# to classify reliably ("Koncert", credit lists); it takes the language of its
# neighbours instead.
MIN_PARAGRAPH_CHARS = 25
# A description counts as monolingual when this share of its classified text
# is in one language (the rest is e.g. an English quote in a Danish text).
MONOLINGUAL_SHARE = 0.9
# In a mixed description, the English paragraphs are used as the English
# version only when they amount to this much text; a short English line in a
# Danish description isn't a translation of it.
MIN_ENGLISH_PART_CHARS = 300

_LINK_OR_URL_RE = re.compile(
    r"(\[[^\]]*\]\([^)]*\)"  # markdown link
    r"|<https?://[^>\s]+>"  # autolink
    r"|https?://\S+"  # bare URL
    r"|[\w.+-]+@[\w-]+\.[\w.-]+)"  # email address
)
_MD_LINK_RE = re.compile(r"^\[([^\]]*)\]\(([^)]*)\)$")
# Leading block markup: headings, bullets, numbered lists, blockquotes.
_BLOCK_PREFIX_RE = re.compile(r"[ \t]*(?:(?:#{1,6}|[*+-]|\d+[.)]|>)[ \t]+)*")
_WRAPPED_EMPHASIS_RE = re.compile(r"^(\*\*|__|\*|_)(.+)\1$")
_INLINE_EMPHASIS_RE = re.compile(r"(\*\*|__)(.+?)\1")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[\"“«(\[]?[A-ZÆØÅ0-9])")
_LETTER_RE = re.compile(r"[^\W\d_]")
_LEADING_LETTER_RE = re.compile(r"^[\W\d_]+")  # strips up to the first letter


@dataclass(frozen=True)
class DescriptionResult:
    """Outcome of processing one description; maps onto the Event fields."""

    language: str = ""  # "", "da", "en" or "mixed"
    da: str = ""  # Danish part of a mixed description
    en: str = ""  # machine translation, or English part of a mixed description
    en_is_machine: bool = False

    def as_fields(self) -> dict:
        return {
            "description_language": self.language,
            "description_da": self.da,
            "description_en": self.en,
            "description_en_is_machine": self.en_is_machine,
        }


# ── Detection ────────────────────────────────────────────────────────────────


@functools.cache
def _detector():
    from lingua import Language, LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_languages(
        Language.DANISH, Language.ENGLISH
    ).build()


def _plain_text(markdown_text: str) -> str:
    from events.feeds import _plain_text as strip_markdown

    return strip_markdown(markdown_text)


def _without_capitalized_words(text: str) -> str:
    """Drop capitalized words, which in these texts are mostly names.

    Event descriptions are dense with Nordic names and venues ("returns to
    København Danser", "thanks to Ida-Elisabeth Larsen"), which make the
    detector call English text Danish with full confidence. Function words,
    which carry the language signal, are lowercase in both languages.
    """
    return " ".join(
        word
        for word in text.split()
        if not _LEADING_LETTER_RE.sub("", word)[:1].isupper()
    )


def detect_language(markdown_text: str) -> str:
    """Return "da", "en", or "" when the text is too short or ambiguous."""
    text = _without_capitalized_words(_plain_text(markdown_text))
    if len(text) < MIN_PARAGRAPH_CHARS:
        return ""
    confidences = _detector().compute_language_confidence_values(text)
    if not confidences:
        return ""
    best = confidences[0]
    if best.value < settings.TRANSLATION_MIN_CONFIDENCE:
        return ""
    return best.language.iso_code_639_1.name.lower()


def _split_paragraphs(markdown_text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", markdown_text.strip()) if p.strip()]


def _paragraph_languages(paragraphs: list[str]) -> list[str]:
    """Detect each paragraph's language; unclassified ones inherit a neighbour's.

    An unclassified heading ("## English", "#### CREDITS") introduces what
    follows, so it takes the next classified paragraph's language; any other
    unclassified paragraph (credit lists, "Varighed ca. 35 min") belongs to
    what precedes it. Either falls back to the other direction at the edges.
    """
    detected = [detect_language(p) for p in paragraphs]

    def nearest(i: int, step: int) -> str:
        j = i + step
        while 0 <= j < len(detected):
            if detected[j]:
                return detected[j]
            j += step
        return ""

    langs = []
    for i, (paragraph, lang) in enumerate(zip(paragraphs, detected, strict=True)):
        if not lang:
            first = 1 if paragraph.lstrip().startswith("#") else -1
            lang = nearest(i, first) or nearest(i, -first)
        langs.append(lang)
    return langs


# ── Translation ──────────────────────────────────────────────────────────────


class TranslationUnavailableError(RuntimeError):
    """The translation model isn't installed at TRANSLATION_MODEL_DIR."""


@dataclass
class _Model:
    translator: object
    bpe: object
    tokenizer: object
    detokenizer: object


@functools.cache
def _model() -> _Model:
    model_dir = Path(settings.TRANSLATION_MODEL_DIR)
    if not (model_dir / "model" / "model.bin").exists():
        raise TranslationUnavailableError(
            f"No translation model at {model_dir}; run "
            "`manage.py download_translation_model`."
        )
    import ctranslate2
    from sacremoses import MosesDetokenizer, MosesTokenizer
    from subword_nmt.apply_bpe import BPE

    with open(model_dir / "bpe.model", encoding="utf-8") as codes:
        bpe = BPE(codes)
    return _Model(
        translator=ctranslate2.Translator(
            str(model_dir / "model"), device="cpu", compute_type="int8"
        ),
        bpe=bpe,
        tokenizer=MosesTokenizer(lang="da"),
        detokenizer=MosesDetokenizer(lang="en"),
    )


def _translate_sentences(sentences: list[str]) -> list[str]:
    """Translate a batch of plain-text sentences from Danish to English."""
    if not sentences:
        return []
    model = _model()
    tokenized = [
        model.bpe.process_line(  # ty: ignore[unresolved-attribute]
            model.tokenizer.tokenize(s, return_str=True, escape=False)  # ty: ignore[unresolved-attribute]
        ).split()
        for s in sentences
    ]
    results = model.translator.translate_batch(tokenized, beam_size=4)  # ty: ignore[unresolved-attribute]
    return [
        model.detokenizer.detokenize(  # ty: ignore[unresolved-attribute]
            " ".join(r.hypotheses[0]).replace("@@ ", "").split()
        )
        for r in results
    ]


class _Batch:
    """Collects sentences to translate so a description is one model call."""

    def __init__(self):
        self.sentences: list[str] = []

    def add_text(self, text: str) -> list:
        """Queue *text*; return parts (verbatim strings or sentence indices)."""
        if not _LETTER_RE.search(text):
            return [text]
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        parts: list = [leading] if leading else []
        for i, sentence in enumerate(_SENTENCE_SPLIT_RE.split(text.strip())):
            if i:
                parts.append(" ")
            parts.append(len(self.sentences))
            self.sentences.append(sentence)
        if trailing:
            parts.append(trailing)
        return parts

    def add_inline(self, text: str) -> list:
        """Queue inline Markdown, keeping link targets, URLs and emails as-is."""
        text = _INLINE_EMPHASIS_RE.sub(r"\2", text)
        parts: list = []
        for segment in _LINK_OR_URL_RE.split(text):
            if not segment:
                continue
            link = _MD_LINK_RE.match(segment)
            if link:
                parts.append("[")
                parts.extend(self.add_text(link.group(1)))
                parts.append(f"]({link.group(2)})")
            elif _LINK_OR_URL_RE.fullmatch(segment):
                parts.append(segment)
            else:
                parts.extend(self.add_text(segment))
        return parts

    def add_line(self, line: str) -> list:
        """Queue one Markdown line, keeping its block prefix and hard break."""
        # Only the prefix is matched by regex; splitting off the trailing
        # whitespace in Python keeps this linear on long whitespace runs.
        match = _BLOCK_PREFIX_RE.match(line)  # always matches (possibly empty)
        prefix = match.group(0) if match else ""
        rest = line[len(prefix) :]
        content = rest.rstrip()
        if not content:
            return [line]
        suffix = rest[len(content) :]
        wrapper = ""
        wrapped = _WRAPPED_EMPHASIS_RE.match(content)
        if wrapped:
            wrapper, content = wrapped.group(1), wrapped.group(2)
        return [prefix, wrapper, *self.add_inline(content), wrapper, suffix]


def _assemble(parts: list, translations: list[str]) -> str:
    return "".join(translations[p] if isinstance(p, int) else p for p in parts)


def translate_markdown(markdown_text: str) -> str:
    """Translate Danish Markdown to English, preserving its structure.

    Block prefixes (headings, lists, quotes), blank lines, hard line breaks,
    whole-line emphasis, link targets, bare URLs and emails survive; inline
    bold inside a sentence is dropped, since the model can't carry it.
    """
    batch = _Batch()
    line_parts = [batch.add_line(line) for line in markdown_text.split("\n")]
    translations = _translate_sentences(batch.sentences)
    return "\n".join(_assemble(parts, translations) for parts in line_parts)


def _translate_danish_paragraphs(paragraphs: list[str], langs: list[str]) -> str:
    """Translate the Danish paragraphs; keep English ones verbatim."""
    batch = _Batch()
    paragraph_parts = [
        [batch.add_line(line) for line in p.split("\n")]
        if lang == DANISH
        else [[line] for line in p.split("\n")]
        for p, lang in zip(paragraphs, langs, strict=True)
    ]
    translations = _translate_sentences(batch.sentences)
    return "\n\n".join(
        "\n".join(_assemble(parts, translations) for parts in lines)
        for lines in paragraph_parts
    )


# ── Entry point ──────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=512)
def process_description(markdown_text: str) -> DescriptionResult:
    """Detect a description's language(s) and produce its English version.

    * English → ``language="en"``, nothing else stored (the original is it).
    * Danish → ``language="da"`` plus a machine translation in ``en``.
    * Both, with a substantial English part → ``language="mixed"`` with the
      Danish and English paragraphs split into ``da`` and ``en``.
    * Undetermined (too short), or translation failed → ``language=""``,
      nothing stored.

    Memoized per process: recurring performances share one description.
    """
    paragraphs = _split_paragraphs(markdown_text)
    if not paragraphs:
        return DescriptionResult()
    try:
        langs = _paragraph_languages(paragraphs)
    except Exception:
        logger.exception("Language detection failed")
        return DescriptionResult()

    chars = {DANISH: 0, ENGLISH: 0}
    for paragraph, lang in zip(paragraphs, langs, strict=True):
        if lang:
            chars[lang] += len(_plain_text(paragraph))
    total = chars[DANISH] + chars[ENGLISH]
    if not total:
        return DescriptionResult()

    if chars[ENGLISH] >= MONOLINGUAL_SHARE * total:
        return DescriptionResult(language=ENGLISH)

    if (
        chars[DANISH] < MONOLINGUAL_SHARE * total
        and chars[ENGLISH] >= MIN_ENGLISH_PART_CHARS
    ):

        def part(lang: str) -> str:
            return "\n\n".join(
                p for p, pl in zip(paragraphs, langs, strict=True) if pl == lang
            )

        return DescriptionResult(language=MIXED, da=part(DANISH), en=part(ENGLISH))

    try:
        translated = _translate_danish_paragraphs(paragraphs, langs)
    # On failure, leave the description unprocessed (language "") so the
    # next backfill_translations run retries it.
    except TranslationUnavailableError as exc:
        logger.warning("%s", exc)
        return DescriptionResult()
    except Exception:
        logger.exception("Translation failed")
        return DescriptionResult()
    return DescriptionResult(language=DANISH, en=translated, en_is_machine=True)
