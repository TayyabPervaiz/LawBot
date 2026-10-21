"""
PDF -> UTF-8 text extractor for law downloads (revised plan Section 2.3,
Method A). EXTRACTS text; it never rewrites, summarizes, or "completes" it.

Usage:
    venv/Scripts/python.exe -m src.extract_pdf data/source_pdfs/tenancy_punjab/the_act.pdf ^
        -o data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt

What it does:
- Extracts every page's text layer with pypdf, writing a "=== PAGE n ==="
  marker before each page so the owner can compare against the PDF.
- Flags pages with no extractable text as likely SCANNED (needs OCR) — they
  are written empty rather than having anything made up.
- Trims obvious page furniture (standalone "Page 12 of 80" lines) only;
  it never touches statutory wording.
- Writes UTF-8 always. The owner then does the four verification checks
  (count/first-last/provisos/20 spot downloads) from the revised plan.

Exit codes: 0 success; 2 bad usage / file missing; 3 nothing extractable.
"""

import argparse
import re
import sys
from pathlib import Path

# Standalone page-number lines commonly seen in printed PDFs.
PAGE_FURNITURE_LINE = re.compile(
    r"^\s*(?:page\s+)?\d{1,3}\s*(?:of\s+\d{1,3})?\s*$", re.IGNORECASE
)


def trim_page_furniture(text: str) -> str:
    """
    Remove standalone page-number / 'Page x of y' lines. Purely mechanical —
    statutory wording is never altered.
    """
    return "\n".join(
        line for line in text.splitlines() if not PAGE_FURNITURE_LINE.match(line)
    )


def extract_pdf(pdf_path: Path, output_path: Path, start=None, end=None) -> tuple[int, int]:
    """
    Extract text from pdf_path into output_path (UTF-8).

    Returns (pages_with_text, scanned_pages).
    """
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)

    parts = []
    with_text = scanned = 0
    if start is None:
        first, last = 1, total
    else:
        first = max(1, start)
        last = min(total, end or total)
    range_pages = range(first, last + 1)

    for page_no in range_pages:
        page = reader.pages[page_no - 1]
        text = (page.extract_text() or "").strip()
        parts.append(f"=== PAGE {page_no} ===")
        if not text:
            scanned += 1
            parts.append("[NO TEXT LAYER ON THIS PAGE — LIKELY SCANNED; OWNER MUST OCR]")
            continue
        with_text += 1
        parts.append(trim_page_furniture(text))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return with_text, scanned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract law PDF text to UTF-8 (never retypes).")
    ap.add_argument("pdf", help="Source PDF (e.g. data/source_pdfs/<category>/<name>.pdf)")
    ap.add_argument("-o", "--output", required=True, help="Output .txt under data/raw/<category>/")
    ap.add_argument("--start", type=int, default=None, help="First page (1-based)")
    ap.add_argument("--end", type=int, default=None, help="Last page inclusive")
    args = ap.parse_args(argv)

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    out_path = Path(args.output)
    try:
        with_text, scanned = extract_pdf(pdf_path, out_path, args.start, args.end)
    except Exception as e:  # corrupt/encrypted PDF etc.
        print(f"ERROR: extraction failed for {pdf_path}: {e}", file=sys.stderr)
        print("Nothing was invented; fix or re-download the PDF.", file=sys.stderr)
        return 2

    print(f"Extracted {with_text} page(s) with a text layer "
          f"({scanned} page(s) had NO text layer) -> {out_path}")
    if scanned:
        print("[WARN] Scanned page(s) detected: OCR is needed (revised plan Section 2.4). "
              "Do NOT hand-type the missing text.")
    print("[NEXT] Owner verification checks (revised plan Section 2.3 step 6):")
    print("  1) section count vs official TOC  2) first/last sections present")
    print("  3) provisos/explanations/schedules included  4) 20 word-for-word spot checks")
    if with_text == 0:
        print("[FAIL] No page yielded text — PDF is likely a scan; report to the model.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
