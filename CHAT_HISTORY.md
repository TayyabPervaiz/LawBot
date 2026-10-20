# LawBot - Project Context & Conversation History

## 1. Project Background & Vision
- **Objective**: An AI Legal Assistant designed specifically for Pakistani citizens to provide easily accessible, highly accurate legal information grounded in Pakistani statutes.
- **Phase 1 Goal**: Prove the **core RAG engine** works with high precision and strict statutory citations before building any user interface, WhatsApp bot, or authentication.
- **Cost Requirement**: 100% Free ($0 Cost) using open-source local embeddings (`sentence-transformers`), local embedded vector store (`ChromaDB`), and free LLM inference (`Groq` free tier / local `Ollama`).

---

## 2. Established Requirements & Decisions

1. **Initial Legal Scope**:
   - **Punjab Tenancy & Rent Law** (*The Punjab Rented Premises Act, 2009*).
   - Modular architecture designed to allow easily adding other statutes later (e.g., Pakistan Penal Code, Family Courts Act, PECA 2016 cybercrime, Property transfer laws).

2. **Language Policy**:
   - English first for core verification.
   - Urdu (Nastaliq) and Roman Urdu will be added in subsequent phases after the core logic is verified.

3. **Official Data Source**:
   - Government of the Punjab official legislative portal: `punjabcode.punjab.gov.pk`
   - Primary statute: **The Punjab Rented Premises Act, 2009 (Act VII of 2009)**.

4. **Hallucination Defense & Citations**:
   - Every answer must cite the specific Act and Section number (e.g. `[Punjab Rented Premises Act, 2009 - Section 15]`).
   - If a question is not covered by the indexed statutory provisions, the system must clearly state so instead of guessing or extrapolating.
   - Explicit guardrails to refuse out-of-scope queries (criminal law, family law, foreign law).

5. **Evaluation Benchmark**:
   - A deterministic 10-question test suite (`tests/evaluate.py`) testing in-scope questions (notice, eviction grounds, rent hike, security deposit, verbal agreements, utilities cutoff) and out-of-scope refusals (criminal FIRs, Khula, cybercrime harassment, foreign laws).

---

## 3. Implemented Project Structure (`D:\Work\Projects\LawBot`)

```text
D:\Work\Projects\LawBot\
├── data\
│   ├── raw\
│   │   └── tenancy_punjab\
│   │       └── punjab_rented_premises_act_2009.txt
│   ├── processed\
│   │   └── chunks.json
│   └── chroma_db\               # Local persistent Chroma vector store
├── src\
│   ├── __init__.py
│   ├── config.py                # Environment & LLM configuration
│   ├── parser.py                # Section-aware statutory parser
│   ├── vector_store.py          # Embeddings & ChromaDB indexer
│   ├── generator.py             # Strict RAG generator with guardrails
│   └── bot.py                   # Interactive CLI query assistant
├── tests\
│   ├── benchmark_dataset.json   # 10 benchmark test questions
│   ├── evaluate.py              # Automated accuracy & citation benchmark
│   └── evaluation_results.json  # Benchmark test run results
├── .env / .env.example
├── requirements.txt
├── IMPLEMENTATION_PLAN.md
└── README.md
```

---

## 4. How to Continue in this Project

To open Claude Code directly in this project directory:
```bash
cd /d D:\Work\Projects\LawBot
claude
```
Running Claude from `D:\Work\Projects\LawBot` ensures all project sessions, context files, and tool executions operate directly inside the repository.
