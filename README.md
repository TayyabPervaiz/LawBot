# 🏛️ Pakistan Law Bot — AI Legal Information Assistant

An AI-powered legal information assistant for Pakistani citizens, currently specialized in **Punjab Tenancy & Rent Law** (The Punjab Rented Premises Act, 2009).

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
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) | Free (local) |
| Vector Store | ChromaDB | Free (local) |
| LLM | Groq Cloud API (Llama 3.3 70B) | Free tier |
| LLM (Offline) | Ollama (Llama 3.2 3B) | Free (local) |
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

### 3. Process Legal Data

```bash
# Parse the law text into structured chunks
python -m src.parser

# Build the vector search index
python -m src.vector_store
```

### 4. Run the Assistant

```bash
# Start the interactive CLI
python -m src.bot
```

---

## 📊 Evaluation

Run the automated benchmark suite to verify accuracy:

```bash
python -m tests.evaluate
```

This tests:
- **Citation Precision**: Are the correct sections cited?
- **Refusal Accuracy**: Are out-of-scope questions properly refused?
- **Uncertainty Calibration**: Does it say "I don't know" when appropriate?

---

## 📁 Project Structure

```text
LawBot/
├── data/
│   ├── raw/tenancy_punjab/          # Original law text files
│   ├── processed/                    # Parsed chunks (JSON)
│   └── chroma_db/                    # Vector database (auto-generated)
├── src/
│   ├── config.py                     # Settings and environment variables
│   ├── parser.py                     # Legal section-aware text chunker
│   ├── vector_store.py               # ChromaDB wrapper with local embeddings
│   ├── generator.py                  # RAG prompt engine with guardrails
│   └── bot.py                        # Main query interface
├── tests/
│   ├── benchmark_dataset.json        # Test questions with expected answers
│   └── evaluate.py                   # Automated accuracy test suite
├── .env.example                      # Template for API keys
├── requirements.txt                  # Python dependencies
└── README.md                         # This file
```

---

## 📜 Currently Supported Laws

- ✅ The Punjab Rented Premises Act, 2009 (Punjab Tenancy & Rent Law)

### Planned Additions
- ⬜ Pakistan Penal Code, 1860
- ⬜ Family Courts Act, 1964
- ⬜ Prevention of Electronic Crimes Act (PECA), 2016

---

## 🤝 Contributing

To add a new legal act:
1. Place the clean text file in `data/raw/<category>/`
2. Follow the formatting pattern: each section starts with `Section X.` on its own line
3. Re-run the parser and vector store indexing
4. Add benchmark test cases to `tests/benchmark_dataset.json`

---

## 📄 License

This project is open source and free for all Pakistani citizens.

---

*Built with the goal of making legal information accessible to every Pakistani citizen. 🇵🇰*
