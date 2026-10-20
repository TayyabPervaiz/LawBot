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
        # Starting point: verify against the real file before validation.
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Za-z]?)\.\s+(.+)",
        "hint_keywords": [
            "cybercrime", "online", "electronic", "fia", "peca", "hacking",
            "harassment", "whatsapp", "facebook", "social media", "data",
            "unauthorized access", "spamming", "spoofing",
        ],
        "always_include_sections": [],  # owner fills after download
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },

    # ---- Family laws (Phase 2C) ----
    "mflo_1961": {
        "title": "The Muslim Family Laws Ordinance, 1961",
        "short_title": "MFLO 1961",
        "year": 1961,
        "jurisdiction": "Federal",
        "category": "family",
        "file": "family/muslim_family_laws_ordinance_1961.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Za-z]?)\.\s+(.+)",
        "hint_keywords": [
            "nikah", "nikkah", "marriage", "talaq", "divorce", "dower",
            "meher", "mahr", "maintenance", "registration", "marriage registrar",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },
    "family_courts_1964": {
        "title": "The Family Courts Act, 1964",
        "short_title": "Family Courts Act 1964",
        "year": 1964,
        "jurisdiction": "Federal",
        "category": "family",
        "file": "family/family_courts_act_1964.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Za-z]?)\.\s+(.+)",
        "hint_keywords": [
            "family court", "custody", "guardian", "dowry", "file a case",
            "jurisdiction", "petition", "suit",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },
    "dmma_1939": {
        "title": "The Dissolution of Muslim Marriages Act, 1939",
        "short_title": "DMMA 1939",
        "year": 1939,
        "jurisdiction": "Federal",
        "category": "family",
        "file": "family/dissolution_of_muslim_marriages_act_1939.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Za-z]?)\.\s+(.+)",
        "hint_keywords": [
            "khula", "dissolution", "decree", "grounds for dissolution",
            "cruelty", "apostasy", "judicial khula",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },

    # ---- Criminal laws (Phase 2D — extra care) ----
    "ppc_1860": {
        "title": "The Pakistan Penal Code, 1860",
        "short_title": "Pakistan Penal Code",
        "year": 1860,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/pakistan_penal_code_1860.txt",
        # PPC uses "302. Punishment for murder" style. This pattern is a
        # starting point ONLY — numbered list items/illustrations inside a
        # section will false-positive on it; parser validation reports this.
        "section_pattern": r"^(\d+[A-Z]?)\.\s+([A-Z].+)",
        "hint_keywords": [
            "theft", "murder", "assault", "fraud", "defamation", "offence",
            "punishment", "cheating", "criminal breach of trust",
            "hurt", "kidnap", "robbery", "extortion",
        ],
        "always_include_sections": [],  # owner lists definition sections
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },
    "crpc_1898": {
        "title": "The Code of Criminal Procedure, 1898",
        "short_title": "CrPC 1898",
        "year": 1898,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/code_of_criminal_procedure_1898.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Z]?)\.\s+([A-Z].+)",
        "hint_keywords": [
            "fir", "first information report", "bail", "arrest", "warrant",
            "magistrate", "investigation", "police", "trial", "summons",
            "sessions court", "cognizable",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },

    # ---- Consumer (later stage) ----
    "punjab_consumer_2005": {
        "title": "The Punjab Consumer Protection Act, 2005",
        "short_title": "Punjab Consumer Protection Act",
        "year": 2005,
        "jurisdiction": "Punjab",
        "category": "consumer",
        "file": "consumer/punjab_consumer_protection_act_2005.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Za-z]?)\.\s+(.+)",
        "hint_keywords": [
            "consumer", "product", "refund", "warranty", "defective",
            "complaint", "deceptive practice",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },

    # ---- Tenancy (existing; text pending official replacement — see
    # data/processed/step0_tenancy_audit.md) ----
    "tenancy_punjab_2009": {
        "title": "The Punjab Rented Premises Act, 2009",
        "short_title": "Punjab Rented Premises Act",
        "year": 2009,
        "jurisdiction": "Punjab",
        "category": "tenancy",
        "file": "tenancy_punjab/punjab_rented_premises_act_2009.txt",
        "section_pattern": r"^Section\s+(\d+[A-Za-z]?)\.\s*(.*)",
        "hint_keywords": [
            "tenant", "landlord", "rent", "evict", "eviction", "tenancy",
            "lease", "rented premises", "security deposit", "rent tribunal",
            "rent registrar", "sublet",
        ],
        "always_include_sections": [],
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": 36,  # genuine Act has 36 sections (Step 0 audit)
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
