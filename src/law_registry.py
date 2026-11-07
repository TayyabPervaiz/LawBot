"""
Central Law Registry for the Pakistan Law Bot (revised plan Section 5.2).

Every law is an entry keyed by law_id, one entry per FILE. The parser,
retrieval, prompts, refusals, and the benchmark harness all read their
law-specific configuration from here. NOTHING else in the codebase may
hardcode law names, section formats, or keywords.

Field discipline:
- title/short_title/year/jurisdiction/category/file: known metadata.
- section_pattern: a STARTING POINT only. The real downloaded text decides
  the final pattern; parser validation (Section 5.3) confirms it works.
- hint_keywords: soft retrieval hints ONLY. They never gate or exclude a law.
- source_url / downloaded_on / amended_up_to / expected_section_count:
  filled in BY THE OWNER after downloading (never guessed by a model).
- always_include_sections: owner lists definition sections found in the real
  text; retrieval appends these chunks when the law is used.

A law is "loaded" only if its raw text file exists on disk. Refusal messages
and the benchmark harness use the loaded list, never the full registry.
"""

import re
from pathlib import Path

from src.config import RAW_DATA_DIR


# ---------------------------------------------------------------------------
# Registry definition. Order = expansion order (pilot PECA first).
# ---------------------------------------------------------------------------

LAW_REGISTRY: dict[str, dict] = {
    # ---- Pilot law (Phase 2B) ----
    "peca_2016": {
        "title": "The Prevention of Electronic Crimes Act, 2016",
        "short_title": "PECA 2016",
        "year": 2016,
        "jurisdiction": "Federal",
        "category": "cybercrime",
        "file": "cybercrime/peca_2016.txt",
        # Validated against official Pakistan Code PDF (amended up to Act II of 2025):
        # matches 1..55, lettered sections (2A..2X, 22A..22C, 24A, 26A, 30A..30D, 43A, 45A, 50A, 51A),
        # footnote markers 1[29. ..., comma typos 1[26A, ..., and parenthesized headers (2E) ...
        "section_pattern": r"^\s*(?:\d+\[|\[)?\(?(\d+[A-Za-z]*?)(?:\)[\.,]?|[\.,])\s+([A-Z].*)",
        "hint_keywords": [
            "cybercrime", "online", "electronic", "fia", "peca", "hacking",
            "harassment", "whatsapp", "facebook", "social media", "data",
            "unauthorized access", "spamming", "spoofing",
        ],
        "always_include_sections": ["2"],  # Definitions section
        "source_url": "https://pakistancode.gov.pk",
        "downloaded_on": "2025-02",
        "amended_up_to": 2025,
        "expected_section_count": 92,
    },

    # ---- Family laws (Phase 2C) ----
    "mflo_1961": {
        "title": "The Muslim Family Laws Ordinance, 1961",
        "short_title": "MFLO 1961",
        "year": 1961,
        "jurisdiction": "Federal",
        "category": "family",
        "file": "family/muslim_family_laws_ordinance_1961.txt",
        # MFLO's ToC lines are *unnumbered* (e.g., "1 Short title" without a period),
        # so the pattern only matches the 13 body sections (e.g., "1. Short title...")
        # Sections 12 and 13 were omitted/repealed; their titles start with "[Amendment".
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+[A-Za-z]?)\.\s+([A-Z\[].*)",
        "hint_keywords": [
            "nikah", "nikkah", "marriage", "talaq", "divorce", "dower",
            "meher", "mahr", "haq mehr", "maintenance", "nafaqah",
            "registration", "marriage registrar", "nikah registrar",
            "arbitration council", "polygamy", "second wife",
            "succession", "inheritance",
        ],
        "always_include_sections": ["2"],  # Definitions (Arbitration Council, Chairman)
        "has_toc": False,  # MFLO file has no ToC block; section headings appear once
        "source_url": "https://pakistancode.gov.pk",
        "downloaded_on": "2026-10-21",
        "amended_up_to": None,  # Owner to verify amendment date from official PDF
        "expected_section_count": 13,
    },
    "family_courts_1964": {
        "title": "The Family Courts Act, 1964",
        "short_title": "Family Courts Act 1964",
        "year": 1964,
        "jurisdiction": "Punjab",  # Punjab-specific re-enactment of WP Act XXXV of 1964
        "category": "family",
        "file": "family/family_courts_act_1964.txt",
        # FCA pattern must handle:
        #   plain:       "1. Short title...–"
        #   footnote:    "5[3.Establishment...–"
        #   hyphenated:  "25-A. Transfer...", "25-B. Stay..."
        #   lettered:    "12A. Cases...", "17A. Suit..."
        # The Schedule list items ("1. Dissolution", "2. Dower") are caught too but
        # are 'toc'-kind duplicates of body sections 1-10 → dropped by ToC filter.
        # '25-A' (ToC style) vs '25A' (body style) difference is flagged as a
        # numbers_with_only_toc WARNING — expected source-text quirk, not a failure.
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+(?:-[A-Za-z]|[A-Za-z])?)\.[\s]*([A-Za-z].*)",
        "hint_keywords": [
            "family court", "custody", "guardian", "dowry", "khula",
            "file a case", "jurisdiction", "petition", "suit",
            "dissolution of marriage", "dower", "maintenance",
            "restitution of conjugal rights", "guardianship",
        ],
        "always_include_sections": ["2", "5", "SCHEDULE"],  # Definitions + Jurisdiction + Schedule
        "has_schedule": True,  # Statutory Schedule at the end holds exclusive jurisdiction list
        "source_url": "https://punjabcode.punjab.gov.pk",
        "downloaded_on": "2026-10-21",
        "amended_up_to": None,  # Owner to verify amendment date from official PDF
        # Sections: 1–26, 12A, 17A, 17B, 21A, 21B, 25A, 25-B = 33 sections + SCHEDULE = 34 total.
        "expected_section_count": 34,
    },
    "dmma_1939": {
        "title": "The Dissolution of Muslim Marriages Act, 1939",
        "short_title": "DMMA 1939",
        "year": 1939,
        "jurisdiction": "Federal",
        "category": "family",
        "file": "family/dissolution_of_muslim_marriages_act_1939.txt",
        # DMMA ToC lines are unnumbered ("1 Short title", "2 Grounds..."), so the
        # pattern matches body sections only (Sec 1–5 + Sec 6 [Repealed]).
        # Sec 6 title is "1[Repealed]." — the optional bracket prefix handles this.
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+[A-Za-z]?)\.\s+(?:\d+\[|\[)?([A-Za-z].*)",
        "hint_keywords": [
            "khula", "faskh", "dissolution", "judicial separation",
            "grounds for dissolution", "cruelty", "apostasy", "renunciation of islam",
            "husband whereabouts", "missing husband", "impotent",
            "maintenance failure", "dower", "right to dower",
        ],
        "always_include_sections": [],  # Sec 2 holds all dissolution grounds (large single section)
        "has_toc": False,  # DMMA file has no ToC block; section headings appear once
        "source_url": "https://pakistancode.gov.pk",
        "downloaded_on": "2026-10-21",
        "amended_up_to": None,  # Owner to verify from official PDF
        # ToC lists sections 1–5 (Sec 6 is [Repealed] and kept as a chunk).
        "expected_section_count": 6,
    },

    # ---- Criminal laws (Phase 2D — extra care) ----
    "ppc_1860": {
        "title": "The Pakistan Penal Code, 1860",
        "short_title": "Pakistan Penal Code",
        "year": 1860,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/pakistan_penal_code_1860.txt",
        # Validated pattern: matches body sections (1..511 plus lettered sections),
        # horizontal whitespace ensures page running headers (e.g. "92.\nExplanation")
        # are rejected. Footnote typo numbers (1500, 1501, 6366) are normalized.
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+[A-Za-z]?)\.[^\S\r\n]+([A-Za-z\"\'\[\?].*)",
        "body_start_marker": "[6th October, 1860]",
        "has_toc": False,  # body_start_marker cleanly bypasses the 14-page Table of Contents
        "hint_keywords": [
            "theft", "murder", "qatl", "assault", "fraud", "defamation", "offence",
            "punishment", "cheating", "criminal breach of trust", "diyat", "arsh",
            "hurt", "kidnap", "abduction", "robbery", "extortion", "dacoity",
            "criminal intimidation", "blasphemy", "rape", "zina", "forgery",
            "counterfeit", "conspiracy", "common intention", "dishonestly",
            "pakistan penal code", "ppc",
        ],
        "always_include_sections": ["34", "53"],  # Common Intention & Punishments
        "source_url": "https://pakistancode.gov.pk",
        "downloaded_on": "2026-10-23",
        "amended_up_to": 2017,  # Amended up to Act XLIV of 2016 (2017-02-16)
        "expected_section_count": 588,
    },
    "crpc_1898": {
        "title": "The Code of Criminal Procedure, 1898",
        "short_title": "CrPC 1898",
        "year": 1898,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/code_of_criminal_procedure_1898.txt",
        # Validated pattern: matches body sections (1..565 plus lettered sections like 164A, 241A, 265A, 561A),
        # normalizes OCR typo 4l7 -> 417 and footnote prefixes. Cuts off before Schedule I.
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+[A-Za-z0-9]?|\d+[lI]\d+)\.[^\S\r\n]+([A-Za-z\"\'\[].*)",
        "body_start_marker": "It is hereby enacted as follows:__",
        "sched_marker": "SCHEDULE I.__",
        "has_toc": False,  # body_start_marker cleanly bypasses Table of Contents
        "hint_keywords": [
            "fir", "first information report", "bail", "pre-arrest bail", "post-arrest bail",
            "arrest", "warrant", "magistrate", "investigation", "police", "trial",
            "summons", "sessions court", "cognizable", "non-cognizable", "remand",
            "police custody", "challan", "police report", "charge", "acquittal",
            "appeal", "quashment", "inherent power", "561a", "crpc",
        ],
        "always_include_sections": ["4"],  # Definitions section (cognizable, complaint, investigation, etc.)
        "source_url": "https://pakistancode.gov.pk",
        "downloaded_on": "2026-10-23",
        "amended_up_to": 2016,  # Amended up to Act XLIV of 2016
        "expected_section_count": 499,
    },

    # ---- Consumer (Phase 2E) ----
    "punjab_consumer_2005": {
        "title": "The Punjab Consumer Protection Act, 2005",
        "short_title": "Punjab Consumer Protection Act",
        "year": 2005,
        "jurisdiction": "Punjab",
        "category": "consumer",
        "file": "consumer/punjab_consumer_protection_act_2005.txt",
        # Pattern handles:
        #   plain:        "1. Short title...–"
        #   footnote:     "2[26. Consumer Courts.–" (amendment substitution marker)
        #   lettered:     "23-A. Powers of Government.–"
        # TOC section lines appear before PAGE 3 ("C O N T E N T S"); parser
        # skips them via the standard ToC-dedup logic.
        "section_pattern": r"^\s*(?:\d+\[|\[)?(\d+(?:-[A-Za-z]|[A-Za-z])?)\.\s+([A-Za-z].*)",
        "hint_keywords": [
            "consumer", "buyer", "purchaser", "product", "refund", "warranty",
            "defective product", "defective service", "faulty service",
            "consumer court", "consumer protection", "complaint", "claim",
            "bait advertisement", "false representation", "misleading",
            "manufacturer", "service provider", "damages", "penalty",
            "punjab consumer protection act",
        ],
        "always_include_sections": ["2"],  # Definitions section
        "source_url": "https://punjabcode.punjab.gov.pk",
        "downloaded_on": "2026-10-23",
        "amended_up_to": 2025,  # Punjab Consumer Protection (Amendment) Act 2025 (LIV of 2025)
        # Sections 1–39 plus lettered amendment 23-A = 40 total (verified from ToC and body).
        # Section 26 body is footnote-prefixed '2[26.' (2025 amendment substitution) — still counted.
        "expected_section_count": 40,
    },

    # ---- Tenancy (the only verified law; Step 0: 36 sections confirmed,
    # ToC and body agree. Owner-only provenance fields stay None until the
    # owner fills them from the downloaded PDF.) ----
    "tenancy_punjab_2009": {
        "title": "The Punjab Rented Premises Act, 2009",
        "short_title": "Punjab Rented Premises Act",
        "year": 2009,
        "jurisdiction": "Punjab",
        "category": "tenancy",
        "file": "tenancy_punjab/punjab_rented_premises_act_2009.txt",
        # Verified against the real file (Step 0): body headings are
        # "15. Grounds for eviction.– text..." (no "Section" prefix, title
        # followed by an en dash). ToC lines share the "15. Title" shape; the
        # parser skips them (Plan Section 5.3 point 3).
        "section_pattern": r"^(\d+[A-Za-z]?)\.\s*(.+)",
        "hint_keywords": [
            "tenant", "landlord", "rent", "evict", "eviction", "tenancy",
            "lease", "rented premises", "security deposit", "rent tribunal",
            "rent registrar", "sublet",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": 36,  # owner-confirmed at Step 0
    },
}


# ---------------------------------------------------------------------------
# Lookup helpers. Callers must treat the registry as read-only.
# ---------------------------------------------------------------------------

def get_registry() -> dict[str, dict]:
    """Return the full registry (all registered laws, loaded or not)."""
    return LAW_REGISTRY


def get_law(law_id: str) -> dict | None:
    """Get one registry entry by law_id, or None."""
    return LAW_REGISTRY.get(law_id)


def get_law_ids() -> list[str]:
    """All registered law_ids in registry order."""
    return list(LAW_REGISTRY.keys())


def is_loaded(law_id: str) -> bool:
    """A law is loaded iff its raw text file exists."""
    entry = LAW_REGISTRY.get(law_id)
    if not entry:
        return False
    return (RAW_DATA_DIR / entry["file"]).exists()


def loaded_laws() -> list[dict]:
    """All registry entries whose raw text file exists, in registry order."""
    return [entry for entry in LAW_REGISTRY.values() if is_loaded(
        next(k for k, v in LAW_REGISTRY.items() if v is entry)
    )]


def get_loaded_laws() -> dict[str, dict]:
    """All loaded laws as a dict mapping law_id -> entry metadata."""
    return {law_id: entry for law_id, entry in LAW_REGISTRY.items() if is_loaded(law_id)}


def loaded_law_ids() -> list[str]:
    """law_ids of all loaded laws."""
    return [
        law_id for law_id, entry in LAW_REGISTRY.items() if is_loaded(law_id)
    ]


def loaded_categories() -> set[str]:
    """Categories that have at least one loaded law."""
    return {
        entry["category"] for law_id, entry in LAW_REGISTRY.items()
        if is_loaded(law_id)
    }


def laws_in_category(category: str) -> list[str]:
    """law_ids of loaded laws in a category."""
    return [
        law_id for law_id, entry in LAW_REGISTRY.items()
        if entry["category"] == category and is_loaded(law_id)
    ]


def law_file_path(law_id: str) -> Path:
    """Absolute path of a law's raw text file."""
    return RAW_DATA_DIR / LAW_REGISTRY[law_id]["file"]


def short_title_by_id() -> dict[str, str]:
    """Convenience map law_id -> short_title (used in refusal messages)."""
    return {law_id: entry["short_title"] for law_id, entry in LAW_REGISTRY.items()}


def format_loaded_laws_for_refusal() -> str:
    """'The Punjab Rented Premises Act, 2009; The ...' line for refusal text."""
    entries = loaded_laws()
    titles = [e["title"] for e in entries]
    return "; ".join(titles) if titles else "no laws yet"
