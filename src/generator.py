"""
RAG Generator with Strict Legal Guardrails (Phase 2A, revised plan Section 5.5).

Controls:
1. HOW the LLM answers (strict citation format, grounded in retrieved text only).
2. WHEN it refuses (foreign jurisdictions, topics with no loaded law).
3. WHAT gets appended (mandatory dynamic legal disclaimer).

Phase 2A changes:
- The system prompt is DYNAMIC: {laws_in_context} lists the Acts actually
  retrieved for this question. No law name is hardcoded.
- Refusals are built from the registry of LOADED laws.
- Out-of-scope keyword detection now consults the registry: a topic keyword
  (criminal / family / cybercrime / tax) refuses ONLY if no loaded law covers
  that category. Foreign jurisdiction always refuses (no foreign laws exist).
- Deterministic LLM answer cache keyed by (prompt version, model, question,
  context) so free-tier 429s don't break benchmark runs (plan Section 6.4).
"""

import re
import time
import hashlib
import json
import threading

from groq import Groq
from src import config
import src.law_registry as registry
from src.citations import parse_citations, validate_citations_grounding, strip_or_footnote_unsupported


# ---------------------------------------------------------------------------
# System Prompt — The Core Guardrail (dynamic: no hardcoded law name)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a Pakistani Legal Information Specialist. Your ONLY role is to provide accurate legal information based EXCLUSIVELY on the statutory provisions provided to you below.

## LAWS IN CONTEXT
The provisions below come from:
{laws_in_context}

## YOUR ABSOLUTE RULES (NEVER VIOLATE THESE):

### RULE 1 — STRICT CITATION
Every factual legal statement you make MUST cite the exact Act name and Section number in this format:
[Act Name - Section X]
or for specific subsections:
[Act Name - Section X(y)]

Example: "The landlord must file an application before the Rent Tribunal to evict a tenant [Punjab Rented Premises Act, 2009 - Section 15(1)]."

If you cannot cite a specific section for a claim, DO NOT make that claim.
When several Acts appear in the context, cite each fact to its OWN Act. Never merge provisions from different Acts into one statement.
You may ONLY cite section numbers that are explicitly provided in the 'Section X:' headers of the statutory provisions below. Never cite section numbers that are not provided in the context below.

### RULE 2 — ZERO GUESSING / ANTI-HALLUCINATION
You may ONLY state legal information that is EXPLICITLY written in the statutory provisions provided below.
- Do NOT infer, extrapolate, or guess what the law "probably" says.
- Do NOT use general legal knowledge from your training data.
- If the provided provisions do not answer the question, you MUST say:
  "The provided provisions of {laws_in_context} do not explicitly address this specific issue. Please consult a qualified advocate for guidance."

### RULE 3 — SCOPE
You are ONLY authorized to answer questions about the Acts listed above.
If the question concerns a legal topic none of them covers, respond:
"This assistant currently covers: {laws_in_context}. Your question regarding [TOPIC] falls outside this scope. Please consult an appropriate legal resource or advocate."

### RULE 4 — MANDATORY DISCLAIMER
You MUST end EVERY response with a short disclaimer clarifying that this is legal information, not formal legal advice.

### RULE 5 — RESPONSE FORMAT
- Use clear, simple language a layperson can understand.
- Use bullet points or numbered steps when listing multiple points.
- Always specify the legal grounds and the relevant section numbers.
- Be concise but thorough — cover all relevant provisions from the retrieved text.
- Do NOT stop mid-sentence. Complete every explanation fully before ending.

### RULE 6 — LANGUAGE OF RESPONSE
Detect the dominant language of the user's question and respond in the SAME language:
- **Urdu script (اردو):** If the question contains mostly Urdu script characters, answer in fluent, formal Urdu while preserving statutory citations formatted as `[The Pakistan Penal Code, 1860 - Section 302]`.
- **Roman Urdu / Urdu-English mix:** If the question mixes Urdu words written in Roman script with English (e.g., "landlord ne eviction ka notice diya"), answer in the same Roman Urdu register — conversational but clear — while keeping statutory citations in English.
- **English:** If the question is in English, answer in English.
- **Ambiguous:** When unsure, prefer English.
- Always preserve statutory citation precision regardless of the language used.

## STATUTORY PROVISIONS FOR THIS QUERY:
{context}
"""


def _laws_in_context(retrieved_chunks: list[dict]) -> str:
    """Human-readable list of the Acts actually retrieved, in retrieval order."""
    seen: list[str] = []
    for chunk in retrieved_chunks:
        title = (chunk.get("metadata") or {}).get("law_title")
        if title and title not in seen:
            seen.append(title)
    return " | ".join(seen) if seen else "[NO PROVISIONS RETRIEVED]"


# ---------------------------------------------------------------------------
# Legal Disclaimer (dynamic)
# ---------------------------------------------------------------------------

def build_disclaimer(retrieved_chunks: list[dict]) -> str:
    """Disclaimer naming the Acts in this answer's context."""
    laws = _laws_in_context(retrieved_chunks)
    return (
        "\n\n---\n"
        f"**Disclaimer:** This is legal information based on: {laws}. "
        "It is not formal legal advice. For advice specific to your situation, "
        "please consult a qualified advocate."
    )


# ---------------------------------------------------------------------------
# Out-of-Scope Detection — Registry-aware Pre-LLM Filter
# ---------------------------------------------------------------------------

# Keyword groups for NON-legal-domain bounds. Each topic maps to the registry
# CATEGORY whose laws would answer it; the refusal fires only if the category
# has no loaded law. "foreign jurisdiction" always refuses.
OUT_OF_SCOPE_PATTERNS: dict[str, list[str]] = {
    "criminal": [
        r"\bFIR\b", r"\bpolice\s+report\b", r"\btheft\b", r"\bmurder\b",
        r"\bPPC\b", r"\bpenal\s+code\b", r"\bCrPC\b", r"\bbail\b",
        r"\barrest\b", r"\bcriminal\b", r"\bfraud\b", r"\brobbery\b",
        r"\bkidnapping\b", r"\bassault\b",
    ],
    "family": [
        r"\bdivorce\b", r"\bkhula\b", r"\btalaq\b", r"\bcustody\b",
        r"\bchild\s+support\b", r"\bnikkah?\b", r"\bmeher\b",
        r"\bmahr\b", r"\binheritance\b", r"\bwirasat\b", r"\bfamily\s+court\b",
        r"\bguardian\b",
    ],
    "cybercrime": [
        r"\bPECA\b", r"\bcybercrime\b", r"\bFIA\b", r"\bonline\s+harassment\b",
        r"\bhacking\b", r"\bdata\s+breach\b", r"\bWhatsApp\b", r"\bFacebook\b",
        r"\bsocial\s+media\b",
    ],
    # No tax law is planned in the near stages — always refuses (no category).
    # Patterns are intentionally narrow to avoid false-positive refusals for
    # questions that happen to mention "tax" in a non-tax-law context.
    "tax": [
        r"\bFBR\b", r"\bincome\s+tax\b", r"\bsales\s+tax\b", r"\btax\s+return\b",
        r"\bNTN\b", r"\bٹیکس\b", r"\bانکم\s*ٹیکس\b", r"\bسیلز\s*ٹیکس\b",
        r"\bایف\s*بی\s*آر\b", r"\bگوشوارہ\b", r"\btax\s+file\b", r"\btax\s+evasion\b",
        r"\bwithholding\s+tax\b", r"\bcustoms\s+duty\b",
    ],
    "foreign jurisdiction": [
        r"\bLondon\b", r"\bUK\b", r"\bUSA\b", r"\bUS\s+law\b", r"\bCanada\b",
        r"\bAustralia\b", r"\bIndia\b", r"\bDubai\b", r"\bUAE\b",
        r"\bSaudi\b", r"\bAmerican\b", r"\bBritish\b", r"\bEuropean\b",
        r"\bامریکہ\b", r"\bبرطانیہ\b", r"\bانڈیا\b", r"\bبھارت\b",
        r"\bدبئی\b", r"\bسعودی\b", r"\bکینیڈا\b", r"\bآسٹریلیا\b",
        r"\bamreeka\b", r"\bbartania\b", r"\bhindustan\b", r"\bbahar\s+ka\s+mulk\b",
    ],
}

TOPIC_TO_CATEGORY = {
    "criminal": "criminal",
    "family": "family",
    "cybercrime": "cybercrime",
    "tax": None,  # never loaded
    # foreign jurisdiction handled separately below
}


def detect_scope(question: str) -> dict:
    """
    Registry-aware scope detection (revised plan Section 5.4 replaces the
    Phase-1 tenancy-only binary filter).

    Returns {"in_scope": bool, "detected_topic": str|None}.
    A topic-refusal fires only when NO loaded law covers that category;
    the retrieval threshold then decides coverage within loaded laws.
    """
    question_lower = question.lower()
    loaded_categories = registry.loaded_categories()

    # Plan Wave 1-C: Scan all patterns first so foreign jurisdiction and tax
    # always trigger a refusal, even if a loaded keyword (e.g. FIR) also matches.
    matched_topics: list[str] = []
    for topic, patterns in OUT_OF_SCOPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question, re.IGNORECASE):
                if topic not in matched_topics:
                    matched_topics.append(topic)
                break

    if "foreign jurisdiction" in matched_topics:
        return {"in_scope": False, "detected_topic": "foreign jurisdiction"}

    if "tax" in matched_topics:
        return {"in_scope": False, "detected_topic": "tax"}

    for topic in matched_topics:
        category = TOPIC_TO_CATEGORY.get(topic)
        if category is None or category not in loaded_categories:
            return {"in_scope": False, "detected_topic": topic}

    return {"in_scope": True, "detected_topic": None}


def build_refusal_response(detected_topic: str, question: str) -> str:
    """Registry-driven out-of-scope refusal (lists the loaded laws)."""
    topic_display = detected_topic.title() if detected_topic else "that topic"
    loaded_line = registry.format_loaded_laws_for_refusal()
    return (
        f"This assistant is currently specialized in **the following laws**: {loaded_line}.\n\n"
        f"Your question regarding **{topic_display}** falls outside this scope.\n\n"
        f"Please consult an appropriate legal resource or a qualified advocate "
        f"for guidance on {topic_display} matters."
        "\n\n---\n"
        "**Disclaimer:** This is legal information, not formal legal advice. "
        "For advice specific to your situation, please consult a qualified advocate."
    )


# ---------------------------------------------------------------------------
# Context Formatting
# ---------------------------------------------------------------------------

def format_context(retrieved_chunks: list[dict], max_chars: int = 14000) -> str:
    """Format retrieved chunks with clear per-provision headers, capped at max_chars for ITPM safety.

    Guard rails:
    - Each individual chunk body is capped at max_chars // 2 so a single
      pathologically large section cannot blow the total limit on its own.
    - The global cap is checked before appending so the total never exceeds
      max_chars regardless of chunk count.
    """
    if not retrieved_chunks:
        return "[NO RELEVANT PROVISIONS FOUND IN THE DATABASE]"

    # Per-chunk body cap: prevents one giant section from consuming the whole window.
    per_chunk_body_cap = max_chars // 2

    context_parts = []
    total_len = 0
    for i, chunk in enumerate(retrieved_chunks, 1):
        metadata = chunk.get("metadata") or {}
        law_title = metadata.get("law_title", "Unknown law")
        section_num = metadata.get("section_number", "?")
        section_title = metadata.get("section_title", "")
        chapter = metadata.get("chapter", "")

        header = (
            f"--- PROVISION {i} ---\n"
            f"Law: {law_title}\n"
            f"Chapter: {chapter}\n"
            f"Section {section_num}: {section_title}\n"
            f"---\n"
        )
        chunk_body = chunk.get("text") or ""
        # Cap individual chunk body so one oversized section can't exceed the window
        if len(chunk_body) > per_chunk_body_cap:
            chunk_body = chunk_body[:per_chunk_body_cap] + "\n[... truncated for context limit ...]"
        part = header + chunk_body
        # Global cap: stop adding chunks once total would exceed limit
        if total_len + len(part) > max_chars:
            break
        context_parts.append(part)
        total_len += len(part)

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# LLM Answer Cache (deterministic answers — revised plan Section 6.4)
# ---------------------------------------------------------------------------

def _cache_key(question: str, context: str, conversation_history: list[dict] | None = None) -> str:
    hist_str = "|".join(f"{m.get('role')}:{m.get('content')}" for m in (conversation_history or []))
    tmpl_hash = hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()[:12]
    # Include MAX_TOKENS in the key so a change in token limit invalidates old short-answer entries.
    payload = "|".join([
        config.PROMPT_VERSION,
        tmpl_hash,
        config.LLM_MODEL,
        str(config.MAX_TOKENS),
        question,
        hashlib.sha256(context.encode("utf-8")).hexdigest(),
        hashlib.sha256(hist_str.encode("utf-8")).hexdigest() if hist_str else "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_cache_lock = threading.Lock()
MAX_CACHE_SIZE = 500

# In-memory cache: avoids reading the entire JSON file from disk on every lookup.
# The disk file is still written for persistence across restarts.
_memory_cache: dict[str, str] = {}
_memory_cache_loaded: bool = False


def _ensure_memory_cache_loaded() -> None:
    """Load the disk cache into memory once (called under _cache_lock)."""
    global _memory_cache, _memory_cache_loaded
    if not _memory_cache_loaded and config.LLM_CACHE_ENABLED:
        try:
            with open(config.LLM_CACHE_PATH, "r", encoding="utf-8") as f:
                _memory_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _memory_cache = {}
        _memory_cache_loaded = True


def _load_cache() -> dict:
    if not config.LLM_CACHE_ENABLED:
        return {}
    try:
        with open(config.LLM_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    if not config.LLM_CACHE_ENABLED:
        return
    config.LLM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LLM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _get_cached_answer(key: str) -> str | None:
    """Thread-safe in-memory cache lookup (falls back to disk on first access)."""
    if not config.LLM_CACHE_ENABLED:
        return None
    with _cache_lock:
        _ensure_memory_cache_loaded()
        return _memory_cache.get(key)


def _store_cached_answer(key: str, answer: str) -> None:
    """
    Thread-safe cache store: writes to memory immediately, persists to disk.
    Never caches strings starting with 'Error:'.
    """
    if not config.LLM_CACHE_ENABLED:
        return
    if not answer or answer.strip().startswith("Error:"):
        return

    with _cache_lock:
        _ensure_memory_cache_loaded()
        if len(_memory_cache) >= MAX_CACHE_SIZE and key not in _memory_cache:
            # Drop oldest entry (FIFO)
            try:
                oldest_key = next(iter(_memory_cache))
                del _memory_cache[oldest_key]
            except (StopIteration, KeyError):
                pass
        _memory_cache[key] = answer
        _save_cache(_memory_cache)


# ---------------------------------------------------------------------------
# LLM Call
# ---------------------------------------------------------------------------

def call_llm(
    question: str,
    context: str,
    retrieved_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Call the Groq LLM with the dynamic system prompt, with answer caching,
    conversation history context, and retry-with-backoff for rate limits.
    """
    if config.LLM_PROVIDER.lower() != "groq":
        raise ValueError(
            f"Unsupported LLM_PROVIDER '{config.LLM_PROVIDER}'. Only 'groq' is supported."
        )

    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your_groq_api_key_here":
        raise RuntimeError(
            "Groq API key not configured. "
            "Get a free key at https://console.groq.com/keys "
            "and add it to your .env file as GROQ_API_KEY=your_key"
        )

    key = _cache_key(question, context, conversation_history)
    cached = _get_cached_answer(key)
    if cached is not None:
        return cached

    full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        laws_in_context=_laws_in_context(retrieved_chunks),
        context=context,
    )

    messages = [{"role": "system", "content": full_system_prompt}]
    if conversation_history:
        for turn in conversation_history[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    client = Groq(api_key=config.GROQ_API_KEY)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
            )
            answer = response.choices[0].message.content
            _store_cached_answer(key, answer)
            return answer

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "authentication" in error_msg.lower():
                raise RuntimeError(
                    "Groq API authentication failed. Check your API key in .env"
                ) from e
            if "429" in error_msg or "rate" in error_msg.lower():
                if attempt < max_retries - 1:
                    m_min = re.search(r"try again in (\d+)m(\d+(\.\d+)?)s", error_msg)
                    if m_min:
                        wait_time = float(m_min.group(1)) * 60 + float(m_min.group(2)) + 2.0
                    else:
                        match = re.search(r"try again in (\d+(\.\d+)?)s", error_msg)
                        wait_time = float(match.group(1)) + 2.0 if match else (2 ** attempt) * 12
                    print(f"  [Rate Limit] {error_msg}")
                    print(f"  [Rate Limit] Waiting {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(
                    "Groq API rate limit reached after retries. The free tier has limits — "
                    "please wait a moment and try again."
                ) from e
            if "connection" in error_msg.lower() or "timeout" in error_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3
                    print(f"  [Network] Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(f"Groq API connection error: {error_msg}") from e
            raise RuntimeError(f"Groq API error: {error_msg}") from e


# ---------------------------------------------------------------------------
# Post-Processing
# ---------------------------------------------------------------------------

def ensure_disclaimer(response: str, retrieved_chunks: list[dict]) -> str:
    """Enforce the disclaimer as a safety net (dynamic per answer)."""
    if "disclaimer" in response.lower() and "legal information" in response.lower():
        return response
    return response + build_disclaimer(retrieved_chunks)


def validate_citations(response: str, retrieved_chunks: list[dict] | None = None) -> dict:
    """
    Check whether the response contains proper statutory citations,
    and verify grounding against retrieved chunk metadata (Wave 2-D).
    """
    parsed = parse_citations(response)
    unique_sections = sorted(
        {c["section"] for c in parsed},
        key=lambda x: (int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 999999, x),
    )

    supported: list[str] = []
    unsupported: list[str] = []
    unsupported_cites: list[dict] = []

    if retrieved_chunks is not None:
        grounding = validate_citations_grounding(parsed, retrieved_chunks)
        supported = sorted(
            {c["section"] for c in grounding["supported"]},
            key=lambda x: (int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 999999, x),
        )
        unsupported = sorted(
            {c["section"] for c in grounding["unsupported"]},
            key=lambda x: (int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 999999, x),
        )
        unsupported_cites = grounding["unsupported"]

    return {
        "has_citations": len(unique_sections) > 0,
        "citation_count": len(unique_sections),
        "citations_found": unique_sections,
        "supported": supported,
        "unsupported": unsupported,
        "unsupported_cites": unsupported_cites,
    }


# ---------------------------------------------------------------------------
# Main Generate Function — The Public API
# ---------------------------------------------------------------------------

def generate_answer(
    question: str,
    retrieved_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Generate a grounded legal answer with citations and guardrails.

    Returns dict with keys: answer, in_scope, detected_topic, citations,
    source_sections, not_covered.

    NOTE: Scope detection (detect_scope) is intentionally NOT called here —
    bot.py:ask() already calls it before this function and returns early.
    Calling it a second time was redundant and doubled regex scanning.
    """
    # Step 1: format context
    context = format_context(retrieved_chunks)

    source_sections = []
    for chunk in retrieved_chunks:
        sec_num = (chunk.get("metadata") or {}).get("section_number", "?")
        if sec_num not in source_sections:
            source_sections.append(sec_num)

    # Step 3: call the LLM (cached, retried)
    try:
        raw_answer = call_llm(question, context, retrieved_chunks, conversation_history=conversation_history)
    except RuntimeError as e:
        return {
            "answer": f"Error: {str(e)}",
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0,
                          "citations_found": [], "supported": [], "unsupported": []},
            "source_sections": source_sections,
            "not_covered": False,
        }

    # Step 4: enforce the dynamic disclaimer
    answer = ensure_disclaimer(raw_answer, retrieved_chunks)

    # Step 5: citation validation + retrieved-section grounding trace (Wave 2-D)
    citations = validate_citations(answer, retrieved_chunks)

    # Step 6: If unsupported citations are present, do not leave them in user-visible answer
    if citations["unsupported_cites"]:
        answer = strip_or_footnote_unsupported(answer, citations["unsupported_cites"])

    return {
        "answer": answer,
        "in_scope": True,
        "detected_topic": None,
        "citations": citations,
        "source_sections": source_sections,
        "not_covered": False,
    }
