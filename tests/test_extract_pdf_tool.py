"""
Offline tests for src/extract_pdf.py. Only pure helpers and CLI error paths
are tested here (real extraction is owner-gated against actual law PDFs).
"""

from pathlib import Path

import pytest

import src.extract_pdf as x


def test_trim_page_furniture_removes_only_page_number_lines():
    text = (
        "Section 15. Grounds for eviction\n"
        "Page 12 of 80\n"
        "12\n"
        "36 of 40\n"
        "(1) A landlord may apply..."
    )
    out = x.trim_page_furniture(text)
    assert "Page 12" not in out
    assert "\n12\n" not in out
    assert "Section 15. Grounds for eviction" in out
    # Statutory wording with digits stays intact
    assert "(1) A landlord may apply..." in out


def test_trim_page_furniture_never_eats_numbered_provision_lines():
    # Lines that carry content (like a legal subsection starting with a number)
    # do NOT match the furniture pattern.
    line = "(1) 36 days notice"
    assert x.trim_page_furniture(line) == line


def test_main_errors_cleanly_when_pdf_missing(tmp_path, capsys):
    rc = x.main([str(tmp_path / "ghost.pdf"), "-o", str(tmp_path / "out.txt")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_main_flags_scanned_pdf_blank_pages(tmp_path, capsys, monkeypatch):
    """A blank 2-page PDF is extracted honestly: markers written, scan warning, exit 3."""
    pypdf = pytest.importorskip("pypdf")
    import io

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(buf.getvalue())

    out = tmp_path / "out.txt"
    rc = x.main([str(pdf), "-o", str(out)])
    captured = capsys.readouterr()
    assert rc == 3
    text = out.read_text(encoding="utf-8")
    assert "=== PAGE 1 ===" in text and "=== PAGE 2 ===" in text
    assert "NO TEXT LAYER" in text
    # Scan warning goes to stdout; nothing-extractable verdict to stderr
    assert "Scanned" in captured.out and "OCR" in captured.out
    assert "No page yielded text" in captured.err


def test_empty_pages_and_partial_ranges_are_handled(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    import io

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    pdf = tmp_path / "b3.pdf"
    pdf.write_bytes(buf.getvalue())

    out = tmp_path / "partial.txt"
    with_text, scanned = x.extract_pdf(pdf, out, start=2, end=2)
    assert (with_text, scanned) == (0, 1)
    assert "=== PAGE 2 ===" in out.read_text(encoding="utf-8")
    assert "=== PAGE 1 ===" not in out.read_text(encoding="utf-8")
