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
# Table-of-contents skipping (revised plan Section 5.3 point 3)
# ---------------------------------------------------------------------------

def _fake_law():
    law = dict(TENANCY_LAW)
    return law


def test_toc_entries_are_skipped_so_each_section_appears_once():
    """Sections listed in a ToC then repeated in the body parse exactly once."""
    toc = "".join(f"{n}. Title {n}\n" for n in range(1, 4))
    body = "".join(
        f"{n}. Title {n}.– Body text of section {n}, long enough to be a real paragraph.\n"
        for n in range(1, 4)
    )
    law = _fake_law()
    raw = parser._extract_with_chapters(toc + body, law, [])
    sections, info = parser.exclude_toc_entries(raw)

    numbers = [s["section_number"] for s in sections]
    assert numbers == ["1", "2", "3"], "each section must appear exactly once"
    assert info["toc_entries_dropped"] == 3
    assert info["kept_count"] == 3
    assert info["numbers_with_only_toc"] == []
    assert info["real_duplicate_numbers"] == []


def test_single_occurrence_toc_style_number_is_kept_and_flagged():
    """Defensive: a ToC-style number with no body match is kept, not vanishing."""
    raw = [
        parser._extract_with_chapters(
            "1. Title one\n", _fake_law(), []
        )[0]
    ]
    sections, info = parser.exclude_toc_entries(raw)
    assert [s["section_number"] for s in sections] == ["1"]
    assert info["numbers_with_only_toc"] == ["1"]


def test_two_body_copies_of_one_number_are_real_duplicates():
    raw = (
        parser._extract_with_chapters(
            "1. Title one.– Body one.\n1. Title one.– Body repeated.\n",
            _fake_law(), [],
        )
    )
    sections, info = parser.exclude_toc_entries(raw)
    assert len(sections) == 2
    assert info["real_duplicate_numbers"] == ["1"]


def test_occurrence_kind_dash_marker_split_toc_from_body():
    assert parser._occurrence_kind({"text": "15. Grounds for eviction"}) == "toc"
    assert parser._occurrence_kind({"text": "15. Grounds for eviction.– (1) text"}) == "body"
    # Wrapped body title: dash lands on the next line, still within the window.
    wrapped = "34. Provisions of X and Code not\nto apply.– Save as otherwise..."
    assert parser._occurrence_kind({"text": wrapped}) == "body"
    # ToC line whose span spills past preamble furniture; its dash belongs to
    # far-later content ("...enacted as follows:–"), far beyond the window.
    spilled_toc = (
        "36. Repeal and validation\nSCHEDULE\nTEXT\nPREAMBLE LINE\nAn\nAct\nto regulate\n"
        + "filler furniture line\n" * 10
        + "It is hereby enacted as follows:–\n"
    )
    assert parser._occurrence_kind({"text": spilled_toc}) == "toc"


def test_occurrence_kind_window_is_body_dash_near_start_only():
    far = "x" * (parser.BODY_DASH_WINDOW + 1) + "–"
    assert parser._occurrence_kind({"text": far}) == "toc"
    near = "x" * 10 + "–"
    assert parser._occurrence_kind({"text": near}) == "body"


def test_clean_section_title_strips_dash_and_body():
    text = "15. Grounds for eviction.– (1) A landlord may seek eviction.\n(1) more"
    raw_title = ("Grounds for eviction.– (1) A landlord may seek eviction.")
    assert parser._clean_section_title(raw_title, text, 0) == "Grounds for eviction"


def test_clean_section_title_joins_wrapped_title_before_dash():
    # Body heading like the real sec 34: dash lands on the NEXT line.
    full = "34. Provisions of Qanun-e-Shahadat Order and Code of Civil Procedure not\nto apply.– Save as otherwise..."
    match_end = full.index("to apply.–")
    raw_title = "Provisions of Qanun-e-Shahadat Order and Code of Civil Procedure not"
    title = parser._clean_section_title(raw_title, full, match_end)
    assert title.endswith("to apply"), f"wrapped title must join to the dash line: {title!r}"
    assert "–" not in title and "Save as otherwise" not in title


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


def test_finalize_chunk_omits_none_metadata():
    """Wave 4-M4: Keys whose value is None (e.g. amended_up_to) are omitted from metadata."""
    sec = make_section("1", "Title", "Text")
    sec["amended_up_to"] = None
    finalized = parser._finalize_chunk("test_law", sec)
    assert "amended_up_to" not in finalized["metadata"]
    assert finalized["metadata"]["section_number"] == "1"

    sec["amended_up_to"] = "2021"
    finalized2 = parser._finalize_chunk("test_law", sec)
    assert finalized2["metadata"]["amended_up_to"] == "2021"

