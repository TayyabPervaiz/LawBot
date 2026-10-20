"""
Legal Section-Aware Parser for Pakistani Statutory Texts.

This is the FOUNDATION of the entire RAG pipeline. If sections are split
incorrectly, every downstream answer will cite the wrong law.

Design decisions:
1. We parse by statutory "Section X." boundaries — NOT by character count.
   Naive 500-char splitting severs subsections, provisos, and definitions
   mid-sentence, which destroys legal meaning.

2. Each chunk carries rich metadata (law title, section number, section title,
   chapter) so the LLM can cite precisely: "[Act Name - Section X(y)]".

3. Oversized sections (like Section 2 Definitions or Section 15 Eviction
   grounds) are split by subsection while preserving a context header
   so the LLM always knows which section a subsection belongs to.

4. Chapter headings are tracked as state so each section knows its chapter.
"""

import re
import json
from pathlib import Path
from src.config import RAW_DATA_DIR, PROCESSED_DATA_DIR


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum chunk size in characters. Sections longer than this get split
# by subsection. Chosen to be comfortably within embedding model limits
# (all-MiniLM-L6-v2 handles ~256 tokens ≈ ~1200 chars) while keeping
# enough context for the LLM.
MAX_CHUNK_CHARS = 1500

# Regex to detect the start of a statutory section.
# Matches: "Section 1.", "Section 15.", "Section 2A.", etc.
# Captures: group(1) = section number (e.g., "15", "2A")
#           group(2) = section title (e.g., "Application for eviction.")
SECTION_PATTERN = re.compile(
    r"^Section\s+(\d+[A-Za-z]?)\.\s*(.*)",
    re.MULTILINE
)

# Regex to detect chapter headings.
# Matches: "CHAPTER I", "CHAPTER VII", "CHAPTER IV\nRENT TRIBUNAL"
CHAPTER_PATTERN = re.compile(
    r"^(CHAPTER\s+[IVXLCDM]+)\s*\n?(.*)",
    re.MULTILINE
)

# Regex to detect subsection boundaries for splitting oversized sections.
# Matches: "(1) ...", "(2) ...", "(a) ...", "(b) ..." at the start of a line.
SUBSECTION_PATTERN = re.compile(
    r"^(\(\d+\)|\([a-z]\))\s+",
    re.MULTILINE
)


# ---------------------------------------------------------------------------
# Chapter Extraction
# ---------------------------------------------------------------------------

def extract_chapters(full_text: str) -> list[dict]:
    """
    Extract all chapter headings and their positions from the full text.

    Returns a list of dicts sorted by position:
        [{"chapter": "CHAPTER V: EVICTION", "start": 4521}, ...]
    """
    chapters = []
    for match in CHAPTER_PATTERN.finditer(full_text):
        chapter_num = match.group(1).strip()        # e.g., "CHAPTER V"
        chapter_title = match.group(2).strip()       # e.g., "EVICTION"
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
    """
    Given a character position in the text, return the chapter it falls under.
    Uses the last chapter heading that appears before this position.
    """
    current_chapter = "UNKNOWN"
    for ch in chapters:
        if ch["start"] <= position:
            current_chapter = ch["chapter"]
        else:
            break
    return current_chapter


# ---------------------------------------------------------------------------
# Section Extraction
# ---------------------------------------------------------------------------

def extract_sections(full_text: str, law_title: str, chapters: list[dict]) -> list[dict]:
    """
    Extract all statutory sections from the full text.

    Each section is bounded by the start of one "Section X." and the start
    of the next "Section Y." (or end of file).

    Returns a list of dicts:
        [{
            "section_number": "15",
            "section_title": "Application for eviction",
            "chapter": "CHAPTER V: EVICTION",
            "law_title": "The Punjab Rented Premises Act, 2009",
            "text": "Section 15. Application for eviction. (1) A landlord..."
        }, ...]
    """
    # Find all section start positions
    matches = list(SECTION_PATTERN.finditer(full_text))

    if not matches:
        print("WARNING: No sections found! Check that the text uses 'Section X.' format.")
        return []

    sections = []
    for i, match in enumerate(matches):
        section_number = match.group(1).strip()
        section_title_raw = match.group(2).strip()

        # Clean the section title: remove trailing period
        section_title = section_title_raw.rstrip(".")

        # Extract the full text of this section:
        # From the start of this "Section X." to the start of the next "Section Y."
        section_start = match.start()
        if i + 1 < len(matches):
            section_end = matches[i + 1].start()
        else:
            section_end = len(full_text)

        section_text = full_text[section_start:section_end].strip()

        # Determine which chapter this section belongs to
        chapter = get_chapter_for_position(chapters, section_start)

        sections.append({
            "section_number": section_number,
            "section_title": section_title,
            "chapter": chapter,
            "law_title": law_title,
            "text": section_text,
        })

    return sections


# ---------------------------------------------------------------------------
# Subsection Splitting (for oversized sections)
# ---------------------------------------------------------------------------

def split_section_by_subsections(section: dict) -> list[dict]:
    """
    Split an oversized section into smaller chunks by subsection boundaries.

    Each sub-chunk gets a context header prepended so the LLM always knows
    which section and law the subsection belongs to.

    Example context header:
        "[The Punjab Rented Premises Act, 2009 - Section 15: Application for eviction]"

    Strategy:
    1. Find all subsection markers: (1), (2), (a), (b), etc.
    2. Split text at those boundaries.
    3. If the first part (before any subsection marker) is meaningful, keep it.
    4. Prepend the context header to each sub-chunk.
    """
    text = section["text"]
    context_header = (
        f"[{section['law_title']} - Section {section['section_number']}: "
        f"{section['section_title']}]\n\n"
    )

    # Find all subsection boundary positions
    subsection_starts = [m.start() for m in SUBSECTION_PATTERN.finditer(text)]

    if not subsection_starts:
        # No subsection markers found — return the section as-is
        return [section]

    # Build sub-chunks
    sub_chunks = []
    boundaries = subsection_starts + [len(text)]

    # Include any preamble text before the first subsection marker
    preamble = text[:boundaries[0]].strip()

    for i in range(len(boundaries) - 1):
        chunk_text = text[boundaries[i]:boundaries[i + 1]].strip()
        if not chunk_text:
            continue

        # If this is the first sub-chunk and there's a preamble, prepend it
        if i == 0 and preamble:
            chunk_text = preamble + "\n" + chunk_text

        # If still too long, we group consecutive clauses together
        # For now, add context header and accept
        full_chunk_text = context_header + chunk_text

        sub_chunks.append({
            "section_number": section["section_number"],
            "section_title": section["section_title"],
            "chapter": section["chapter"],
            "law_title": section["law_title"],
            "text": full_chunk_text,
            "is_subsection": True,
            "subsection_index": i,
        })

    return sub_chunks if sub_chunks else [section]


# ---------------------------------------------------------------------------
# Chunk Assembly
# ---------------------------------------------------------------------------

def merge_small_consecutive_clauses(sub_chunks: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """
    Merge consecutive small sub-chunks into larger ones to avoid
    producing many tiny chunks that lose context.

    Example: clauses (a), (b), (c), (d) of Section 6 are each ~100 chars.
    It's better to merge them into one chunk of ~400 chars.
    """
    if not sub_chunks:
        return []

    merged = []
    current = sub_chunks[0].copy()

    for i in range(1, len(sub_chunks)):
        next_chunk = sub_chunks[i]
        combined_length = len(current["text"]) + len(next_chunk["text"])

        # Merge if both are subsections of the same section AND combined size fits
        same_section = (
            current["section_number"] == next_chunk["section_number"]
            and current.get("is_subsection") and next_chunk.get("is_subsection")
        )

        if same_section and combined_length <= max_chars:
            # Merge: append next chunk's text (skip its context header since current already has one)
            # Extract just the subsection text (after the context header)
            next_text = next_chunk["text"]
            # Find end of context header (it ends with "]\n\n")
            header_end = next_text.find("]\n\n")
            if header_end != -1:
                next_text = next_text[header_end + 3:]
            current["text"] = current["text"] + "\n" + next_text
        else:
            merged.append(current)
            current = next_chunk.copy()

    merged.append(current)
    return merged


def build_chunks(sections: list[dict]) -> list[dict]:
    """
    Convert extracted sections into final chunks ready for embedding.

    For each section:
    - If it fits within MAX_CHUNK_CHARS, keep it as one chunk.
    - If it's oversized, split by subsections and merge small consecutive ones.

    Each final chunk gets a unique ID for ChromaDB.
    """
    all_chunks = []

    for section in sections:
        if len(section["text"]) <= MAX_CHUNK_CHARS:
            # Section fits in one chunk
            all_chunks.append(section)
        else:
            # Section is too long — split by subsections
            sub_chunks = split_section_by_subsections(section)
            # Merge tiny consecutive sub-chunks back together
            sub_chunks = merge_small_consecutive_clauses(sub_chunks)
            all_chunks.extend(sub_chunks)

    # Assign unique IDs
    for chunk in all_chunks:
        # Generate a stable, unique ID
        law_slug = chunk["law_title"].lower().replace(" ", "_").replace(",", "")
        sec_num = chunk["section_number"]
        sub_idx = chunk.get("subsection_index", "")
        if sub_idx != "":
            chunk["id"] = f"{law_slug}_sec_{sec_num}_sub_{sub_idx}"
        else:
            chunk["id"] = f"{law_slug}_sec_{sec_num}"

        # Build metadata dict (everything except 'text' and 'id')
        chunk["metadata"] = {
            "law_title": chunk["law_title"],
            "section_number": chunk["section_number"],
            "section_title": chunk["section_title"],
            "chapter": chunk["chapter"],
        }

    return all_chunks


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def parse_law_file(file_path: Path, law_title: str) -> list[dict]:
    """
    Parse a single law text file into chunks.

    Args:
        file_path: Path to the .txt file containing the law text.
        law_title: Official title of the law (e.g., "The Punjab Rented Premises Act, 2009").

    Returns:
        List of chunk dicts ready for vector store ingestion.
    """
    print(f"\n{'='*60}")
    print(f"Parsing: {law_title}")
    print(f"File:    {file_path}")
    print(f"{'='*60}")

    # Read the full text
    text = file_path.read_text(encoding="utf-8")
    print(f"  File size: {len(text):,} characters")

    # Extract chapter structure
    chapters = extract_chapters(text)
    print(f"  Chapters found: {len(chapters)}")
    for ch in chapters:
        print(f"    - {ch['chapter']}")

    # Extract sections
    sections = extract_sections(text, law_title, chapters)
    print(f"  Sections found: {len(sections)}")

    # Build chunks (split oversized, merge tiny)
    chunks = build_chunks(sections)
    print(f"  Final chunks: {len(chunks)}")

    # Report chunk sizes
    sizes = [len(c["text"]) for c in chunks]
    if sizes:
        print(f"  Chunk sizes: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)//len(sizes)}")

    # Report any oversized chunks that couldn't be split further
    oversized = [c for c in chunks if len(c["text"]) > MAX_CHUNK_CHARS]
    if oversized:
        print(f"  WARNING: {len(oversized)} chunks exceed {MAX_CHUNK_CHARS} chars:")
        for c in oversized:
            print(f"    - Section {c['section_number']}: {len(c['text'])} chars")

    return chunks


def save_chunks(chunks: list[dict], output_path: Path) -> None:
    """Save parsed chunks to a JSON file for inspection and downstream use."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save a clean version (without redundant keys in the top-level dict)
    serializable = []
    for chunk in chunks:
        serializable.append({
            "id": chunk["id"],
            "text": chunk["text"],
            "metadata": chunk["metadata"],
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved {len(serializable)} chunks to: {output_path}")


def load_chunks(input_path: Path) -> list[dict]:
    """Load previously parsed chunks from JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main: Parse all law files in data/raw/
# ---------------------------------------------------------------------------

# Registry of known law files and their official titles.
# To add a new law, just add an entry here and drop the .txt file in data/raw/.
LAW_REGISTRY = {
    "tenancy_punjab/punjab_rented_premises_act_2009.txt": {
        "title": "The Punjab Rented Premises Act, 2009",
    },
    # Future laws can be added here:
    # "penal_code/pakistan_penal_code_1860.txt": {
    #     "title": "The Pakistan Penal Code, 1860",
    # },
}


def parse_all() -> list[dict]:
    """
    Parse all registered law files and return combined chunks.
    Also saves chunks to data/processed/chunks.json.
    """
    all_chunks = []

    for relative_path, info in LAW_REGISTRY.items():
        file_path = RAW_DATA_DIR.parent / relative_path
        if not file_path.exists():
            print(f"\n  WARNING: File not found: {file_path}")
            print(f"  Skipping {info['title']}")
            continue

        chunks = parse_law_file(file_path, info["title"])
        all_chunks.extend(chunks)

    # Save combined chunks
    output_path = PROCESSED_DATA_DIR / "chunks.json"
    save_chunks(all_chunks, output_path)

    print(f"\n{'='*60}")
    print(f"TOTAL: {len(all_chunks)} chunks from {len(LAW_REGISTRY)} law(s)")
    print(f"{'='*60}")

    return all_chunks


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("LEGAL SECTION-AWARE PARSER")
    print("=" * 60)

    chunks = parse_all()

    # Print a summary of each chunk for verification
    print("\n\nCHUNK SUMMARY:")
    print("-" * 60)
    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        print(
            f"  [{i+1:2d}] Section {meta['section_number']:>3s} | "
            f"{meta['chapter']:<30s} | "
            f"{meta['section_title'][:40]:<40s} | "
            f"{len(chunk['text']):>5d} chars"
        )

    print(f"\n[OK] Parser complete. {len(chunks)} chunks ready for embedding.")
