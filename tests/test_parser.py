"""
Offline unit tests for src/parser.py (pure parsing/validation logic).

No real law files are used: everything is built from in-memory fixtures so
the tests never depend on (or write) statutory text — per revised plan
Rule 1, law text comes from the owner only.
"""

import src.parser as parser
import src.law_registry as registry

TENANCY_LAW = registry.get_law("tenancy_punjab_2009")


def make_section(num, title, text, law=TENANCY_LAW):
    """Build a section dict the way parser._extract_with_chapters does."""
    return {
        "section_number": num,
        "section_title": title,
        "chapter": "CHAPTER I: TEST",
        "law_title": law["title"],
        "short_title": law["short_title"],
        "jurisdiction": law["jurisdiction"],
        "category": law["category"],
        "amended_up_to": None,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Chapter extraction
# ---------------------------------------------------------------------------

def test_extract_chapters_assigns_titles_and_positions():
    text = "Preamble text here.\nCHAPTER I: PRELIMINARY\nSection 1. Title. Body.\nCHAPTER V: EVICTION\nSection 15. Grounds. Body."
    chapters = parser.extract_chapters(text)
    assert [c["chapter"] for c in chapters] == [
        "CHAPTER I: PRELIMINARY", "CHAPTER V: EVICTION",
    ]
    # positions are ascending
    starts = [c["start"] for c in chapters]
    assert starts == sorted(starts)


def test_get_chapter_for_position_picks_heading_before_position():
    text = "AAAA\nCHAPTER II: MID\nBBBB\nCHAPTER III: LATE\nCCCC"
    chapters = parser.extract_chapters(text)
    pos_early = text.index("BBBB")
    pos_unknown = 0
    assert parser.get_chapter_for_position(chapters, pos_early) == "CHAPTER II: MID"
    assert parser.get_chapter_for_position(chapters, pos_unknown) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Subsection splitting / merging / build_chunks
# ---------------------------------------------------------------------------

def test_build_chunks_keeps_short_section_whole_with_metadata():
    sec = make_section("5", "Tenancy agreement", "Section 5. Tenancy agreement. Short body text.")
    chunks = parser.build_chunks("tenancy_punjab_2009", TENANCY_LAW, [sec])
    assert len(chunks) == 1
    meta = chunks[0]["metadata"]
    assert meta["law_id"] == "tenancy_punjab_2009"
    assert meta["section_number"] == "5"
    assert meta["law_title"] == TENANCY_LAW["title"]
    assert chunks[0]["id"] == "tenancy_punjab_2009_sec_5"


def test_oversized_section_splits_by_subsection_and_keeps_parent_header():
    body = "Preamble about the section.\n" + (
        "(1) " + "Filler text for subsection one. " * 30 + "\n" +
        "(2) " + "Filler text for subsection two. " * 30
    )
    sec = make_section("15", "Grounds for eviction", ("Section 15. " + body))
    assert len(sec["text"]) > parser.MAX_CHUNK_CHARS

    chunks = parser.build_chunks("tenancy_punjab_2009", TENANCY_LAW, [sec])

    assert len(chunks) >= 2, "oversized section must be split"
    header = f"[{TENANCY_LAW['title']} - Section 15: Grounds for eviction]"
    for c in chunks:
        assert c["text"].startswith(header), "every sub-chunk keeps the parent context header"
        assert c["metadata"]["section_number"] == "15"
    # Multiple sub-chunks of one section get _sub_ ids
    assert any("_sub_" in c["id"] for c in chunks)


def test_merge_small_consecutive_clauses_combines_same_section():
    header_len = 60
    tag = "|" * 40
    c1 = {"section_number": "15", "section_title": "T", "is_subsection": True,
          "text": "[H]\n\n(1) " + tag}
    c2 = {"section_number": "15", "section_title": "T", "is_subsection": True,
          "text": "[H]\n\n(2) " + tag}
    c3 = {"section_number": "16", "section_title": "U", "is_subsection": True,
          "text": "[H2]\n\n(1) " + tag}
    merged = parser.merge_small_consecutive_clauses([c1, c2, c3])
    assert len(merged) == 2  # c1+c2 merged; c3 separate (different section)
    assert "(1) " + tag in merged[0]["text"] and "(2) " + tag in merged[0]["text"]


# ---------------------------------------------------------------------------
# Validation report checks
# ---------------------------------------------------------------------------

def _law(expected=None):
    law = dict(TENANCY_LAW)
    law["expected_section_count"] = expected
    return law


def test_validate_sections_passes_clean_sequence():
    secs = [make_section(str(n), f"Sec {n}", "Body text long enough. " * 8) for n in range(1, 4)]
    lines = []
    failures = parser.validate_sections("tenancy_punjab_2009", _law(3), secs, lines)
    assert failures == []
    assert any("LAW RESULT: OK" in ln for ln in lines)


def test_validate_sections_reports_count_mismatch_and_gaps():
    secs = [make_section(str(n), f"Sec {n}", "Body text long enough. " * 8)
            for n in (1, 2, 4, 5)]  # 3 missing
    lines = []
    failures = parser.validate_sections("tenancy_punjab_2009", _law(5), secs, lines)
    assert f"tenancy_punjab_2009:count-mismatch" in failures
    assert f"tenancy_punjab_2009:gaps" in failures
    assert any("expected 5" in ln for ln in lines)


def test_validate_sections_flags_duplicates_and_out_of_order():
    secs = [
        make_section("2", "B", "Body text long enough. " * 8),
        make_section("1", "A", "Body text long enough. " * 8),
        make_section("2", "B again", "Body text long enough. " * 8),
    ]
    lines = []
    failures = parser.validate_sections("tenancy_punjab_2009", _law(None), secs, lines)
    assert f"tenancy_punjab_2009:ordering" in failures
    assert f"tenancy_punjab_2009:duplicates" in failures


def test_validate_sections_count_unverifiable_when_owner_has_not_set():
    secs = [make_section("1", "A", "Body text long enough. " * 8)]
    lines = []
    failures = parser.validate_sections("tenancy_punjab_2009", _law(None), secs, lines)
    assert failures == []  # not a hard failure, but must be called out
    assert any("COUNT UNVERIFIABLE" in ln for ln in lines)


def test_validate_sections_no_sections_is_hard_fail():
    lines = []
    failures = parser.validate_sections("tenancy_punjab_2009", _law(36), [], lines)
    assert failures == ["tenancy_punjab_2009:no-sections"]
