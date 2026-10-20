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
"""

import re
import json
import random
from pathlib import Path

from src.config import PROCESSED_DATA_DIR, VALIDATION_REPORT_PATH
import src.law_registry as registry

# Maximum chunk size in characters. Sections longer than this get split
# by subsection (comfortably within embedding-model limits while keeping
# enough context for the LLM).
MAX_CHUNK_CHARS = 1500

# Regex to detect chapter headings. Matches "CHAPTER I", "CHAPTER VII"
# optionally followed by a title line.
CHAPTER_PATTERN = re.compile(
    r"^(CHAPTER\s+[IVXLCDM]+|CHAPTER\s+\d+)\s*[\n\-—:]?\s*(.*)",
    re.MULTILINE | re.IGNORECASE
)

# Regex to detect subsection boundaries for splitting oversized sections.
# Matches "(1) ...", "(2) ...", "(a) ...", "(b) ..." at the start of a line.
SUBSECTION_PATTERN = re.compile(
    r"^(\(\d+\)|\([a-z]\))\s+",
    re.MULTILINE
)

# Number of sections printed in full in the validation report for owner
# spot-checking against the official PDF (revised plan Section 2.3 step 6).
SPOT_CHECK_COUNT = 20

# A parsed section shorter than this is suspicious (possible bad split).
MIN_SECTION_CHARS = 30


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
    chunk["metadata"] = {
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

def validate_sections(law_id: str, law: dict, sections: list[dict], lines: list[str]) -> list[str]:
    """
    Run ordering/count/size checks for one law.

    Appends a human-readable report to `lines` and returns the law_ids of
    FAILURES (empty list = pass).
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
    gaps = [
        n for cur, nxt in zip(ordered, ordered[1:])
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

        sections = _extract_with_chapters(text, law, chapters)
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

        chunks = build_chunks(law_id, law, sections)
        print(f"  Sections: {len(sections)} | Chunks: {len(chunks)}")
        all_chunks.extend(chunks)

        law_failures = validate_sections(law_id, law, sections, report_lines)
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
    sections = []

    for i, match in enumerate(matches):
        section_start = match.start()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({
            "section_number": match.group(1).strip(),
            "section_title": match.group(2).strip().rstrip("."),
            "chapter": get_chapter_for_position(chapters, section_start),
            "law_title": law["title"],
            "short_title": law["short_title"],
            "jurisdiction": law["jurisdiction"],
            "category": law["category"],
            "amended_up_to": law.get("amended_up_to"),
            "text": text[section_start:section_end].strip(),
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
        print(
            f"  [{i + 1:3d}] {meta['law_id'][:24]:<24} | Sec {meta['section_number']:>4} | "
            f"{meta['section_title'][:40]:<40} | {len(chunk['text']):>5d} chars"
        )

    print(f"\n[OK] Parser complete. {len(chunks)} chunks ready.")
    print("NOTE: Indexing is a separate, owner-gated step (revised plan GATE 2).")
