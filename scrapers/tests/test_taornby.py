"""Unit tests for scrapers/taornby.py helper functions."""

from __future__ import annotations

import datetime

from bs4 import BeautifulSoup, Tag

from scrapers.taornby import (
    RangeSlot,
    SingleSlot,
    _collect_bio_names,
    _get_blocks,
    _infer_year,
    _parse_duration_minutes,
    build_records,
    extract_date_time_pairs,
    is_english_paragraph,
    is_meta_block,
    parse_meta,
    pick_title_and_artist,
)

TODAY = datetime.date(2026, 7, 13)


# ── is_meta_block / parse_meta ────────────────────────────────────────────────


def test_is_meta_block_requires_two_labels():
    assert is_meta_block("TID 20/8 kl. 16.00 HVOR Tårnbyparken") is True


def test_is_meta_block_rejects_prose_with_lowercase_hvor():
    # "hvor" ("where") is common in ordinary Danish sentences and must not
    # be mistaken for the ALL CAPS label.
    text = "Vi spørger hvor vi er, og hvor vi skal hen, og hvad det betyder."
    assert is_meta_block(text) is False


def test_is_meta_block_single_label_not_enough():
    assert is_meta_block("HVOR Tårnbyparken") is False


def test_parse_meta_splits_labels_and_values():
    text = "TID 20/8 kl. 16.00\nHVOR Tårnbyparken LÆNGDE 35 min"
    result = parse_meta(text)
    assert result == {
        "tid": "20/8 kl. 16.00",
        "hvor": "Tårnbyparken",
        "længde": "35 min",
    }


def test_parse_meta_handles_indvielse_alongside_hvornaar():
    text = "HVORNÅR Hele uge 34.\nINDVIELSE 20/8 kl 15.00\nHVOR Tårnbyparken"
    result = parse_meta(text)
    assert result["hvornår"] == "Hele uge 34."
    assert result["indvielse"] == "20/8 kl 15.00"
    assert result["hvor"] == "Tårnbyparken"


# ── _infer_year ────────────────────────────────────────────────────────────────


def test_infer_year_future_date_same_year():
    assert _infer_year(8, 20, TODAY) == 2026


def test_infer_year_past_date_rolls_to_next_year():
    assert _infer_year(1, 1, TODAY) == 2027


# ── extract_date_time_pairs ────────────────────────────────────────────────────


def test_single_date_and_time():
    result = extract_date_time_pairs("20/8 kl. 16.00", TODAY)
    assert result == [
        SingleSlot(datetime.date(2026, 8, 20), datetime.time(16, 0), None)
    ]


def test_multiple_showtimes_same_day_use_first_only():
    result = extract_date_time_pairs("21/8 kl 16.00 og 17:45", TODAY)
    assert result == [
        SingleSlot(datetime.date(2026, 8, 21), datetime.time(16, 0), None)
    ]


def test_multiple_dates_each_get_a_record():
    result = extract_date_time_pairs("21/8 kl 16:00 & kl 17:45 & 22/8 kl 16:15", TODAY)
    assert result == [
        SingleSlot(datetime.date(2026, 8, 21), datetime.time(16, 0), None),
        SingleSlot(datetime.date(2026, 8, 22), datetime.time(16, 15), None),
    ]


def test_date_range_with_no_times_is_a_range():
    result = extract_date_time_pairs("17/8 - 22/8", TODAY)
    assert result == [RangeSlot(datetime.date(2026, 8, 17), datetime.date(2026, 8, 22))]


def test_time_range_per_date():
    result = extract_date_time_pairs("21/8 17:30-19:30 & 22/8 kl. 17.00-20.0", TODAY)
    assert result == [
        SingleSlot(
            datetime.date(2026, 8, 21),
            datetime.time(17, 30),
            datetime.time(19, 30),
        ),
        SingleSlot(
            datetime.date(2026, 8, 22),
            datetime.time(17, 0),
            datetime.time(20, 0),
        ),
    ]


def test_date_with_tba_time_has_no_time():
    result = extract_date_time_pairs("21/8 formiddage /eftermiddag TBA", TODAY)
    assert result == [SingleSlot(datetime.date(2026, 8, 21), None, None)]


def test_no_date_returns_empty():
    assert extract_date_time_pairs("", TODAY) == []
    assert extract_date_time_pairs("Hele uge 34 med beboere.", TODAY) == []


def test_split_date_across_whitespace():
    # "22\n/8" style artefacts get normalised to a single line before this
    # function runs, but stray spaces around the slash should still parse.
    result = extract_date_time_pairs("22 /8 kl. 18.00", TODAY)
    assert result == [
        SingleSlot(datetime.date(2026, 8, 22), datetime.time(18, 0), None)
    ]


# ── _parse_duration_minutes ────────────────────────────────────────────────────


def test_duration_minutes_only():
    assert _parse_duration_minutes("35 min") == 35


def test_duration_hours_and_minutes():
    assert _parse_duration_minutes("1 time og 15 min") == 75


def test_duration_hours_only():
    assert _parse_duration_minutes("ca 2 timer") == 120


def test_duration_unparseable_returns_none():
    assert _parse_duration_minutes("Ingen aldersgrænse") is None


# ── is_english_paragraph ───────────────────────────────────────────────────────


def test_english_paragraph_detected():
    text = (
        "Feral Fantasies is a solo by Andreas Haglund exploring domestication "
        "and wildness."
    )
    assert is_english_paragraph(text) is True


def test_danish_paragraph_rejected():
    text = (
        "Humor, intimitet og intensitet eksisterer side om side i denne forestilling."
    )
    assert is_english_paragraph(text) is False


def test_english_paragraph_with_danish_place_name_still_detected():
    # Real proper nouns (the town's own name) contain Danish letters but
    # shouldn't disqualify an otherwise-English paragraph.
    text = (
        "With a hitchhiking sign, we move closer to Tårnby and the town's "
        "citizens, who guide us to the greenest place."
    )
    assert is_english_paragraph(text) is True


def test_short_danish_tagline_without_stopwords_rejected():
    assert is_english_paragraph("Intet ender nogensinde") is False


# ── pick_title_and_artist ──────────────────────────────────────────────────────


def test_title_first_when_artist_matches_bio_name():
    title, artist = pick_title_and_artist(
        "FERAL FANTASIES", "ANDREAS HAGLUND", {"ANDREAS HAGLUND"}
    )
    assert (title, artist) == ("FERAL FANTASIES", "ANDREAS HAGLUND")


def test_artist_first_when_title_matches_bio_name():
    title, artist = pick_title_and_artist(
        "JOANA ÖHLSCHLÄGER", "HEART TO RIDE", {"JOANA ÖHLSCHLÄGER"}
    )
    assert (title, artist) == ("HEART TO RIDE", "JOANA ÖHLSCHLÄGER")


def test_generic_title_word_wins_over_person_name():
    title, artist = pick_title_and_artist("PHYLLIS AKINYI", "WORKSHOP", set())
    assert (title, artist) == ("WORKSHOP", "PHYLLIS AKINYI")


def test_presenter_label_never_becomes_title():
    title, artist = pick_title_and_artist("TÅRNBY PARK STUDIO", "PARTY", set())
    assert (title, artist) == ("PARTY", "TÅRNBY PARK STUDIO")


def test_explicit_header_override():
    title, artist = pick_title_and_artist("LADY GAG", "MILK BOX STAGES", set())
    assert (title, artist) == ("MILK BOX STAGES", "LADY GAG")


def test_combined_byline_matches_individual_bio_names():
    title, artist = pick_title_and_artist(
        "MIKKA MALLOW & MARCOS NACAR",
        "CAR PIECE",
        {"MIKKA MALLOW", "MARCOS NACAR"},
    )
    assert (title, artist) == ("CAR PIECE", "MIKKA MALLOW & MARCOS NACAR")


# ── _collect_bio_names ─────────────────────────────────────────────────────────


def test_collect_bio_names_from_plain_blocks():
    blocks = ["ANDREAS HAGLUND\nAndreas Haglund is a choreographer...", "KØB BILLET"]
    assert _collect_bio_names(blocks) == {"ANDREAS HAGLUND"}


# ── _get_blocks / build_records (synthetic section) ───────────────────────────

_SECTION_HTML = """
<section class="page-section">
  <div class="sqs-block">
    <div class="sqs-html-content"><h1>FERAL FANTASIES</h1></div>
  </div>
  <div class="sqs-block">
    <div class="sqs-html-content"><p>ANDREAS HAGLUND</p></div>
  </div>
  <div class="sqs-block">
    <div class="sqs-html-content">
      <p><strong>Obey!</strong> Command! Submit!</p>
      <p><strong>In </strong><em>KABOOM</em><strong>, old objects are new.</strong></p>
      <p>Humor, intimitet og intensitet eksisterer side om side.</p>
      <p>Feral Fantasies is a solo by Andreas Haglund exploring domestication.</p>
    </div>
  </div>
  <div class="sqs-block">
    <div class="sqs-html-content">
      <p><strong>TID</strong> 22/8 <strong>kl:</strong> 19:00<br/>
      <strong>VARIGHED</strong> 50 min<br/>
      <strong>HVOR</strong> Tårnbyparken</p>
    </div>
  </div>
  <div class="sqs-block">
    <div class="sqs-html-content">
      <p>ANDREAS HAGLUND<br/>Andreas Haglund er en koreograf.</p>
    </div>
  </div>
</section>
"""


def test_get_blocks_preserves_paragraphs_without_inline_tag_splits():
    soup = BeautifulSoup(_SECTION_HTML, "lxml")
    section = soup.find("section")
    assert isinstance(section, Tag)
    blocks = _get_blocks(section)
    # The inline <strong>/<em> split inside "In KABOOM, old objects..." must
    # not produce a spurious line break.
    assert "In KABOOM, old objects are new." in blocks[2]


def test_build_records_end_to_end():
    soup = BeautifulSoup(_SECTION_HTML, "lxml")
    section = soup.find("section")
    assert isinstance(section, Tag)
    records = build_records(section, TODAY, fallback_date=None)
    assert len(records) == 1
    record = records[0]
    assert record["title"] == "Feral Fantasies"
    assert "By Andreas Haglund" in record["description"]
    assert "Feral Fantasies is a solo by Andreas Haglund" in record["description"]
    assert record["venue_name"] == "Tårnbyparken"
    assert record["venue_address"] == "Tårnbyparken, Tårnby, Denmark"
    assert record["start_datetime"] == "2026-08-22T17:00:00+00:00"
    assert record["end_datetime"] == "2026-08-22T17:50:00+00:00"
    assert record["external_source"] == "taornby"


def test_build_records_skips_non_event_section():
    html = """
    <section class="page-section">
      <div class="sqs-block">
        <div class="sqs-html-content"><h1>ÅRETS KUNSTNERE</h1></div>
      </div>
    </section>
    """
    soup = BeautifulSoup(html, "lxml")
    section = soup.find("section")
    assert isinstance(section, Tag)
    assert build_records(section, TODAY, fallback_date=None) == []


def test_build_records_falls_back_when_no_date_found():
    html = """
    <section class="page-section">
      <div class="sqs-block"><div class="sqs-html-content"><h1>MYSTERY ARTIST</h1></div></div>
      <div class="sqs-block"><div class="sqs-html-content"><p>MYSTERY TITLE</p></div></div>
      <div class="sqs-block"><div class="sqs-html-content"><p>An untimed piece.</p></div></div>
      <div class="sqs-block">
        <div class="sqs-html-content">
          <p><strong>HVOR</strong> Tårnbyparken<br/><strong>ALDER</strong> 6+</p>
        </div>
      </div>
    </section>
    """
    soup = BeautifulSoup(html, "lxml")
    section = soup.find("section")
    assert isinstance(section, Tag)
    fallback = datetime.date(2026, 8, 20)
    records = build_records(section, TODAY, fallback_date=fallback)
    assert len(records) == 1
    assert records[0]["start_datetime"] == "2026-08-20T10:00:00+00:00"
    assert "confirmed" in records[0]["price_note"].lower()
