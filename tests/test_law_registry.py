"""
Offline unit tests for src/law_registry.py (pure logic, no heavy deps).

These tests pin the registry contract that parser, retrieval, prompts, and
refusals all depend on (revised plan Section 5.2).
"""

import re

import pytest

import src.law_registry as registry


# ---------------------------------------------------------------------------
# Structure invariants
# ---------------------------------------------------------------------------

def test_registry_ids_are_unique_and_snake_case():
    ids = registry.get_law_ids()
    assert len(ids) == len(set(ids)), "duplicate law_id in registry"
    for law_id in ids:
        assert re.fullmatch(r"[a-z0-9_]+", law_id), f"bad law_id format: {law_id}"


@pytest.mark.parametrize("law_id", registry.get_law_ids())
def test_each_entry_has_required_fields(law_id):
    law = registry.get_law(law_id)
    for field in (
        "title", "short_title", "year", "jurisdiction", "category",
        "file", "section_pattern", "hint_keywords",
        "always_include_sections",
    ):
        assert field in law, f"{law_id} missing field {field}"
    # Pattern must compile and be anchored at line start
    assert law["section_pattern"].strip().startswith("^")
    re.compile(law["section_pattern"])
    assert isinstance(law["hint_keywords"], list) and law["hint_keywords"]


def test_expected_section_counts_when_set_are_positive_ints():
    for law_id, law in registry.get_registry().items():
        esc = law.get("expected_section_count")
        if esc is not None:
            assert isinstance(esc, int) and esc > 0


# ---------------------------------------------------------------------------
# Loaded-law logic (uses a temp file to avoid depending on real data state)
# ---------------------------------------------------------------------------

def test_is_loaded_depends_on_file_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DATA_DIR", tmp_path)
    assert not registry.is_loaded("peca_2016")  # registered but file missing
    target = tmp_path / registry.get_law("peca_2016")["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Section 1. Short title. Placeholder for the test fixture.", encoding="utf-8")
    assert registry.is_loaded("peca_2016")


def test_loaded_helpers_filter_to_existing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DATA_DIR", tmp_path)
    # Nothing exists -> nothing loaded
    assert registry.loaded_law_ids() == []
    assert "no laws yet" in registry.format_loaded_laws_for_refusal()
    # Make only PECA exist
    entry = registry.get_law("peca_2016")
    f = tmp_path / entry["file"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("Section 1. x", encoding="utf-8")
    assert registry.loaded_law_ids() == ["peca_2016"]
    assert registry.loaded_categories() == {"cybercrime"}
    assert registry.laws_in_category("cybercrime") == ["peca_2016"]
    assert registry.laws_in_category("tenancy") == []
    assert "The Prevention of Electronic Crimes Act, 2016" in registry.format_loaded_laws_for_refusal()


def test_law_file_path_composes_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "RAW_DATA_DIR", tmp_path)
    p = registry.law_file_path("ppc_1860")
    assert p == tmp_path / registry.get_law("ppc_1860")["file"]
    assert p.name == "pakistan_penal_code_1860.txt"
