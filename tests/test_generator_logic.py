"""
Offline unit tests for src/generator.py pure logic: dynamic prompt bits,
disclaimer, registry-driven scope detection, refusals, citation checks,
and the answer-cache key. No LLM calls are made.
"""

import pytest
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
    # Real disk state: unloaded categories refuse (tax, foreign jurisdiction).
    for q, topic in [
        ("How do I file my income tax return?", "tax"),
        ("Can my landlord kick me out in London?", "foreign jurisdiction"),
    ]:
        result = gen.detect_scope(q)
        assert result["in_scope"] is False, f"{q!r} should refuse"
        assert result["detected_topic"] == topic


def test_criminal_scope_behavior(monkeypatch):
    # With criminal laws loaded (current disk state), criminal questions are in-scope
    assert gen.detect_scope("How do I file an FIR for motorcycle theft?")["in_scope"] is True

    # If criminal was not loaded, it would refuse
    monkeypatch.setattr(registry, "loaded_categories", lambda: {"tenancy", "cybercrime", "family", "consumer"})
    refused = gen.detect_scope("How do I file an FIR for motorcycle theft?")
    assert refused["in_scope"] is False
    assert refused["detected_topic"] == "criminal"


def test_family_scope_behavior(monkeypatch):
    # With family laws loaded (current disk state), family questions are in-scope
    assert gen.detect_scope("What is the procedure for Khula?")["in_scope"] is True

    # If family was not loaded, it would refuse
    monkeypatch.setattr(registry, "loaded_categories", lambda: {"tenancy", "cybercrime"})
    refused = gen.detect_scope("What is the procedure for Khula?")
    assert refused["in_scope"] is False
    assert refused["detected_topic"] == "family"


def test_cybercrime_scope_behavior(monkeypatch):
    # With PECA loaded (current disk state), cybercrime is in-scope
    assert gen.detect_scope("How to report harassment on WhatsApp to FIA?")["in_scope"] is True

    # If cybercrime was not loaded, it would refuse
    monkeypatch.setattr(registry, "loaded_categories", lambda: {"tenancy"})
    refused = gen.detect_scope("How to report harassment on WhatsApp to FIA?")
    assert refused["in_scope"] is False
    assert refused["detected_topic"] == "cybercrime"


def test_scope_mixed_foreign_and_tax_refuses_over_loaded_keywords(monkeypatch):
    """
    Plan Wave 1-C: Scanning must refuse foreign jurisdiction and tax even when
    a loaded category keyword (e.g. FIR, theft, landlord) is present.
    """
    # Assume all categories are loaded
    monkeypatch.setattr(
        registry,
        "loaded_categories",
        lambda: {"tenancy", "cybercrime", "family", "criminal", "consumer"},
    )

    # 1. Foreign jurisdiction mixed with criminal
    res_london = gen.detect_scope("How do I file an FIR in London?")
    assert res_london["in_scope"] is False
    assert res_london["detected_topic"] == "foreign jurisdiction"

    res_dubai = gen.detect_scope("Landlord in Dubai and also FIR")
    assert res_dubai["in_scope"] is False
    assert res_dubai["detected_topic"] == "foreign jurisdiction"

    # 2. Tax mixed with criminal
    res_tax = gen.detect_scope("How do I pay FBR sales tax after theft?")
    assert res_tax["in_scope"] is False
    assert res_tax["detected_topic"] == "tax"

    # 3. Pure criminal with criminal loaded -> in scope
    res_fir = gen.detect_scope("How do I file an FIR for motorcycle theft?")
    assert res_fir["in_scope"] is True
    assert res_fir["detected_topic"] is None

    # 4. Pure criminal with criminal NOT loaded -> refuse
    monkeypatch.setattr(registry, "loaded_categories", lambda: {"tenancy"})
    res_fir_refused = gen.detect_scope("How do I file an FIR for motorcycle theft?")
    assert res_fir_refused["in_scope"] is False
    assert res_fir_refused["detected_topic"] == "criminal"

    # 5. Pure tenancy -> in scope
    res_tenancy = gen.detect_scope("Can my landlord evict me?")
    assert res_tenancy["in_scope"] is True
    assert res_tenancy["detected_topic"] is None


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


def test_citation_grounding_supports_matching_act_and_section():
    """
    Plan Wave 2-D: [Punjab Rented Premises Act, 2009 - Section 15] supported
    if retrieved metadata has that law + 15.
    """
    retrieved = [chunk("tenancy_punjab_2009", "15", "Grounds for eviction")]
    answer = "Landlord eviction rules [Punjab Rented Premises Act, 2009 - Section 15]."
    val = gen.validate_citations(answer, retrieved)
    assert val["has_citations"] is True
    assert "15" in val["supported"]
    assert val["unsupported"] == []


def test_citation_grounding_supports_statutory_cross_reference_in_chunk_text():
    """
    When a chunk body text explicitly cross-references another section of the same Act
    (e.g., Section 15 referencing Section 7), citations to that cross-referenced section
    are grounded and supported.
    """
    ch = chunk("tenancy_punjab_2009", "15", "Grounds for eviction")
    ch["text"] = (
        "[The Punjab Rented Premises Act, 2009 - Section 15: Grounds for eviction] "
        "A landlord may apply for eviction within thirty days after the expiry of the period stipulated in section 7."
    )
    retrieved = [ch]
    answer = (
        "Under [Punjab Rented Premises Act, 2009 - Section 15], eviction can be sought after "
        "the period in Section 7 expires."
    )
    val = gen.validate_citations(answer, retrieved)
    assert val["has_citations"] is True
    assert "15" in val["supported"]
    assert "7" in val["supported"]
    assert val["unsupported"] == []


def test_citation_grounding_strips_unsupported_same_section_different_act(monkeypatch):
    """
    Plan Wave 2-D: Same section number from a different Act in the answer,
    not in retrieval -> unsupported and removed or footnoted in answer.
    """
    retrieved = [chunk("tenancy_punjab_2009", "15", "Grounds for eviction")]
    raw_answer = (
        "- Landlord must apply to Rent Tribunal [Punjab Rented Premises Act, 2009 - Section 15].\n"
        "- Any person guilty shall be fined [The Pakistan Penal Code, 1860 - Section 15]."
    )
    monkeypatch.setattr(gen, "call_llm", lambda *args, **kwargs: raw_answer)

    res = gen.generate_answer("Eviction notice rules?", retrieved)

    # Supported citation is kept
    assert "Punjab Rented Premises Act" in res["answer"]
    assert "Section 15" in res["answer"]

    # Unsupported citation from different Act is removed from the visible answer
    assert "The Pakistan Penal Code" not in res["answer"]

    # Unsupported citations list tracks the hallucinated cite
    assert "15" in res["citations"]["unsupported"]
    assert any(c["law_id"] == "ppc_1860" and c["section"] == "15" for c in res["citations"]["unsupported_cites"])



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


def test_llm_provider_must_be_groq(monkeypatch):
    """Wave 4-M2: Non-groq LLM_PROVIDER raises ValueError."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "unsupported_provider")
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        gen.call_llm("test question", "test context", [])

