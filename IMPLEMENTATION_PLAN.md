# Implementation Plan: AI Legal Assistant for Pakistani Citizens (Core Proof-of-Concept)

## Context & Objectives
The goal of this project is to build an accurate, trustworthy, and **100% free ($0 cost)** AI legal information assistant for Pakistani citizens. 

To ensure the core works with high precision before investing in user interfaces or messaging channels:
- **Scope**: Focus strictly on **Punjab Tenancy & Rent Law** (The Punjab Rented Premises Act, 2009). The architecture will be strictly modular so new legal acts (e.g., Pakistan Penal Code, Family Courts Act, PECA) can be added seamlessly by dropping documents into the pipeline.
- **Language**: English first for the core logic. (Urdu & Roman Urdu to follow after verification).
- **Core Requirements**:
  1. **Strict statutory citations**: Every answer must identify the exact Act and Section (e.g., Section 15 of Punjab Rented Premises Act, 2009).
  2. **Zero guessing / Anti-hallucination**: Explicitly declare when a matter is not covered or unsure.
  3. **Scope enforcement**: Politely refuse out-of-scope legal queries (criminal law, family law, federal tax, foreign law).
  4. **Rigorous benchmark evaluation**: An automated test harness with ground-truth citations to measure accuracy before expanding.
  5. **100% Free**: Uses local open-source embeddings, local vector storage, and free LLM inference.

---

## 1. Official Data Acquisition & Directory Structure

### 1.1 Official Source
The primary official source for Punjab laws is the official Government of the Punjab legislative repository:
- **Portal**: [Punjab Code (punjabcode.punjab.gov.pk)](https://punjabcode.punjab.gov.pk)
- **Target Document**: **The Punjab Rented Premises Act, 2009** (Punjab Act VII of 2009).
  - Also recommended companion: The Punjab Rented Premises Rules, 2010.

### 1.2 Step-by-Step Acquisition Instructions
1. Visit `https://punjabcode.punjab.gov.pk/`.
2. Search for `Punjab Rented Premises Act 2009`.
3. Open the full text view of the Act (consisting of 36 sections divided into Chapters: Preliminary, Creation of Tenancy, Obligations of Parties, Rent Tribunals, Procedure, Eviction, Miscellaneous).
4. Save the text as clean UTF-8 text or PDF.

### 1.3 Project Folder Structure
```text
C:\Users\tayya\pakistan-law-bot\
├── data\
│   ├── raw\
│   │   └── tenancy_punjab\
│   │       ├── punjab_rented_premises_act_2009.txt
│   │       └── punjab_rented_premises_rules_2010.txt
│   ├── processed\
│   │   └── chunks.json
│   └── chroma_db\               # Local persistent vector database
├── src\
│   ├── __init__.py
│   ├── config.py                # Configuration and environment settings
│   ├── parser.py                # Legal section-aware chunker
│   ├── vector_store.py          # ChromaDB & local sentence-transformers
│   ├── generator.py             # Strict RAG prompt & free LLM engine
│   └── bot.py                   # Main legal assistant query interface
├── tests\
│   ├── benchmark_dataset.json   # Benchmark questions & ground truth citations
│   └── evaluate.py              # Automated accuracy & refusal test harness
├── requirements.txt
└── README.md
```

---

## 2. 100% Free Technology Stack ($0 Cost)

1. **Embeddings**: `sentence-transformers` using `all-MiniLM-L6-v2` or `BAAI/bge-small-en-v1.5`
   - Runs locally on CPU/device. 100% free, zero API cost, zero rate limits.
2. **Vector Store**: `ChromaDB`
   - Embedded local vector store saved directly in the project folder. Zero hosting cost.
3. **LLM Engine (Free Tier)**:
   - **Primary**: **Groq Cloud API** (free tier providing `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`). Extremely fast, high legal reasoning capabilities, completely free API key.
   - **Alternative / Offline**: **Ollama** (running `llama3.2:3b` locally on Windows with no internet or API key required).
4. **Environment**: Python 3.10+ on Windows.

---

## 3. Legal Section-Aware Chunking Strategy

Legal texts cannot be chunked using naive character counts (e.g. 500 characters) because standard splitters sever sections, subsections, and definitions mid-sentence.

In `src/parser.py`, we implement a **Section-Aware Chunker**:
1. Uses regex to detect statutory boundaries: `^Section\s+(\d+[A-Za-z]?)\.?\s*(.*?)(?=\nSection\s+\d+|\Z)`.
2. Extracts metadata for each chunk:
   - `law_title`: "The Punjab Rented Premises Act, 2009"
   - `section_number`: e.g., "15"
   - `section_title`: e.g., "Application for eviction"
   - `chapter`: e.g., "Chapter V: Eviction"
   - `text`: Complete text of the section including subsections and provisos.
3. For exceptionally long sections (e.g., Section 15 or Section 2), splits by subsection while retaining parent section title and metadata in the context header.

---

## 4. Grounded RAG & Strict Guardrail Engine

In `src/generator.py`:
1. **System Prompt Rules**:
   - Act as an objective, strictly grounded Pakistani Legal Information Specialist.
   - **Citation Rule**: Every factual statement must cite the specific Act and Section (e.g., `[Punjab Rented Premises Act, 2009 - Section 15(a)]`).
   - **Uncertainty Rule**: If the retrieved statutory provisions do not explicitly answer the question, state: *"The provided provisions of the Punjab Rented Premises Act, 2009 do not address this specific issue. Please consult an advocate."* Do NOT extrapolate or guess.
   - **Out-of-Scope Rule**: If asked about criminal law, divorce/family law, cybercrime, or non-Pakistani law, reply: *"This assistant is currently specialized in Punjab Tenancy and Rent Law. Your question regarding [Topic] is outside this scope."*
   - **Mandatory Legal Disclaimer**: Every response concludes with a short disclaimer clarifying this is legal information, not formal legal advice.

2. **Core Legal Knowledge Points Grounded in the Act**:
   - **Eviction without notice (Section 15)**: Landlord cannot forcibly or summarily evict. Must file an application before the Rent Tribunal on statutory grounds (default in rent, period expiry, breach of agreement, subletting, bona fide personal use).
   - **Rent Increase (Section 6 & 10)**: Rent can only be increased if stipulated in the written agreement registered with the Rent Registrar. Unilateral or arbitrary hikes outside the tenancy agreement terms are unlawful.
   - **Security Deposit (Section 6 & 7)**: Refundable at the conclusion of tenancy, subject to valid contractual deductions.
   - **Registration requirement (Section 5)**: Tenancy agreements must be in writing and registered with the Rent Registrar.

---

## 5. Evaluation Benchmark & Accuracy Test Suite

Before building any frontend, we validate the core against a deterministic test suite (`tests/evaluate.py`):

| # | Test Question | Type | Expected Citation / Behavior |
|---|---|---|---|
| 1 | "Can my landlord evict me without notice?" | In-scope | Section 15 (Must file application before Rent Tribunal; specify grounds) |
| 2 | "Can my landlord increase rent whenever he wants?" | In-scope | Section 6 & 10 (Only per registered agreement terms) |
| 3 | "Does my landlord have to return my security deposit?" | In-scope | Section 6 (Agreement terms & refund on determination) |
| 4 | "Is a verbal tenancy agreement valid in Punjab?" | In-scope | Section 5 (Tenancy must be in writing and registered) |
| 5 | "What are the grounds for eviction of a tenant?" | In-scope | Section 15 (Default, expiry, breach, subletting, etc.) |
| 6 | "Can the landlord shut off my electricity or water if I delay rent?" | In-scope | Section 13 (Landlord cannot cut off essential amenities) |
| 7 | "How do I file an FIR for motorcycle theft?" | Out-of-scope | Refusal + Scope Boundary (Criminal law / CrPC) |
| 8 | "What is the procedure for Khula under Pakistani law?" | Out-of-scope | Refusal + Scope Boundary (Family Law) |
| 9 | "How to report harassment on WhatsApp to FIA?" | Out-of-scope | Refusal + Scope Boundary (PECA 2016 / Cybercrime) |
| 10 | "Can my landlord kick me out in London?" | Out-of-scope | Refusal + Scope Boundary (Non-Pakistani jurisdiction) |

### Metrics Tracked:
- **Citation Precision**: % of in-scope answers citing the correct statutory section.
- **Refusal Accuracy**: % of out-of-scope questions refused without hallucinating.
- **Uncertainty Calibration**: Correct refusal when a question cannot be resolved from the text.

---

## 6. Execution Plan & Milestones

1. **Milestone 1**: Project Setup & Virtual Environment (`requirements.txt` with `chromadb`, `sentence-transformers`, `groq`, `python-dotenv`).
2. **Milestone 2**: Ingest Official Law Text (`data/raw/punjab_rented_premises_act_2009.txt`).
3. **Milestone 3**: Build Section-Aware Parser (`src/parser.py`) & verify chunk boundaries.
4. **Milestone 4**: Build Local Vector Store (`src/vector_store.py`) with local sentence-transformers.
5. **Milestone 5**: Build RAG Pipeline & Guardrails (`src/generator.py` and `src/bot.py`).
6. **Milestone 6**: Run Automated Benchmark Suite (`tests/evaluate.py`) and verify 100% citation & refusal accuracy.

---

## 7. Verification Steps
- Run `python -m src.parser` to confirm all 36 sections are cleanly extracted with titles and numbers.
- Run `python -m src.vector_store` to index into local ChromaDB.
- Run `python -m tests.evaluate` to execute the 10 benchmark test questions and verify accuracy metrics.
- Run interactive CLI `python -m src.bot` to test real queries interactively.
