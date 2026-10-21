"""
Offline unit tests for src/generator.py pure logic: dynamic prompt bits,
disclaimer, registry-driven scope detection, refusals, citation checks,
and the answer-cache key. No LLM calls are made.
"""

import src.generator as gen
import src.law_registry as registry
import src.config as config


def chunk(law_id="tenancy_punjab_2009", sec="15", title="Grounds for eviction"):
    law = registry.get_law(law_id)
    return {
        "id": f"{law_id}_sec_{sec}",
        "text": f"[{law['title']} - Section {sec}: {title}] Body text.",
        "metadata": {
            "law_id": law_id, "law_title": law["title"],
            "section_number": sec, "section_title": title,
            "chapter": "CHAPTER I", "category": law["category"],
            "jurisdiction": law["jurisdiction"],
        },
    }


# ---------------------------------------------------------------------------
# Dynamic prompt pieces (no hardcoded law names)
# ---------------------------------------------------------------------------

def test_laws_in_context_lists_unique_titles_in_order():
    chunks = [chunk("tenancy_punjab_2009", "5"), chunk("tenancy_punjab_2009", "15"),
              chunk("peca_2016", "24", "Cyber harassment")]
    line = gen._laws_in_context(chunks)
    titles = line.split(" | ")
    assert titles[0] == registry.get_law("tenancy_punjab_2009")["title"]
    assert titles[1] == registry.get_law("peca_2016")["title"]
    assert len(titles) == 2  # duplicate tenancy title collapsed
    assert gen._laws_in_context([]) == "[NO PROVISIONS RETRIEVED]"


def test_system_prompt_template_formats_without_law_names_hardcoded():
    filled = gen.SYSTEM_PROMPT_TEMPLATE.format(
        laws_in_context="TEST ACT A | TEST ACT B", context="--- PROVISION 1 ---"
    )
    assert "TEST ACT A | TEST ACT B" in filled
    assert "STRICT CITATION" in filled and "{laws_in_context}" not in filled
    # The static example in RULE 1 may mention the pilot act, but the
    # operative fields must all come from the placeholders.
    assert filled.count("{") == 0  # leave braces unformatted = broken call


def test_build_disclaimer_names_retrieved_laws():
    d = gen.build_disclaimer([chunk()])
    assert registry.get_law("tenancy_punjab_2009")["title"] in d
    assert "not formal legal advice" in d


def test_ensure_disclaimer_adds_only_when_missing():
    chunks = [chunk()]
    raw = gen.build_disclaimer(chunks).strip()  # response already carrying it
    out = gen.ensure_disclaimer(raw, chunks)
    assert out == raw  # no double disclaimer
    bare = "Some answer without a disclaimer."
    out2 = gen.ensure_disclaimer(bare, chunks)
    assert out2.startswith(bare) and "Disclaimer" in out2


# ---------------------------------------------------------------------------
# Registry-aware scope detection (stage-aware: depends on loaded laws)
# ---------------------------------------------------------------------------

def test_out_of_scope_when_category_not_loaded():
    # Real disk state: only tenancy is loaded -> criminal/family/etc. refuse.
    for q, topic in [
        ("How do I file an FIR for motorcycle theft?", "criminal"),
        ("What is the procedure for Khula?", "family"),
        ("How to report harassment on WhatsApp to FIA?", "cybercrime"),
        ("How do I file my income tax return?", "tax"),
        ("Can my landlord kick me out in London?", "foreign jurisdiction"),
    ]:
        result = gen.detect_scope(q)
        assert result["in_scope"] is False, f"{q!r} should refuse"
        assert result["detected_topic"] == topic


def test_in_scope_topic_with_loaded_law_passes_filter(monkeypatch):
    # If a criminal law were loaded, an FIR question is NOT a scope refusal;
    # the retrieval threshold decides coverage (revised plan Decision 3).
    monkeypatch.setattr(registry, "loaded_categories", lambda: {"criminal"})
    result = gen.detect_scope("How do I file an FIR for motorcycle theft?")
    assert result == {"in_scope": True, "detected_topic": None}


def test_plain_tenancy_questions_stay_in_scope():
    assert gen.detect_scope("Can my landlord evict me without notice?")["in_scope"] is True
    assert gen.detect_scope("Does the landlord have to return my security deposit?")["in_scope"] is True


def test_refusal_response_lists_loaded_laws():
    text = gen.build_refusal_response("criminal", "How do I file an FIR?")
    assert registry.get_law("tenancy_punjab_2009")["title"] in text
    assert "Criminal" in text and "Disclaimer" in text


# ---------------------------------------------------------------------------
# Context formatting + citation validation
# ---------------------------------------------------------------------------

def test_format_context_embeds_metadata_headers():
    ctx = gen.format_context([chunk()])
    assert "--- PROVISION 1 ---" in ctx
    assert f"Law: {registry.get_law('tenancy_punjab_2009')['title']}" in ctx
    assert "Section 15: Grounds for eviction" in ctx
    assert "[NO RELEVANT PROVISIONS" not in ctx
    assert gen.format_context([]) == "[NO RELEVANT PROVISIONS FOUND IN THE DATABASE]"


def test_validate_citations_extracts_unique_normalized_sections():
    answer = (
        "A [Act - Section 15(1)] and [Act - Section 15(2)] also cite Section 6 "
        "and section 302A maybe, but no cite here for 999."
    )
    res = gen.validate_citations(answer)
    assert res["has_citations"] is True
    # Sorted numerically: 6 < 15 < 302A
    assert res["citations_found"] == ["6", "15", "302A"]


def test_validate_citations_none_case():
    res = gen.validate_citations("No statutory citations in this text.")
    assert res["has_citations"] is False and res["citation_count"] == 0
    assert res["citations_found"] == []


# ---------------------------------------------------------------------------
# LLM answer cache key (pure function)
# ---------------------------------------------------------------------------

def test_cache_key_is_deterministic_and_discriminates(monkeypatch):
    a1 = gen._cache_key("Can my landlord evict me?", "ctx-1")
    a2 = gen._cache_key("Can my landlord evict me?", "ctx-1")
    a3 = gen._cache_key("Different question", "ctx-1")
    a4 = gen._cache_key("Can my landlord evict me?", "ctx-2")
    assert a1 == a2
    assert a1 != a3 and a1 != a4
    # A prompt-version bump must invalidate cached answers (plan Rule 6)
    monkeypatch.setattr(config, "PROMPT_VERSION", "BUMPED")
    assert gen._cache_key("Can my landlord evict me?", "ctx-1") != a1
