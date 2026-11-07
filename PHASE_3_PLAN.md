# Phase 3 Implementation Plan: User Experience & Multilingual Expansion

**Date:** 2026-11-07  
**Status:** In Execution  
**Predecessor Gate:** Phase 2 Complete (114/114 Verified Questions Passing, 92/92 Pytest Regression Tests Passing)  

---

## 1. Executive Summary & Objectives

Phase 2 established a verified, strictly grounded legal intelligence engine across all 8 target Pakistani statutory Acts with 100.0% benchmark accuracy and zero fabricated citations.

**Phase 3 shifts focus to User Experience (UX), Channels, and Multilingual Accessibility:**
1. **Task 3-1: Web Interface & Product UX**
   - Lightweight, zero-dependency multi-threaded production server (`src/server.py`) serving a modern responsive web client (`static/index.html`, `static/style.css`, `static/app.js`).
   - Alternate Streamlit application (`app_streamlit.py`) for data science & rapid prototyping environments.
   - Real-time knowledge base telemetry (`/api/stats`, `/api/laws`), statutory citation inspection, copy-to-clipboard, and session management.
2. **Task 3-2: Multilingual Support (Urdu Script & Roman Urdu)**
   - Cross-lingual dense retrieval verification using `paraphrase-multilingual-MiniLM-L12-v2`.
   - Comprehensive Urdu script (اردو) and Roman Urdu legal synonyms and query expansions in `src/retrieval.py`.
   - Urdu script and Roman Urdu out-of-scope patterns in `src/generator.py` (tax, foreign law).
   - Dedicated multilingual benchmark dataset (`tests/benchmark_multilingual.json`) and automated test suite (`tests/test_multilingual.py`).
3. **Task 3-3: Conversational Memory & Multi-turn Follow-ups**
   - Context-aware retrieval expansion for short follow-ups in English, Roman Urdu ("aur agar wo na mane?"), and Urdu script ("اور اگر مالک انکار کرے؟").
   - Preserves session history across turns without context dilution.
4. **Task 3-4: Messaging Channels (WhatsApp / Twilio Webhook)**
   - Zero-dependency Twilio WhatsApp webhook endpoint in `src/server.py` (`POST /api/webhook/twilio`).
   - Clean statutory WhatsApp formatting with disclaimer and TwiML XML output.
5. **Task 3-5: Response Caching & Rate-Limit Resilience**
   - Sub-millisecond instant retrieval for repeated queries via `data/processed/llm_cache.json`.
   - \$0 operating cost guarantee on Groq free-tier with exponential backoff on HTTP 429.

---

## 2. Architecture & Components

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                                USER INTERFACES                                    │
│                                                                                   │
│   Web Browser (HTML5/CSS3/JS)       WhatsApp (Twilio Webhook)      Streamlit App  │
│        (static/index.html)            (POST /api/webhook/twilio)   (app_streamlit)│
└─────────────────────────┬─────────────────────────┬───────────────────────┬───────┘
                          │                         │                       │
                          ▼                         ▼                       │
┌───────────────────────────────────────────────────┐                       │
│             LIGHTWEIGHT HTTP SERVER               │                       │
│                 (src/server.py)                   │                       │
│    - GET  /api/health                             │                       │
│    - GET  /api/laws (Metadata for 8 Acts)         │                       │
│    - GET  /api/stats (Indexed chunk counts)       │                       │
│    - POST /api/ask (RAG Orchestration)            │                       │
│    - POST /api/webhook/twilio (WhatsApp TwiML)    │                       │
└─────────────────────────┬─────────────────────────┘                       │
                          │                                                 │
                          └────────────────────────┬────────────────────────┘
                                                   ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              CORE PIPELINE (src/bot.py)                           │
│                                                                                   │
│  1. Multilingual Scope Filter (src/generator.py detect_scope)                     │
│     - English, Roman Urdu, Urdu Script Out-of-Scope Patterns                      │
│                                                                                   │
│  2. Conversational Contextualizer                                                 │
│     - English & Urdu follow-up detection (_is_followup_query)                     │
│                                                                                   │
│  3. Hybrid Cross-Lingual Retrieval (src/retrieval.py)                             │
│     - Multilingual MiniLM Vector Search (1,635 Chunks)                            │
│     - Trilingual Legal Synonyms (EN, Roman Urdu, Urdu Script)                     │
│     - BM25 Lexical Re-ranking + Province/Jurisdiction Matching                    │
│     - Linked Statutory Definition Injection                                       │
│                                                                                   │
│  4. Grounded Generation & Guardrails (src/generator.py)                           │
│     - Dynamic System Prompt (Laws in context)                                     │
│     - Language Preservation (Urdu, Roman Urdu, English)                           │
│     - Statutory Citation Extraction & Grounding Verification                      │
│     - Mandatory Statutory Disclaimer                                              │
│     - LRU Deterministic Response Cache                                            │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Implementation Steps

| Step | Component | Description |
|---|---|---|
| **Step 3.1** | `src/generator.py` | Add Urdu & Roman Urdu patterns to `OUT_OF_SCOPE_PATTERNS` for tax and foreign jurisdictions. |
| **Step 3.2** | `src/retrieval.py` | Expand `LEGAL_SYNONYMS` with comprehensive Urdu script and Roman Urdu terms across all 8 Acts. |
| **Step 3.3** | `src/bot.py` | Expand `_FOLLOWUP_PHRASES` with Roman Urdu and Urdu script conversational triggers. |
| **Step 3.4** | `src/server.py` | Add `POST /api/webhook/twilio` endpoint for WhatsApp integration with TwiML XML formatting. |
| **Step 3.5** | `app_streamlit.py` | Create a standalone Streamlit chat interface with citation inspector and coverage drawer. |
| **Step 3.6** | `tests/benchmark_multilingual.json` | Construct 20+ verified multilingual benchmark questions across all 8 Acts + out-of-scope. |
| **Step 3.7** | `tests/test_multilingual.py` | Unit and integration tests verifying cross-lingual retrieval, Urdu/Roman Urdu answers, and out-of-scope refusals. |
| **Step 3.8** | Full Regression Run | Run `pytest tests/` and verify 100% pass across all existing (92) and new tests. |
| **Step 3.9** | Documentation & Report | Update `README.md` and generate `PHASE_3_REPORT.md`. |

---

## 4. Definition of Done (DoD)

- [ ] All Urdu and Roman Urdu legal terms recognized in retrieval and out-of-scope filters.
- [ ] Multilingual benchmark suite passes 100% of retrieval and refusal checks.
- [ ] WhatsApp webhook handles incoming queries and formats response with statutory citations.
- [ ] Streamlit interface runs cleanly or provides clear guidance if installed.
- [ ] Full regression test suite passes with zero failures.
- [ ] All code adheres strictly to $0 budget (Groq free tier + local embeddings).

