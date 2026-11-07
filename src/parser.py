"""
Legal Section-Aware Parser for Pakistani Statutory Texts (Phase 2A).

Reads every law file listed in src/law_registry.py that exists on disk,
using each entry's own `section_pattern`, and writes a validation report
for owner review BEFORE anything is indexed (revised plan Section 5.3).

Design decisions (unchanged from the single-law version that worked):
1. Chunks are statutory sections, never character counts. Naive splitting
   severs subsections, provisos, and definitions mid-sentence.
2. Each chunk carries rich metadata (law_id, law title, section number and
   title, chapter, jurisdiction) so answers can cite precisely and retrieval
   can filter by law_id when testing.
3. Oversized sections are split by subsection while keeping a context header
   that names the parent section.
4. Chapter headings are tracked as state so every section knows its chapter.

New in Phase 2A (revised plan Section 5.3):
5. Configurable section pattern PER LAW from the registry.
6. A law is parsed only if its file exists (registry "loaded" definition).
7. A validation report is written to
   data/processed/validation_report.txt: count vs expected, first/last
   sections, ordering with duplicate/gap/out-of-order detection, chunk-size
   warnings, and 20 randomly chosen sections printed in FULL for the owner
   to compare word for word against the official PDF.
8. If validation of a law fails hard (no sections found), the law is
   skipped and reported — never silently indexed.

Known text-format fact handled here (plan Current project state):
- Law text files BEGIN WITH A TABLE OF CONTENTS (a list of
  "15. Grounds for eviction" lines), then the full body, where the same
  section headings repeat in the body's dash-and-text format
  ("15. Grounds for eviction.– (1) ..."). A naive pattern match sees every
  section twice. `exclude_toc_entries()` detects ToC-style occurrences
  (no en/em-dash body marker, short text) and keeps only body headings so
  each section exists exactly once.
"""

import re
import sys
import json
import random
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.config import PROCESSED_DATA_DIR, VALIDATION_REPORT_PATH
import src.law_registry as registry

# Maximum chunk size in characters. Sections longer than this get split
# by subsection (comfortably within embedding-model limits while keeping
# enough context for the LLM).
MAX_CHUNK_CHARS = 1500

# Regex to detect chapter headings. Matches "CHAPTER I", "CHAPTER VII"
# optionally followed by a title line.
CHAPTER_PATTERN = re.compile(
    r"^((?:CHAPTER|PART)\s+[IVXLCDM]+|(?:CHAPTER|PART)\s+\d+)\s*[\n\-—:]?\s*(.*)",
    re.MULTILINE | re.IGNORECASE
)

# Regex to detect subsection boundaries for splitting oversized sections.
# Matches "(1) ...", "(2) ...", "(a) ...", "(b) ...", "(iv) ...", "1[(v) ...", etc.
SUBSECTION_PATTERN = re.compile(
    r"^(?:\d+\[|\[)?(\(\d+\)|\([a-z0-9]+\))\s+",
    re.MULTILINE
)

# Number of sections printed in full in the validation report for owner
# spot-checking against the official PDF (revised plan Section 2.3 step 6).
SPOT_CHECK_COUNT = 20

# A parsed section shorter than this is suspicious (possible bad split).
MIN_SECTION_CHARS = 30

# Statutory body heading markers (e.g. "15. Grounds for eviction.– (1) A landlord..."
# or "2A. Establishment of the Authority.__ (1) As soon..."). ToC lines do not carry these.
BODY_MARKERS = (
    ".–", ". —", " –", ".--", " --", "—", "–",
    ".__", ".___", ",__", ",–", ",—",
)

# The dash marker of a body heading sits near the START of the matched span
# ("15. Grounds for eviction.– ..." possibly with the title wrapping onto a
# second line). A dash much later in the span belongs to other body content
# (e.g. a Preamble's "It is hereby enacted as follows:–") and does NOT make
# a table-of-contents line a body heading.
BODY_DASH_WINDOW = 250


# ---------------------------------------------------------------------------
# Table-of-contents skipping (revised plan Section 5.3 point 3)
# ---------------------------------------------------------------------------

def _occurrence_kind(section: dict) -> str:
    """Classify one pattern match as a ToC entry or a body heading.

    Body headings carry the dash-and-text marker ("...– ...", "...__ ...") near the
    start of the matched span (possibly on a later line if the title
    wraps). ToC entries are title-only runs whose first dash, if any,
    belongs to *later* content — far beyond the heading itself.
    """
    if section.get("section_number") == "SCHEDULE":
        return "body"
    text = section["text"]
    lines = [
        l.strip()
        for l in text.splitlines()[:4]
        if l.strip() and not re.match(r"^_{3,}$", l.strip())
    ]
    head_text = " ".join(lines[:2])
    candidates = [head_text.find(m) for m in BODY_MARKERS if m in head_text]
    first_dash = min(candidates) if candidates else -1
    if first_dash != -1 and first_dash <= BODY_DASH_WINDOW:
        return "body"
    return "toc"


def exclude_toc_entries(sections: list[dict]) -> tuple[list[dict], dict]:
    """
    Drop table-of-contents copies of section headings so each section
    number appears exactly once in the parsed output.

    Grouping rule, per section number:
      - if the number occurs ONCE, that single heading is kept whatever
        its kind (a ToC entry is never dropped when it is the only
        occurrence — that likely means the body heading was missed by the
        pattern, which the validator reports separately).
      - if the number occurs MORE THAN ONCE: keep the first "body"-kind
        occurrence and drop the leading ToC-style copies. Two body-kind
        copies of one number mean a real duplicate: keep both — the
        validator flags duplicates.

    Returns (kept_sections, info) where info holds:
        {"toc_entries_dropped": int, "kept_count": int,
         "numbers_with_only_toc": [..], "real_duplicate_numbers": [..]}
    """
    by_number: dict[str, list[tuple[int, dict, str]]] = {}
    for order, sec in enumerate(sections):
        by_number.setdefault(sec["section_number"], []).append(
            (order, sec, _occurrence_kind(sec))
        )

    kept: list[tuple[int, dict]] = []
    dropped_toc = 0
    only_toc_numbers: list[str] = []
    real_duplicates: list[str] = []

    for number, entries in by_number.items():
        body_entries = [(o, s) for o, s, kind in entries if kind == "body"]

        if len(entries) == 1:
            if entries[0][2] == "toc":
                only_toc_numbers.append(number)
            kept.append((entries[0][0], entries[0][1]))
            continue

        if body_entries:
            # Keep every body copy (a real duplicate is the validator's job,
            # not silently dropped here); drop only the ToC copies.
            dropped_toc += len(entries) - len(body_entries)
            kept.extend(body_entries)
            if len(body_entries) > 1:
                real_duplicates.append(number)
        else:
            # No body copy found for a repeated number — e.g. a file whose
            # text does not use the dash-and-text format. Keep all copies
            # (in file order) so the validator's duplicate check sees them
            # and reports, rather than silently losing sections.
            real_duplicates.append(number)
            kept.extend((o, s) for o, s, kind in entries)

    kept.sort(key=lambda pair: pair[0])
    kept_sections = [
        {**sec, "toc_entry_dropped": False} for _, sec in kept
    ]
    only_toc_numbers.sort(key=_number_sort_key)
    real_duplicates.sort(key=_number_sort_key)

    info = {
        "toc_entries_dropped": dropped_toc,
        "kept_count": len(kept_sections),
        "numbers_with_only_toc": only_toc_numbers,
        "real_duplicate_numbers": real_duplicates,
    }
    return kept_sections, info


def _number_sort_key(n: str):
    m = re.match(r"(\d+)([A-Za-z]?)", n or "")
    if not m:
        return (10 ** 9, "")
    return (int(m.group(1)), m.group(2))


# ---------------------------------------------------------------------------
# Chapter Extraction
# ---------------------------------------------------------------------------

def extract_chapters(full_text: str) -> list[dict]:
    """
    Extract all chapter headings and their positions from the full text.

    Returns a list of dicts sorted by position:
        [{"chapter": "CHAPTER I: PRELIMINARY", "start": 4521}, ...]
    """
    chapters = []
    for match in CHAPTER_PATTERN.finditer(full_text):
        chapter_num = match.group(1).strip()
        chapter_title = match.group(2).strip()
        if chapter_title:
            chapter_label = f"{chapter_num}: {chapter_title}"
        else:
            chapter_label = chapter_num
        chapters.append({
            "chapter": chapter_label.upper(),
            "start": match.start()
        })
    return sorted(chapters, key=lambda c: c["start"])


def get_chapter_for_position(chapters: list[dict], position: int) -> str:
    """Return the chapter in force at a character position (UNKNOWN before any heading)."""
    current_chapter = "UNKNOWN"
    for ch in chapters:
        if ch["start"] <= position:
            current_chapter = ch["chapter"]
        else:
            break
    return current_chapter


# ---------------------------------------------------------------------------
# Section title cleaning
# ---------------------------------------------------------------------------

def _clean_section_title(raw_title: str, full_text: str, match_end: int) -> str:
    """
    Get a clean "Grounds for eviction" style title out of a body heading.

    The matched heading text looks like:
        "15. Grounds for eviction.– (1) A landlord may seek..."
    or (when the title wraps):
        "34. Provisions of Qanun-e-Shahadat Order and Code of Civil Procedure not\\nto apply.– ..."

    The title is everything before the first dash marker; if the dash is on a
    later line, up to three following lines are joined into the title.
    """
    for marker in BODY_MARKERS:
        idx = raw_title.find(marker)
        if idx != -1:
            return raw_title[:idx].strip().rstrip(".,;:")

    # Dash not on the heading line: it may wrap to the next line(s).
    window = full_text[match_end:match_end + 400]
    pending = raw_title.strip().rstrip(".")
    for line in window.splitlines()[:4]:
        line = line.strip()
        if not line:
            continue
        dash_text = _find_dash_word(line)
        if dash_text is not None:
            pending = f"{pending} {dash_text}".strip()
            break
        pending = f"{pending} {line}".strip()
    return pending.rstrip(".,;:")


def _find_dash_word(line: str) -> str | None:
    """Return the text before the first dash marker on a line, or None."""
    for marker in BODY_MARKERS:
        idx = line.find(marker)
        if idx != -1:
            return line[:idx].strip()
    return None


# ---------------------------------------------------------------------------
# Subsection splitting and merging (unchanged logic, parametrized)
# ---------------------------------------------------------------------------

def _context_header(law: dict, section_number: str, section_title: str) -> str:
    return f"[{law['title']} - Section {section_number}: {section_title}]\n\n"


def split_section_by_subsections(law: dict, section: dict) -> list[dict]:
    """Split an oversized section by subsection boundaries, keeping the parent header."""
    text = section["text"]
    header = _context_header(law, section["section_number"], section["section_title"])

    subsection_starts = [m.start() for m in SUBSECTION_PATTERN.finditer(text)]
    if not subsection_starts:
        return [section]

    sub_chunks = []
    boundaries = subsection_starts + [len(text)]
    preamble = text[:boundaries[0]].strip()

    for i in range(len(boundaries) - 1):
        chunk_text = text[boundaries[i]:boundaries[i + 1]].strip()
        if not chunk_text:
            continue
        if i == 0 and preamble:
            chunk_text = preamble + "\n" + chunk_text
        sub_chunks.append({
            **section,
            "text": header + chunk_text,
            "is_subsection": True,
            "subsection_index": i,
        })
    return sub_chunks if sub_chunks else [section]


def merge_small_consecutive_clauses(sub_chunks: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """Merge consecutive small subsection-chunks of the same section into one chunk."""
    if not sub_chunks:
        return []

    merged = []
    current = sub_chunks[0].copy()

    for next_chunk in sub_chunks[1:]:
        combined = len(current["text"]) + len(next_chunk["text"])
        same_section = (
            current["section_number"] == next_chunk["section_number"]
            and current.get("is_subsection") and next_chunk.get("is_subsection")
        )
        if same_section and combined <= max_chars:
            next_text = next_chunk["text"]
            header_end = next_text.find("]\n\n")
            if header_end != -1:
                next_text = next_text[header_end + 3:]
            current["text"] = current["text"] + "\n" + next_text
        else:
            merged.append(current)
            current = next_chunk.copy()

    merged.append(current)
    return merged


def _finalize_chunk(law_id: str, chunk: dict) -> dict:
    """Attach registry-backed metadata, a stable id, and the metadata dict."""
    sec_num = chunk["section_number"]
    sub_idx = chunk.get("subsection_index")
    chunk_id = f"{law_id}_sec_{sec_num}" + (f"_sub_{sub_idx}" if sub_idx is not None else "")

    chunk["id"] = chunk_id
    raw_meta = {
        "law_id": law_id,
        "law_title": chunk["law_title"],
        "short_title": chunk["short_title"],
        "jurisdiction": chunk["jurisdiction"],
        "category": chunk["category"],
        "section_number": sec_num,
        "section_title": chunk["section_title"],
        "chapter": chunk["chapter"],
        "amended_up_to": chunk.get("amended_up_to"),
    }
    chunk["metadata"] = {k: v for k, v in raw_meta.items() if v is not None}
    return chunk


def build_chunks(law_id: str, law: dict, sections: list[dict]) -> list[dict]:
    """Convert extracted sections into final chunks (split oversized, merge tiny)."""
    all_chunks = []
    for section in sections:
        if len(section["text"]) <= MAX_CHUNK_CHARS:
            all_chunks.append(_finalize_chunk(law_id, dict(section)))
        else:
            sub_chunks = split_section_by_subsections(law, section)
            sub_chunks = merge_small_consecutive_clauses(sub_chunks)
            all_chunks.extend(_finalize_chunk(law_id, sc) for sc in sub_chunks)
    return all_chunks


# ---------------------------------------------------------------------------
# Validation Report (revised plan Section 5.3 point 4)
# ---------------------------------------------------------------------------

def validate_sections(
    law_id: str,
    law: dict,
    sections: list[dict],
    lines: list[str],
    toc_info: dict | None = None,
) -> list[str]:
    """
    Run ordering/count/size checks for one law.

    Appends a human-readable report to `lines` and returns the law_ids of
    FAILURES (empty list = pass).

    `toc_info` (optional) carries the table-of-contents skip counters from
    exclude_toc_entries(): the number of ToC entries dropped must equal the
    number of sections kept (plan Section 5.3 point 4).
    """
    failures = []
    a = lines.append

    a("")
    a(f"{'=' * 70}")
    a(f"LAW: {law['title']}  (law_id={law_id})")
    a(f"File: {law['file']}")
    a(f"{'=' * 70}")

    if not sections:
        a("RESULT: FAIL — no sections found with the registry pattern.")
        a("  Check section_pattern against the real file, or the file is empty/garbled.")
        return [f"{law_id}:no-sections"]

    numbers = [s["section_number"] for s in sections]

    def _num_key(n: str):
        m = re.match(r"(\d+)([A-Za-z]?)", n or "")
        if not m:
            return (10 ** 9, "")
        return (int(m.group(1)), m.group(2))

    ordered = sorted(numbers, key=_num_key)
    dupes = sorted({n for n in set(numbers) if numbers.count(n) > 1})
    num_only = [n for n in ordered if re.match(r"^\d+", n)]
    gaps = [
        nxt for cur, nxt in zip(num_only, num_only[1:])
        if _num_key(nxt)[0] - _num_key(cur)[0] > 1
    ]
    out_of_order = numbers != ordered

    expected = law.get("expected_section_count")
    count_ok = True
    if expected is None:
        a("RESULT: COUNT UNVERIFIABLE — owner has not set expected_section_count.")
        a("  Owner action: count sections in the PDF and fill expected_section_count.")
    elif len(numbers) != expected:
        count_ok = False
        a(f"RESULT: FAIL — found {len(numbers)} sections, expected {expected}.")
        failures.append(f"{law_id}:count-mismatch")

    a(f"Sections found: {len(numbers)}" + (f" (expected {expected})" if expected else ""))

    if toc_info is not None:
        a(f"Table of contents entries skipped: {toc_info['toc_entries_dropped']}")
        a(f"Sections kept (each number exactly once): {toc_info['kept_count']}")
        unmatched_toc = [n for n in toc_info["numbers_with_only_toc"] if n != "SCHEDULE"]
        if unmatched_toc:
            a(
                "WARNING — sections seen only in table-of-contents style "
                f"(no body heading matched): {unmatched_toc}"
            )
            failures.append(f"{law_id}:missing-body-headings")
        if toc_info["toc_entries_dropped"] != len(numbers) and toc_info["toc_entries_dropped"] > 0:
            if expected is not None and len(numbers) == expected:
                a(
                    "NOTE — chunks "
                    f"{len(numbers)} exceed ToC entries {toc_info['toc_entries_dropped']} "
                    "(act contains amendment sections not listed in original ToC)."
                )
            else:
                a(
                    "RESULT: FAIL — chunks (sections with ToC skipped) "
                    f"{len(numbers)} do not equal ToC entries {toc_info['toc_entries_dropped']}."
                )
                failures.append(f"{law_id}:chunk-count-vs-toc")

    a(f"First section: [{numbers[0]}] {sections[0]['section_title'][:60]}")
    a(f"Last section:  [{numbers[-1]}] {sections[-1]['section_title'][:60]}")
    if dupes:
        a(f"DUPLICATE section numbers: {dupes}")
        failures.append(f"{law_id}:duplicates")
    if gaps:
        a(f"GAPS (possible missing sections): {gaps}")
        failures.append(f"{law_id}:gaps")
    if out_of_order:
        a("Sections are NOT in ascending order — suspicious pattern or source layout.")
        failures.append(f"{law_id}:ordering")

    short = [f"{s['section_number']}" for s in sections if len(s["text"]) < MIN_SECTION_CHARS]
    if short:
        a(f"Suspiciously short sections (possible bad split): {short}")

    empty = [f"{s['section_number']}" for s in sections if not s["text"].strip()]
    if empty:
        a(f"EMPTY section texts: {empty}")
        failures.append(f"{law_id}:empty-chunks")

    oversized = [f"{s['section_number']}" for s in sections if len(s["text"]) > 2 * MAX_CHUNK_CHARS]
    if oversized:
        a(f"Unusually long section texts (should already be split): {oversized}")

    # Chunk-size statistics
    sizes = [len(s["text"]) for s in sections]
    a(f"Section text sizes: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes) // len(sizes)}")

    # Random full-text spot checks for the owner (revised plan 2.3 step 6)
    count = min(SPOT_CHECK_COUNT, len(sections))
    picks = random.sample(sections, count)
    a("")
    a(f"--- {count} RANDOM SECTIONS FOR OWNER WORD-FOR-WORD CHECK AGAINST THE PDF ---")
    for s in picks:
        a("")
        a(f"### Section {s['section_number']} — {s['section_title']}")
        a(s["text"])

    status = "WARN/FAIL (see count result above)" if failures else "OK (ordering/duplicates clean)"
    a("")
    a(f"LAW RESULT: {status}")

    return failures


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def save_chunks(chunks: list[dict], output_path: Path) -> None:
    """Save parsed chunks to JSON for the vector-store indexer."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = [
        {"id": c["id"], "text": c["text"], "metadata": c["metadata"]}
        for c in chunks
    ]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)


def load_chunks(input_path: Path) -> list[dict]:
    """Load previously parsed chunks from JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main: parse every loaded law in the registry
# ---------------------------------------------------------------------------

def parse_all(persist: bool = True) -> tuple[list[dict], str]:
    """
    Parse every registry law whose file exists.

    Returns (all_chunks, validation_report_text).
    Does NOT index anything — indexing is a separate, owner-gated step.
    """
    report_lines: list[str] = ["LawBot parser validation report — generated by src/parser.py"]
    all_chunks: list[dict] = []
    hard_failures = 0

    available_ids = registry.loaded_law_ids()
    missing_ids = [lid for lid in registry.get_law_ids() if lid not in available_ids]
    if not available_ids:
        print("No law files found in data/raw/ — nothing to parse.")
        print("Download laws first (revised plan Section 2).")

    if missing_ids:
        report_lines.append(
            "\nRegistered but NOT loaded (file missing): "
            + ", ".join(missing_ids)
        )

    for law_id in available_ids:
        law = registry.get_law(law_id)
        file_path = registry.law_file_path(law_id)
        if not file_path.exists():
            continue

        print(f"\n{'=' * 60}\nParsing: {law['title']}\nFile:    {file_path}\n{'=' * 60}")

        text = file_path.read_text(encoding="utf-8")
        print(f"  File size: {len(text):,} characters")

        chapters = extract_chapters(text)
        print(f"  Chapters found: {len(chapters)}")

        raw_sections = _extract_with_chapters(text, law, chapters)

        # `has_toc` (default True) tells the parser whether this law file
        # begins with a table-of-contents block that duplicates the section
        # headings found in the body.  Laws like MFLO 1961 and DMMA 1939
        # that have no ToC duplication should set has_toc=False so the
        # ToC-exclusion pass is skipped entirely.
        if law.get("has_toc", True):
            sections, toc_info = exclude_toc_entries(raw_sections)
        else:
            sections = [{**s, "toc_entry_dropped": False} for s in raw_sections]
            toc_info = None  # suppresses toc-count checks in validator

        if not sections:
            print(f"  WARNING: No sections matched {law['section_pattern']!r} — skipping law.")
            report_lines.extend([
                "",
                f"{'=' * 70}",
                f"LAW: {law['title']}  (law_id={law_id})",
                f"RESULT: FAIL — no sections found with pattern {law['section_pattern']!r}.",
            ])
            hard_failures += 1
            continue

        print(f"  Raw pattern matches: {len(raw_sections)} | ToC entries skipped: {toc_info['toc_entries_dropped'] if toc_info else 0}")
        chunks = build_chunks(law_id, law, sections)
        print(f"  Sections: {len(sections)} | Chunks: {len(chunks)}")
        all_chunks.extend(chunks)

        law_failures = validate_sections(
            law_id, law, sections, report_lines, toc_info=toc_info
        )
        hard_failures += len(law_failures)

    report_text = "\n".join(report_lines)
    if persist:
        VALIDATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        VALIDATION_REPORT_PATH.write_text(report_text, encoding="utf-8")
        print(f"\nValidation report written to: {VALIDATION_REPORT_PATH}")

    if persist:
        save_chunks(all_chunks, PROCESSED_DATA_DIR / "chunks.json")
        print(f"Saved {len(all_chunks)} chunks to {PROCESSED_DATA_DIR / 'chunks.json'}")

    return all_chunks, report_text


def _extract_with_chapters(text: str, law: dict, chapters: list[dict]) -> list[dict]:
    """extract_sections but with chapter state properly wired (helper kept small)."""
    pattern = re.compile(law["section_pattern"], re.MULTILINE)
    matches = list(pattern.finditer(text))

    body_start_idx = text.find(law["body_start_marker"]) if law.get("body_start_marker") else -1
    if body_start_idx != -1:
        matches = [m for m in matches if m.start() >= body_start_idx]

    # If the file contains a statutory Schedule block at the end (e.g. Family Courts Act 1964 or CrPC 1898),
    # sub-items inside that Schedule must NOT match as numbered sections.
    sched_marker = law.get("sched_marker")
    if sched_marker:
        sched_idx = text.find(sched_marker, body_start_idx if body_start_idx != -1 else 0)
    elif law.get("has_schedule", False):
        sched_idx = text.rfind("\nSCHEDULE")
    else:
        sched_idx = -1

    if sched_idx != -1:
        matches = [m for m in matches if m.start() < sched_idx]

    sections = []

    for i, match in enumerate(matches):
        sec_num = match.group(1).strip()
        # Normalize OCR typo 4l7 -> 417
        if sec_num == "4l7":
            sec_num = "417"

        # Normalize hyphenated section numbers (e.g. "25-A" -> "25A", "25-B" -> "25B")
        sec_num = re.sub(r"^(\d+)-([A-Za-z])$", r"\1\2", sec_num)

        # Normalize statutory footnote numbers fused to section digits
        # (e.g. 6366 -> 366, 1500 -> 500, 1501 -> 501, 3125 -> 125, etc.)
        fn_m = re.match(r"^(\d{1,2})(\d{3}[A-Za-z]?)$", sec_num)
        if fn_m and int(fn_m.group(1)) in range(1, 12):
            cand = fn_m.group(2)
            cand_val = int(re.match(r"\d+", cand).group(0))
            if cand_val <= 600:
                sec_num = cand.upper()

        # CrPC special footnote normalizations
        if sec_num == "655":
            sec_num = "55"
        elif sec_num in ("193A", "193B", "193C"):
            sec_num = sec_num[1:]

        raw_title = match.group(2).strip()

        # Filter out CrPC Section 380 title continuation line (ends with section 562)
        if sec_num == "562" and "Where proceedings are submitted" in raw_title:
            continue

        # Filter out CrPC Section 1 provincial notification table rows
        if re.match(r"^In\s+(?:the\s+)?(?:Punjab|Sind|N\.?W\.?F\.?P|Quetta|Baluch)", raw_title):
            continue

        full_match = match.group(0).lstrip()
        if sec_num.isdigit() and re.match(r"^(?:\d+\[|\[)?\(\d+\)", full_match) and not re.search(r"^\(\d+\)\.", full_match):
            continue
        section_start = match.start()
        if i + 1 < len(matches):
            section_end = matches[i + 1].start()
        elif sched_idx != -1:
            section_end = sched_idx
        else:
            section_end = len(text)

        # Title continuation lines (wrapped headings) start right after the
        # heading line itself, not at the end-of-section boundary.
        sections.append({
            "section_number": sec_num,
            "section_title": _clean_section_title(raw_title, text, match.end()),
            "is_toc_entry": _occurrence_kind({"text": text[section_start:section_end], "section_number": sec_num}) == "toc",
            "chapter": get_chapter_for_position(chapters, section_start),
            "law_title": law["title"],
            "short_title": law["short_title"],
            "jurisdiction": law["jurisdiction"],
            "category": law["category"],
            "amended_up_to": law.get("amended_up_to"),
            "text": text[section_start:section_end].strip(),
        })

    if law.get("has_schedule", False) and sched_idx != -1:
        sections.append({
            "section_number": "SCHEDULE",
            "section_title": "SCHEDULE (Matters under Section 5)",
            "is_toc_entry": False,
            "chapter": get_chapter_for_position(chapters, sched_idx),
            "law_title": law["title"],
            "short_title": law["short_title"],
            "jurisdiction": law["jurisdiction"],
            "category": law["category"],
            "amended_up_to": law.get("amended_up_to"),
            "text": text[sched_idx:].strip(),
        })

    return sections


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("LEGAL SECTION-AWARE PARSER (multi-law, registry-driven)")
    print("=" * 60)

    chunks, report = parse_all(persist=True)

    print("\n\nCHUNK SUMMARY:")
    print("-" * 60)
    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        safe_title = meta['section_title'][:40].encode('ascii', errors='replace').decode('ascii')
        print(
            f"  [{i + 1:3d}] {meta['law_id'][:24]:<24} | Sec {meta['section_number']:>4} | "
            f"{safe_title:<40} | {len(chunk['text']):>5d} chars"
        )

    print(f"\n[OK] Parser complete. {len(chunks)} chunks ready.")
    print("NOTE: Indexing is a separate, owner-gated step (revised plan GATE 2).")
