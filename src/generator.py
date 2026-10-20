"""
RAG Generator with Strict Legal Guardrails.

This module is the most critical part of the system for legal accuracy.
It controls:
1. HOW the LLM answers (strict citation format, grounded in retrieved text only)
2. WHEN the LLM refuses (out-of-scope topics, insufficient evidence)
3. WHAT gets appended (mandatory legal disclaimer)

Design decisions:
- The system prompt is intentionally verbose and repetitive about citation rules
  because LLMs follow instructions better when they are emphasized multiple times.
- We use temperature=0.0 for deterministic, non-creative responses.
- The context window is carefully managed: we feed retrieved chunks with clear
  separators so the LLM can distinguish between different sections.
- Scope detection happens BEFORE the LLM call to save API quota on obvious
  out-of-scope queries.
"""

import re
import time
from groq import Groq
from src.config import GROQ_API_KEY, LLM_MODEL, MAX_TOKENS, TEMPERATURE


# ---------------------------------------------------------------------------
# System Prompt — The Core Guardrail
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Pakistani Legal Information Specialist. Your ONLY role is to provide accurate legal information about Punjab Tenancy and Rent Law based EXCLUSIVELY on the statutory provisions provided to you below.

## YOUR ABSOLUTE RULES (NEVER VIOLATE THESE):

### RULE 1 — STRICT CITATION
Every factual legal statement you make MUST cite the exact Act name and Section number in this format:
[Punjab Rented Premises Act, 2009 - Section X]
or for specific subsections:
[Punjab Rented Premises Act, 2009 - Section X(y)]

Example: "A landlord must file an application before the Rent Tribunal to evict a tenant [Punjab Rented Premises Act, 2009 - Section 15(1)]."

If you cannot cite a specific section for a claim, DO NOT make that claim.

### RULE 2 — ZERO GUESSING / ANTI-HALLUCINATION
You may ONLY state legal information that is EXPLICITLY written in the statutory provisions provided below.
- Do NOT infer, extrapolate, or guess what the law "probably" says.
- Do NOT use general legal knowledge from your training data.
- If the provided provisions do not contain the answer, you MUST say:
  "The provided provisions of the Punjab Rented Premises Act, 2009 do not explicitly address this specific issue. Please consult a qualified advocate for guidance."

### RULE 3 — SCOPE ENFORCEMENT
You are ONLY authorized to answer questions about Punjab Tenancy and Rent Law (The Punjab Rented Premises Act, 2009).
If the user asks about ANY other legal topic, respond with:
"This assistant is currently specialized in Punjab Tenancy and Rent Law (The Punjab Rented Premises Act, 2009). Your question regarding [TOPIC] falls outside this scope. Please consult an appropriate legal resource or advocate."

Out-of-scope topics include but are not limited to:
- Criminal law (Pakistan Penal Code, CrPC, FIRs)
- Family law (divorce, Khula, custody, inheritance)
- Cybercrime (PECA 2016, FIA complaints)
- Tax law (FBR, income tax)
- Corporate/business law
- Immigration law
- Any non-Pakistani jurisdiction
- Any non-Punjab provincial law

### RULE 4 — MANDATORY DISCLAIMER
You MUST end EVERY response with this disclaimer on a new line:
"---
Disclaimer: This is legal information based on the Punjab Rented Premises Act, 2009, not formal legal advice. For advice specific to your situation, please consult a qualified advocate."

### RULE 5 — RESPONSE FORMAT
- Use clear, simple language that a layperson can understand.
- Structure your response with bullet points or numbered steps when listing multiple points.
- Always specify the legal grounds and relevant section numbers.
- Be concise but thorough — cover all relevant provisions from the retrieved text.

## STATUTORY PROVISIONS FOR THIS QUERY:
{context}
"""


# ---------------------------------------------------------------------------
# Legal Disclaimer
# ---------------------------------------------------------------------------

LEGAL_DISCLAIMER = (
    "\n\n---\n"
    "**Disclaimer:** This is legal information based on the Punjab Rented Premises "
    "Act, 2009, not formal legal advice. For advice specific to your situation, "
    "please consult a qualified advocate."
)


# ---------------------------------------------------------------------------
# Scope Detection — Pre-LLM Filter
# ---------------------------------------------------------------------------

# Keywords that indicate out-of-scope legal queries.
# Checked BEFORE calling the LLM to save API quota.
OUT_OF_SCOPE_PATTERNS = {
    "criminal": [
        r"\bFIR\b", r"\bpolice\s+report\b", r"\btheft\b", r"\bmurder\b",
        r"\bPPC\b", r"\bpenal\s+code\b", r"\bCrPC\b", r"\bbail\b",
        r"\barrest\b", r"\bcriminal\b", r"\bfraud\b", r"\brobbery\b",
        r"\bkidnapping\b", r"\bassault\b",
    ],
    "family law": [
        r"\bdivorce\b", r"\bkhula\b", r"\btalaq\b", r"\bcustody\b",
        r"\bchild\s+support\b", r"\bnikkah\b", r"\bnikah\b", r"\bmeher\b",
        r"\bmahr\b", r"\binheritance\b", r"\bwirasat\b", r"\bfamily\s+court\b",
        r"\bguardian\b",
    ],
    "cybercrime": [
        r"\bPECA\b", r"\bcybercrime\b", r"\bFIA\b", r"\bonline\s+harassment\b",
        r"\bhacking\b", r"\bdata\s+breach\b", r"\bWhatsApp\b", r"\bFacebook\b",
        r"\bsocial\s+media\b",
    ],
    "tax": [
        r"\bFBR\b", r"\bincome\s+tax\b", r"\bsales\s+tax\b", r"\btax\s+return\b",
        r"\bNTN\b",
    ],
    "foreign jurisdiction": [
        r"\bLondon\b", r"\bUK\b", r"\bUSA\b", r"\bUS\s+law\b", r"\bCanada\b",
        r"\bAustralia\b", r"\bIndia\b", r"\bDubai\b", r"\bUAE\b",
        r"\bSaudi\b", r"\bAmerican\b", r"\bBritish\b", r"\bEuropean\b",
    ],
}

# Tenancy-related keywords that indicate the query IS in scope.
# If these are present alongside out-of-scope keywords, it's likely in scope.
IN_SCOPE_INDICATORS = [
    r"\btenant\b", r"\blandlord\b", r"\brent\b", r"\bevict\b",
    r"\btenancy\b", r"\blease\b", r"\brented\s+premises\b",
    r"\bsecurity\s+deposit\b", r"\brent\s+tribunal\b",
    r"\brent\s+registrar\b",
]


def detect_scope(question: str) -> dict:
    """
    Detect whether a question is in scope (Punjab tenancy law) or out of scope.

    Returns:
        {
            "in_scope": True/False,
            "detected_topic": "criminal" / "family law" / None,
            "confidence": "high" / "medium"
        }
    """
    question_lower = question.lower()

    # Check for in-scope indicators first
    has_tenancy_keywords = sum(
        1 for pattern in IN_SCOPE_INDICATORS
        if re.search(pattern, question_lower, re.IGNORECASE)
    )

    # Check each out-of-scope category
    for topic, patterns in OUT_OF_SCOPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question, re.IGNORECASE):
                # If the question also has tenancy keywords, it might be in scope.
                # But for foreign jurisdictions, require stronger evidence (2+ keywords)
                # because generic words like "tenant" appear in any jurisdiction's questions.
                if topic == "foreign jurisdiction":
                    if has_tenancy_keywords >= 2:
                        return {
                            "in_scope": True,
                            "detected_topic": None,
                            "confidence": "medium"
                        }
                elif has_tenancy_keywords >= 1:
                    return {
                        "in_scope": True,
                        "detected_topic": None,
                        "confidence": "medium"
                    }
                return {
                    "in_scope": False,
                    "detected_topic": topic,
                    "confidence": "high"
                }

    return {
        "in_scope": True,
        "detected_topic": None,
        "confidence": "high"
    }


def build_refusal_response(detected_topic: str, question: str) -> str:
    """Build a polite out-of-scope refusal response."""
    topic_display = detected_topic.title() if detected_topic else "that topic"
    return (
        f"This assistant is currently specialized in **Punjab Tenancy and Rent Law** "
        f"(The Punjab Rented Premises Act, 2009). Your question regarding "
        f"**{topic_display}** falls outside this scope.\n\n"
        f"Please consult an appropriate legal resource or a qualified advocate "
        f"for guidance on {topic_display} matters."
        f"{LEGAL_DISCLAIMER}"
    )


# ---------------------------------------------------------------------------
# Context Formatting
# ---------------------------------------------------------------------------

def format_context(retrieved_chunks: list[dict]) -> str:
    """
    Format retrieved chunks into a clear context string for the LLM.

    Each chunk is wrapped with clear section markers so the LLM can
    distinguish between different statutory provisions.
    """
    if not retrieved_chunks:
        return "[NO RELEVANT PROVISIONS FOUND IN THE DATABASE]"

    context_parts = []
    for i, chunk in enumerate(retrieved_chunks, 1):
        metadata = chunk.get("metadata", {})
        law_title = metadata.get("law_title", "Unknown")
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
        context_parts.append(header + chunk["text"])

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# LLM Call
# ---------------------------------------------------------------------------

def call_llm(question: str, context: str) -> str:
    """
    Call the Groq LLM with the formatted system prompt and user question.

    Args:
        question: The user's legal question.
        context: Formatted statutory provisions from the vector store.

    Returns:
        The LLM's response string.

    Raises:
        RuntimeError: If the Groq API key is missing or the API call fails.
    """
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        raise RuntimeError(
            "Groq API key not configured. "
            "Get a free key at https://console.groq.com/keys "
            "and add it to your .env file as GROQ_API_KEY=your_key"
        )

    # Build the full system prompt with context injected
    full_system_prompt = SYSTEM_PROMPT.format(context=context)

    client = Groq(api_key=GROQ_API_KEY)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": full_system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            return response.choices[0].message.content

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "authentication" in error_msg.lower():
                raise RuntimeError(
                    "Groq API authentication failed. Check your API key in .env"
                ) from e
            elif "429" in error_msg or "rate" in error_msg.lower():
                if attempt < max_retries - 1:
                    match = re.search(r"try again in (\d+(\.\d+)?)s", error_msg)
                    if match:
                        wait_time = float(match.group(1)) + 1.5
                    else:
                        wait_time = (2 ** attempt) * 6
                    print(f"  [Rate Limit] Waiting {wait_time:.1f}s before retry (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(
                        "Groq API rate limit reached after retries. The free tier has limits — "
                        "please wait a moment and try again."
                    ) from e
            elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3
                    print(f"  [Network] Connection issue. Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"Groq API connection error: {error_msg}") from e
            else:
                raise RuntimeError(f"Groq API error: {error_msg}") from e


# ---------------------------------------------------------------------------
# Post-Processing
# ---------------------------------------------------------------------------

def ensure_disclaimer(response: str) -> str:
    """
    Ensure the response ends with the legal disclaimer.
    The LLM is instructed to include it, but we enforce it as a safety net.
    """
    # Check if a disclaimer-like text is already present
    if "disclaimer" in response.lower() and "legal advice" in response.lower():
        return response

    # Append the disclaimer
    return response + LEGAL_DISCLAIMER


def validate_citations(response: str) -> dict:
    """
    Check whether the response contains proper statutory citations.

    Returns:
        {
            "has_citations": True/False,
            "citation_count": int,
            "citations_found": ["Section 15", "Section 6", ...]
        }
    """
    # Match patterns like [Punjab Rented Premises Act, 2009 - Section 15]
    # or simpler patterns like Section 15, Section 6(1)(a)
    citation_pattern = re.compile(
        r"Section\s+(\d+[A-Za-z]?)(?:\s*\([^)]*\))*",
        re.IGNORECASE
    )
    matches = citation_pattern.findall(response)
    unique_sections = list(set(matches))

    return {
        "has_citations": len(unique_sections) > 0,
        "citation_count": len(unique_sections),
        "citations_found": sorted(unique_sections, key=lambda x: int(re.match(r"\d+", x).group())),
    }


# ---------------------------------------------------------------------------
# Main Generate Function — The Public API
# ---------------------------------------------------------------------------

def generate_answer(question: str, retrieved_chunks: list[dict]) -> dict:
    """
    Generate a grounded legal answer with citations and guardrails.

    This is the main entry point for the generator module.

    Args:
        question: The user's legal question.
        retrieved_chunks: List of chunk dicts from the vector store,
                         each with "text" and "metadata" keys.

    Returns:
        {
            "answer": str,           # The final response to show the user
            "in_scope": bool,        # Whether the question was in scope
            "detected_topic": str,   # Out-of-scope topic if any
            "citations": dict,       # Citation validation results
            "source_sections": list, # Section numbers from retrieved chunks
        }
    """
    # Step 1: Scope detection (pre-LLM filter)
    scope = detect_scope(question)

    if not scope["in_scope"]:
        refusal = build_refusal_response(scope["detected_topic"], question)
        return {
            "answer": refusal,
            "in_scope": False,
            "detected_topic": scope["detected_topic"],
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": [],
        }

    # Step 2: Format context from retrieved chunks
    context = format_context(retrieved_chunks)

    # Track which sections were retrieved
    source_sections = []
    for chunk in retrieved_chunks:
        sec_num = chunk.get("metadata", {}).get("section_number", "?")
        if sec_num not in source_sections:
            source_sections.append(sec_num)

    # Step 3: Call LLM
    try:
        raw_answer = call_llm(question, context)
    except RuntimeError as e:
        return {
            "answer": f"Error: {str(e)}",
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": source_sections,
        }

    # Step 4: Post-process — ensure disclaimer is present
    answer = ensure_disclaimer(raw_answer)

    # Step 5: Validate citations
    citations = validate_citations(answer)

    return {
        "answer": answer,
        "in_scope": True,
        "detected_topic": None,
        "citations": citations,
        "source_sections": source_sections,
    }
