"""
Statutory Citation Parser and Grounding Verifier (Wave 2-D).

Shared citation parser and validator for the Pakistan Law Bot.
Handles Act + Section parsing, normalization, and grounding checks against
retrieved chunk metadata.
"""

import re
from src import law_registry as registry


# Bracketed citation pattern: [Act Name - Section X(y)]
_BRACKET_PATTERN = re.compile(
    r"\[\s*([A-Za-z0-9\s,\.\-—–]+?)\s*-\s*Section\s+(\d+[A-Za-z]?)(?:\s*\([^)]*\))*\s*\]",
    re.IGNORECASE,
)

# Act preceding a section: e.g. "under the Pakistan Penal Code, Section 302"
_ACT_SECTION_PATTERN = re.compile(
    r"\b([A-Za-z0-9\s,\.\-—–]+?\b(?:Act|Code|Ordinance)[,\s\d]*?)[,\s\-]+Section\s+(\d+[A-Za-z]?)(?:\s*\([^)]*\))*",
    re.IGNORECASE,
)

# Bare section pattern: "Section 15", "section 302A"
_BARE_SECTION_PATTERN = re.compile(
    r"\bSection\s+(\d+[A-Za-z]?)(?:\s*\([^)]*\))*",
    re.IGNORECASE,
)


def normalize_act_name(act_str: str | None) -> str:
    """
    Map an Act string (e.g. 'Punjab Rented Premises Act, 2009', 'CrPC', 'PPC')
    to a registered law_id, or 'unknown'.
    """
    if not act_str:
        return "unknown"
    act_clean = act_str.strip().lower()

    # Direct match against registry titles / short titles
    for law_id, entry in registry.get_registry().items():
        title = entry.get("title", "").lower()
        short_title = entry.get("short_title", "").lower()
        if short_title and (short_title in act_clean or act_clean in short_title):
            return law_id
        if title and (title in act_clean or act_clean in title):
            return law_id

    # Canonical aliases
    if "penal code" in act_clean or act_clean == "ppc":
        return "ppc_1860"
    if "criminal procedure" in act_clean or act_clean == "crpc":
        return "crpc_1898"
    if "electronic crimes" in act_clean or act_clean == "peca":
        return "peca_2016"
    if "rented premises" in act_clean or "tenancy" in act_clean:
        return "tenancy_punjab_2009"
    if "consumer" in act_clean:
        return "punjab_consumer_2005"
    if "muslim family laws" in act_clean or act_clean == "mflo":
        return "mflo_1961"
    if "family court" in act_clean:
        return "family_courts_1964"
    if "dissolution of muslim marriages" in act_clean or act_clean == "dmma":
        return "dmma_1939"

    return "unknown"


def parse_citations(text: str) -> list[dict]:
    """
    Parse all statutory citations from text.

    Returns a list of dicts:
        [
            {
                "law_id": str,          # normalized law_id or 'unknown'
                "section": str,         # e.g. '15', '302', '2'
                "raw": str,             # matched substring
                "act_name": str | None, # raw act name if captured
                "span": tuple[int, int] # character offsets in text
            },
            ...
        ]
    """
    citations: list[dict] = []
    covered_spans: list[tuple[int, int]] = []

    def _is_covered(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in covered_spans)

    # 1. Bracketed citations: [Act Name - Section X(y)]
    for m in _BRACKET_PATTERN.finditer(text):
        raw = m.group(0)
        act_raw = m.group(1).strip()
        sec = m.group(2).upper()
        law_id = normalize_act_name(act_raw)
        span = (m.start(), m.end())
        covered_spans.append(span)
        citations.append({
            "law_id": law_id,
            "section": sec,
            "raw": raw,
            "act_name": act_raw,
            "span": span,
        })

    # 2. Act preceding section: "Pakistan Penal Code Section 302"
    for m in _ACT_SECTION_PATTERN.finditer(text):
        if _is_covered(m.start(), m.end()):
            continue
        raw = m.group(0)
        act_raw = m.group(1).strip()
        sec = m.group(2).upper()
        law_id = normalize_act_name(act_raw)
        span = (m.start(), m.end())
        covered_spans.append(span)
        citations.append({
            "law_id": law_id,
            "section": sec,
            "raw": raw,
            "act_name": act_raw,
            "span": span,
        })

    # 3. Bare sections: "Section 15"
    for m in _BARE_SECTION_PATTERN.finditer(text):
        if _is_covered(m.start(), m.end()):
            continue
        sec = m.group(1).upper()
        span = (m.start(), m.end())
        citations.append({
            "law_id": "unknown",
            "section": sec,
            "raw": m.group(0),
            "act_name": None,
            "span": span,
        })

    return citations


_CROSS_REF_PATTERN = re.compile(
    r"\b(?:sections?|sec\.?)\s+(\d+[A-Za-z]?(?:\s*(?:,|and|or)\s*\d+[A-Za-z]?)*)",
    re.IGNORECASE,
)


def validate_citations_grounding(
    citations: list[dict],
    retrieved_chunks: list[dict],
) -> dict:
    """
    Check parsed citations against retrieved chunk metadata and chunk body text cross-references.

    A cite is supported if:
    1. That (law_id, section) appears in retrieved chunk metadata.
    2. OR that section appears in retrieved metadata of at least one chunk (if law_id unknown).
    3. OR that section number appears explicitly cross-referenced in the retrieved body text
       of a chunk belonging to that same law_id (or any chunk if law_id unknown).
       (Statutory provisions frequently cross-reference other sections within the same Act,
       e.g., Section 15(b) referring to "the period stipulated in section 7").

    Returns:
        {
            "supported": list[dict],
            "unsupported": list[dict],
        }
    """
    retrieved_pairs: set[tuple[str, str]] = set()
    retrieved_sections: set[str] = set()

    for c in retrieved_chunks:
        meta = c.get("metadata") or {}
        lid = meta.get("law_id")
        sec = str(meta.get("section_number", "")).strip().upper()
        if sec:
            retrieved_sections.add(sec)
            if lid:
                retrieved_pairs.add((lid, sec))

        # Also extract statutory section cross-references from the chunk body text
        chunk_text = c.get("text") or c.get("document") or ""
        if chunk_text:
            for match in _CROSS_REF_PATTERN.finditer(chunk_text):
                for ref_num in re.findall(r"\b\d+[A-Za-z]?\b", match.group(1)):
                    ref_sec = ref_num.upper()
                    retrieved_sections.add(ref_sec)
                    if lid:
                        retrieved_pairs.add((lid, ref_sec))

    supported: list[dict] = []
    unsupported: list[dict] = []

    for cite in citations:
        lid = cite["law_id"]
        sec = cite["section"]
        if lid != "unknown":
            if (lid, sec) in retrieved_pairs:
                supported.append(cite)
            else:
                unsupported.append(cite)
        else:
            if sec in retrieved_sections:
                supported.append(cite)
            else:
                unsupported.append(cite)

    return {
        "supported": supported,
        "unsupported": unsupported,
    }


def strip_or_footnote_unsupported(
    answer: str,
    unsupported_cites: list[dict],
) -> str:
    """
    Remove unsupported citations and any sentences that contain only
    unsupported statutory citations from the user-visible answer.
    """
    if not unsupported_cites:
        return answer

    # Identify raw strings of unsupported citations
    unsupported_raws = {c["raw"] for c in unsupported_cites}
    unsupported_secs = sorted({c["section"] for c in unsupported_cites})

    # Split answer into lines (paragraphs / list items)
    lines = answer.split("\n")
    cleaned_lines = []
    stripped_any = False

    for line in lines:
        line_has_unsupported = any(raw in line for raw in unsupported_raws)
        if not line_has_unsupported:
            cleaned_lines.append(line)
            continue

        # Check if line contains any other citation that IS supported
        line_citations = parse_citations(line)
        has_supported = any(c["raw"] not in unsupported_raws for c in line_citations)

        if has_supported:
            # Line has mixed citations: strip only the unsupported citation tokens
            new_line = line
            for raw in unsupported_raws:
                new_line = new_line.replace(raw, "").strip()
            cleaned_lines.append(new_line)
            stripped_any = True
        else:
            # Line only contains unsupported citation(s): strip the entire line
            stripped_any = True

    cleaned_answer = "\n".join(cleaned_lines).strip()
    if not cleaned_answer:
        cleaned_answer = (
            "The retrieved statutory provisions do not support this query. "
            "Please consult a qualified advocate."
        )

    if stripped_any:
        note = (
            f"\n\n*(Note: References to Section(s) {', '.join(unsupported_secs)} "
            "were removed as they were not supported by the retrieved statutory provisions.)*"
        )
        # Place note before disclaimer if disclaimer is present
        if "\n\n---\n**Disclaimer:**" in cleaned_answer:
            parts = cleaned_answer.split("\n\n---\n**Disclaimer:**", 1)
            cleaned_answer = parts[0] + note + "\n\n---\n**Disclaimer:**" + parts[1]
        elif "\n\n---\n" in cleaned_answer:
            parts = cleaned_answer.split("\n\n---\n", 1)
            cleaned_answer = parts[0] + note + "\n\n---\n" + parts[1]
        else:
            cleaned_answer += note

    return cleaned_answer

