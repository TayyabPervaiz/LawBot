# 🏛️ Pakistan Law Bot (قانون بوٹ) — Statutory AI Legal Assistant

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Tests Passing](https://img.shields.io/badge/Pytest-96%20Passed%20(100%25)-success.svg?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Accuracy](https://img.shields.io/badge/Benchmark-100%25%20Verified%20(114%2F114)-brightgreen.svg)](tests/benchmark_dataset.json)
[![LLM](https://img.shields.io/badge/LLM-Llama%203.3%2070B%20(Groq)-orange.svg)](https://groq.com/)
[![Embeddings](https://img.shields.io/badge/Embeddings-Multilingual%20MiniLM-informational.svg)](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
[![Operating Cost](https://img.shields.io/badge/Operating%20Cost-%240.00-teal.svg)](#-tech-stack)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

An AI-powered legal information assistant for Pakistani citizens. Covering **8 primary statutory Acts** (1,635 validated chunks) across Federal and Punjab provincial jurisdictions with strict anti-hallucination guardrails, plain-language statutory explanations, and multi-channel delivery (Web UI, Streamlit, and Twilio WhatsApp) at **$0 operating cost**.

> ⚠️ **Disclaimer**: This tool provides legal **information**, not legal **advice**. Always consult a qualified advocate for your specific legal situation.

---

## ✨ Features

- **Accurate Statutory Citations**: Every answer cites the exact Act and Section number
- **Anti-Hallucination Guardrails**: Explicitly declares when information is not available rather than guessing
- **Scope Enforcement**: Politely refuses out-of-scope queries (foreign law, tax law, unindexed statutory topics)
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
| Retrieval | Hybrid: vector + BM25 fused by RRF, relevance threshold, multilingual synonyms | Free (local) |
| LLM | Groq Cloud API (`llama-3.3-70b-versatile`), answer caching + backoff | Free tier |
| Web UI | Lightweight built-in multi-threaded server (`src/server.py`) + Streamlit option (`app_streamlit.py`) | Free (zero pip deps for server) |
| Channels | Twilio WhatsApp Webhook (`/api/webhook/twilio`) with TwiML XML responses | Free |
| Language | Python 3.10+ | Free |

---

## 🚀 Setup Instructions

### 1. Clone and Install

```bash
git clone https://github.com/TayyabPervaiz/LawBot.git
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
# Option A: Start the Zero-Dependency Web Application (Modern Obsidian/Emerald UI)
python -m src.server
# or: python -m src.bot --web
# Open http://127.0.0.1:8000 in your browser

# Option B: Run the Streamlit Application (Optional)
streamlit run app_streamlit.py

# Option C: WhatsApp / Twilio Webhook
# Configure your Twilio WhatsApp Sandbox webhook to:
# POST http://<your-server-ip>:8000/api/webhook/twilio

# Option D: Interactive CLI (with conversation memory)
python -m src.bot

# Option E: Single question via CLI:
python -m src.bot --ask "Can my landlord evict me without notice?"
```

---

## 📊 Evaluation

```bash
python -m pytest tests/            # 96 offline tests: registry, parser, retrieval, guardrails, server, memory, multilingual, twilio
python -m tests.evaluate --offline # 114 stage-aware benchmark sanity tests (no API key required)
python -m tests.evaluate           # full live benchmark (API key + index)
```

The benchmark (114 questions) is **stage-aware**: a question is expected to be a refusal until the law in its `answered_by` list is loaded, then expected to answer. With all 8 primary laws loaded, in-scope questions dynamically resolve to statutory answers while foreign jurisdictions and tax queries remain strictly refused. In addition, `tests/benchmark_multilingual.json` provides 22 verified Urdu script and Roman Urdu questions tested via `tests/test_multilingual.py`.

---

## 📁 Project Structure

```text
LawBot/
├── data/
│   ├── source_pdfs/<category>/      # Touched official PDF downloads
│   ├── raw/<category>/              # Official UTF-8 .txt extracts — parser source
│   ├── processed/                   # Generated: chunks.json (1,635 chunks), validation_report.txt, llm_cache.json
│   └── chroma_db/                   # Local ChromaDB vector database
├── src/
│   ├── config.py                    # Paths + retrieval/LLM settings
│   ├── law_registry.py              # Registry of all laws, section patterns, and metadata
│   ├── parser.py                    # Section-aware parser + validation report
│   ├── vector_store.py              # ChromaDB wrapper with multilingual embeddings
│   ├── retrieval.py                 # Hybrid retrieval: vector + BM25 + RRF, threshold, multilingual synonyms
│   ├── generator.py                 # Dynamic guardrail prompt, refusals, answer cache, multilingual rules
│   ├── server.py                    # Lightweight multi-threaded web server, REST API, & Twilio webhook
│   └── bot.py                       # Orchestration, CLI, and Web runner (--web / --ask / --index)
├── static/
│   ├── index.html                   # Modern semantic web app layout (English / Roman Urdu / Urdu)
│   ├── style.css                    # Obsidian glassmorphic design system
│   └── app.js                       # Interactive chat, multi-turn state, citation formatter
├── tests/
│   ├── build_benchmark_dataset.py   # Regenerates benchmark_dataset.json (114 questions)
│   ├── benchmark_dataset.json       # Stage-aware benchmark dataset (114 verified questions)
│   ├── benchmark_multilingual.json  # Multilingual benchmark dataset (22 Urdu / Roman Urdu questions)
│   ├── evaluate.py                  # Stage-aware evaluation harness
│   ├── test_multilingual.py         # Multilingual & Twilio integration tests
│   └── test_*.py                    # 96 unit & integration tests
├── app_streamlit.py                 # Alternate Streamlit chat interface
├── PHASE_3_PLAN.md                  # Phase 3 technical specification & architecture
├── .env.example
├── requirements.txt
└── README.md
```

---

## 📜 Supported Laws & Stage Status

> All 8 priority statutory laws have been extracted from official Pakistan Code and Provincial Gazette scans, parsed into 1,635 validated statutory chunks, and indexed into ChromaDB.

| Stage | Law | Jurisdiction | Sections | Status |
|---|---|---|---|---|
| **Phase 1** | The Punjab Rented Premises Act, 2009 | Punjab | 36 | ✅ Loaded & Indexed |
| **Phase 2B** | The Prevention of Electronic Crimes Act (PECA), 2016 | Federal | 92 | ✅ Loaded & Indexed |
| **Phase 2C** | Muslim Family Laws Ordinance, 1961 (MFLO) | Federal | 13 | ✅ Loaded & Indexed |
| **Phase 2C** | The Family Courts Act, 1964 | Punjab | 34 | ✅ Loaded & Indexed |
| **Phase 2C** | The Dissolution of Muslim Marriages Act, 1939 | Federal | 6 | ✅ Loaded & Indexed |
| **Phase 2D** | The Pakistan Penal Code, 1860 (PPC) | Federal | 588 | ✅ Loaded & Indexed |
| **Phase 2D** | The Code of Criminal Procedure, 1898 (CrPC) | Federal | 499 | ✅ Loaded & Indexed |
| **Phase 2E** | The Punjab Consumer Protection Act, 2005 | Punjab | 40 | ✅ Loaded & Indexed |

**Total Statutory Chunks Indexed:** **1,635 sections** across 8 Acts.

---

## 🌐 Multilingual Capabilities (Phase 3)

The assistant features native multilingual processing powered by the `paraphrase-multilingual-MiniLM-L12-v2` cross-lingual embedding model combined with Llama 3.3 70B:
- **English**: Formal statutory answers with bracketed citations `[Act Name - Section X]`.
- **Roman Urdu**: Everyday citizen queries (e.g., *"Agar police FIR darj karne se inkar kare to kya rasta hai?"*) with statutory grounds.
- **Urdu (اردو)**: Full Urdu script input and output with legal terminology preservation.

---

## 🤝 Contributing (adding a new law)

1. Register the law in `src/law_registry.py` (file, section pattern, keywords).
2. Download official PDF into `data/source_pdfs/<category>/` and extract to `data/raw/<category>/`.
3. Run `python -m src.parser` and inspect `data/processed/validation_report.txt`.
4. Re-index: `python -m src.bot --index --force`.
5. Add benchmark questions via `tests/build_benchmark_dataset.py`.
6. Run full verification: `python -m pytest tests/` and `python -m tests.evaluate --offline`.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — free and open for all Pakistani citizens and the global open-source community.

---

*Built with the goal of making legal information accessible to every Pakistani citizen. 🇵🇰*
