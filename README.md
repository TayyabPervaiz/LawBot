# 🏛️ Pakistan Law Bot — AI Legal Information Assistant

An AI-powered legal information assistant for Pakistani citizens. Phase 1 (Punjab Tenancy & Rent Law — *The Punjab Rented Premises Act, 2009*) proved the RAG core; **Phase 2 is the multi-law platform** per the revised plan (`NEXT_PHASE_PLAN_Revised .md`): registry-driven parsing with owner-gated validation, hybrid retrieval over ALL loaded laws, dynamic guardrail prompts, and a stage-aware benchmark.

> ⚠️ **Disclaimer**: This tool provides legal **information**, not legal **advice**. Always consult a qualified advocate for your specific legal situation.

---

## ✨ Features

- **Accurate Statutory Citations**: Every answer cites the exact Act and Section number
- **Anti-Hallucination Guardrails**: Explicitly declares when information is not available rather than guessing
- **Scope Enforcement**: Politely refuses out-of-scope queries (criminal law, family law, cybercrime, foreign law)
- **100% Free**: Runs on local embeddings, local vector storage, and free LLM APIs
- **Expandable**: Modular architecture designed to add new legal acts easily

---

## 🏗️ Architecture

```text
User Question
     │
     ▼
┌─────────────────┐
│   src/bot.py     │  ← Query Interface
│   (Orchestrator) │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ src/vector_store.py  │  ← Finds relevant law sections
│ (ChromaDB + Local    │     using semantic similarity
│  Sentence-Transformers)│
└────────┬────────────┘
         │ Top-K relevant sections
         ▼
┌─────────────────────┐
│  src/generator.py    │  ← Generates grounded answer
│  (Groq API / Ollama) │     with strict citation rules
│  + Guardrail Engine  │     and anti-hallucination
└─────────────────────┘
```

---

## 🛠️ Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Embeddings | `sentence-transformers` (**multilingual**: paraphrase-multilingual-MiniLM-L12-v2 — chosen in Phase 2A so Urdu needs no re-index) | Free (local) |
| Vector Store | ChromaDB (one collection, `law_id` metadata) | Free (local) |
| Retrieval | Hybrid: vector + BM25 fused by RRF, relevance threshold, soft hints | Free (local) |
| LLM | Groq Cloud API (`llama-3.3-70b-versatile`), answer caching + backoff | Free tier |
| Language | Python 3.10+ | Free |

---

## 🚀 Setup Instructions

### 1. Clone and Install

```bash
git clone <repository-url>
cd LawBot

# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Key

```bash
# Copy the example environment file
copy .env.example .env

# Edit .env and add your free Groq API key
# Get one at: https://console.groq.com/keys
```

### 3. Add law text (OWNER ONLY — the model never supplies law text)

1. Download the official PDF (Pakistan Code for federal laws, punjabcode.punjab.gov.pk for Punjab laws) into `data/source_pdfs/<category>/`.
2. Extract with the provided tool (it extracts — it never retypes):

```bash
python -m src.extract_pdf data/source_pdfs/tenancy_punjab/the_act.pdf -o data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt
```

Pages without a text layer are flagged as scanned (OCR needed — do not hand-type).

### 4. Parse + validate, then index (after your review)

```bash
# Parse the registered law files into validated chunks
# (writes data/processed/chunks.json + data/processed/validation_report.txt
#  — review the report BEFORE indexing)
python -m src.parser

# Build the vector search index (ONLY after you accept the validation report)
python -m src.bot --index
```

> ⚠️ **Do not run `python -m src.vector_store` directly to index.** Its
> `__main__` is a module self-test that resets the collection.

### 5. Run the Assistant

```bash
# Start the interactive CLI
python -m src.bot
```

---

## 📊 Evaluation

```bash
python -m pytest tests/            # 65 offline tests: registry, parser, retrieval, guardrails, evaluator
python -m tests.evaluate --offline # dataset + stage-logic sanity (no API key)
python -m tests.evaluate           # full benchmark (API key + index)
python -m tests.evaluate --help    # (use tests/evaluate.py flags)
```

The benchmark (106 questions) is **stage-aware**: a question is expected to be a refusal
until the law in its `answered_by` list is loaded, then expected to answer. Reported
accuracy counts **owner-verified questions only** (`verified_by` set) — currently ALL are
unverified until the official texts are swapped in (Rule 5 of the plan), so an empty
"verified" column is the honest starting point, not a failure.

---

## 📁 Project Structure

```text
LawBot/
├── data/
│   ├── source_pdfs/<category>/      # OWNER: untouched official PDF downloads (never indexed)
│   ├── raw/<category>/              # CLEAN UTF-8 .txt files — the ONLY folder the parser reads
│   ├── processed/                   # Generated: chunks.json, validation_report.txt, llm_cache.json
│   └── chroma_db/                   # Generated: vector database
├── src/
│   ├── config.py                    # Paths + retrieval/LLM settings (no law names here)
│   ├── law_registry.py              # THE registry: every law, its file, pattern, metadata
│   ├── parser.py                    # Registry-driven section-aware parser + validation report
│   ├── vector_store.py              # ChromaDB wrapper with local multilingual embeddings
│   ├── retrieval.py                 # Hybrid retrieval: vector + BM25 + RRF, threshold, hints
│   ├── generator.py                 # Dynamic guardrail prompt, refusals, answer cache
│   ├── extract_pdf.py               # OWNER tool: PDF → UTF-8 text (extraction only)
│   └── bot.py                       # Orchestration + CLI (--index / --ask)
├── tests/
│   ├── build_benchmark_dataset.py   # Regenerates benchmark_dataset.json (provenance of entries)
│   ├── benchmark_dataset.json       # 106 stage-aware questions (owner-verified ones count only)
│   ├── evaluate.py                  # Stage-aware harness (--offline-less: pytest cotask offline logic)
│   └── test_*.py                    # 65 offline pytest tests
├── .env.example
├── requirements.txt
└── README.md
```

---

## 📜 Supported Laws & Stage Status

> Registry-driven status: a law is loaded only when its registry file exists AND the
> parser validation report passes your review.

| Stage | Law | Status |
|---|---|---|
| Phase 1 | Punjab Rented Premises Act, 2009 | ⚠️ **Data audit FAILED** — current text is a 25-section abridgment, not the genuine 36-section Act. Owner: download official PDF (see `data/processed/step0_tenancy_audit.md`), then re-extract + re-validate |
| 2B pilot | Prevention of Electronic Crimes Act (PECA), 2016 | ⬜ Registered; awaiting owner download |
| 2C | Muslim Family Laws Ordinance 1961; Family Courts Act 1964; Dissolution of Muslim Marriages Act 1939 | ⬜ Registered; awaiting owner download |
| 2D (extra care) | Pakistan Penal Code 1860; CrPC 1898 | ⬜ Registered; awaiting owner download |
| Later | Punjab Consumer Protection Act 2005 | ⬜ Registered; awaiting owner download |

### OWNER CHECKLIST (blocking GATE 1)
1. Download the official Punjab Rented Premises Act 2009 PDF → `data/source_pdfs/tenancy_punjab/`
2. `python -m src.extract_pdf ...` → `data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt`
3. Tell the model to run `python -m src.parser` and review `data/processed/validation_report.txt`
4. Fill registry provenance (`source_url`, `amended_up_to`, `expected_section_count`) in `src/law_registry.py`
5. Verify benchmark questions (`verified_by/verified_on/verification_source`) — unverified ones don't count

---

## 🤝 Contributing (adding a new law)

1. Register the law in `src/law_registry.py` (file, section pattern, keywords)
2. Owner downloads the official PDF → `data/source_pdfs/<category>/`; extract with `src.extract_pdf` → `data/raw/<category>/`
3. Run `python -m src.parser`; owner reviews `data/processed/validation_report.txt` (count/order/spot checks)
4. Fill provenance fields + expected_section_count in the registry
5. Add benchmark questions via `tests/build_benchmark_dataset.py` (regenerates `tests/benchmark_dataset.json`); owner verifies them
6. Only then index and re-run the benchmark

---

## 📄 License

This project is open source and free for all Pakistani citizens.

---

*Built with the goal of making legal information accessible to every Pakistani citizen. 🇵🇰*
