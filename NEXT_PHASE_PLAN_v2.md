# Phase 2 (Revised, v2): Expanding Pakistan Law Bot to More Pakistani Laws

**Status.** The proof of concept on Punjab Tenancy Law reported 100% citation precision and 100% refusal accuracy, but only on 10 questions written by the same plan that built the system. That is a good sign, not a validation. This revision adds a hardening step before expansion, fixes several design problems in the first draft of this plan, and makes the data workflow explicit: **the project owner downloads all law text manually from official sources.**

---

## Current project state (read before anything else)

- **Project root: `D:\Work\Projects\LawBot`.** All paths in this plan are relative to it. Ignore any `C:\Users\tayya\pakistan-law-bot` path in older files. Use the existing `venv` in the project root.
- **Law PDFs are already downloaded and in place** (by the owner, manually) in `data/source_pdfs/<category>/`: Punjab Rented Premises Act 2009, Punjab Consumer Protection Act 2005, PECA 2016, Muslim Family Laws Ordinance 1961, West Pakistan Family Courts Act 1964, Dissolution of Muslim Marriages Act 1939, Pakistan Penal Code 1860, Code of Criminal Procedure 1898. The Punjab Rented Premises Rules 2010 are not downloaded (optional).
- **`fetch_laws.py` exists in the project root.** It already checked all eight PDFs (all have selectable text, none scanned) and wrote draft text files to `data/raw_draft/<category>/` and a provenance log to `data/source_log.json`. Do not modify or re-run it unless asked. It never writes to `data/raw/`.
- **Step 0 result (tenancy Act):** the verified text has **36 sections**; the table of contents and the body agree. The 25-versus-36 discrepancy is settled: it is 36. The verified draft has been copied into `data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt`. The older unverified file is in `data/old_unverified/` and must not be used or indexed.
- **Only the tenancy Act is verified and loaded.** The other seven laws exist only as PDFs plus unreviewed drafts in `data/raw_draft/`. Do not copy them into `data/raw/`, parse them as loaded laws, or index them until the owner verifies them at their stage.
- **Known text-format fact:** each law text file begins with a **table of contents** (a list of section numbers and titles) followed by the **full body**. A naive section parser will see every section twice. The parser must skip the table of contents so each section appears exactly once, and the validator must flag duplicate section numbers.
- **Known issues to fix at Gate 1** (do not guess, read the verified text): several citations in the existing 10-question benchmark appear wrong. In the verified text, Section 12 is "Obligations of landlord", Section 13 is "Obligations of tenant", Section 10 is "Effect of other agreement", and Section 15 is "Grounds for eviction". Test #6 (landlord cutting off amenities) cites Section 13, and test #2 (rent increase) cites Sections 6 and 10. Re-derive every expected citation from the text in `data/raw/`, list each change you make, and let the owner confirm.
- **Early warning for the criminal stage:** the CrPC draft's last section-like line was "295C", although the Code has far more sections. Either the text is cut off, ordered unusually, or formatted differently in its later parts. Investigate this before any CrPC work. Do not touch it now.

---

## 0. Rules for the implementing model (read first)

1. **Law text is supplied by the project owner.** The owner downloads it manually from official sources and places it in the folders described in Section 2. You must **never** write, recall, reconstruct, summarize into, or "fill in" statutory text from your own knowledge. If a law file is missing, say so and stop.
2. **The parser reads only `data/raw/`.** The folder `data/source_pdfs/` holds untouched original PDFs for human comparison. Do not index it. You may read a PDF from it only when the owner asks you to extract text into `data/raw/`.
3. **If a file looks incomplete, garbled, scanned, or fails validation, stop and report.** Do not patch the text by hand or guess at missing sections.
4. **Work in order and stop at every GATE** (defined in Section 9). Report results and wait for the owner's confirmation before continuing.
5. **No unexplained percentages.** Whenever you report an accuracy number, state how many questions were in the benchmark and whether their ground truth was verified by the owner against the official text.
6. **Keep the project 100% free ($0):** local embeddings, local vector store, free LLM tier. Add retry with backoff and response caching for LLM calls so free-tier rate limits (HTTP 429) do not break benchmark runs.
7. **No law names, section formats, or keywords hardcoded outside the law registry** (`src/law_registry.py`).

---

## 1. Summary of changes from the first draft of this plan

| Area | First draft | Revised |
|---|---|---|
| Topic Router | Guess one topic from keywords, then search only that law | Search **all** loaded laws every time (hybrid retrieval + reranker + relevance threshold). Keywords are only a small hint |
| Registry and parser | Laws keyed by folder; PPC and CrPC shared one folder and one regex | Laws keyed **by file**, each with its own pattern. Parser output is **validated** (count, ordering, spot checks) |
| Benchmark | 10 questions, then straight to new laws | New **Gate 1**: owner verifies ground truth, benchmark grows to 40-50 questions, answer content is checked, not just section numbers |
| Benchmark across stages | Old refusal tests would break when PPC is added | Each question lists which laws can answer it; the harness expects an answer or a refusal depending on which laws are loaded |
| Expansion order | PPC and CrPC first (huge) | One **small law first** (PECA) to test the multi-law machinery, then Family, then PPC/CrPC |
| PPC / CrPC | Treated like any other law | Extra care: amendment dates, linked definitions, heavier testing, expert review |
| Family law | Muslim Family Laws Ordinance + Family Courts Act | Adds the **Dissolution of Muslim Marriages Act, 1939** and flags other likely gaps |
| Embedding model | English-only model | A **multilingual model chosen now**, so adding Urdu/Roman Urdu later does not force a second re-index |
| Data | Assumed text files would appear | Manual download guide, folder layout, per-file checklist, tenancy file audit (Step 0) |

---

## 2. Manual data download guide (project owner)

> **Status: complete for all laws currently planned.** The owner has already downloaded the eight PDFs (see Current project state). This section stays as the procedure for any further law and as a record of the folder rules. The implementing model does not need to act on it.

The code does not fetch laws from the internet. You download them once, check them, and place them in the folders below. This is the most important quality step in the project: the bot can only be as complete and as accurate as these files.

### 2.1 Folder layout

Project root: `C:\Users\tayya\pakistan-law-bot\`

```text
data\
├── source_pdfs\                  <- ORIGINAL downloads, never edited, never indexed
│   ├── tenancy_punjab\
│   ├── cybercrime\
│   ├── family\
│   ├── criminal\
│   └── consumer\
├── raw\                          <- CLEAN UTF-8 .txt files. THE PARSER READS ONLY THIS FOLDER
│   ├── tenancy_punjab\
│   ├── cybercrime\
│   ├── family\
│   ├── criminal\
│   └── consumer\
├── processed\                    <- generated (chunks, validation reports)
└── chroma_db\                    <- generated (vector database)
```

Create the folders in PowerShell from the project root:

```powershell
mkdir data\source_pdfs\tenancy_punjab, data\source_pdfs\cybercrime, data\source_pdfs\family, data\source_pdfs\criminal, data\source_pdfs\consumer
mkdir data\raw\tenancy_punjab, data\raw\cybercrime, data\raw\family, data\raw\criminal, data\raw\consumer
```

### 2.2 What to download and where to save it

Use these exact filenames. The law registry refers to them.

| Law | Save PDF in `data\source_pdfs\...` | Save clean text in `data\raw\...` | Where to look |
|---|---|---|---|
| Punjab Rented Premises Act, 2009 | `tenancy_punjab\` | `tenancy_punjab\punjab_rented_premises_act_2009.txt` | Punjab laws portal (punjabcode.punjab.gov.pk) |
| Punjab Rented Premises Rules, 2010 (optional) | `tenancy_punjab\` | `tenancy_punjab\punjab_rented_premises_rules_2010.txt` | Same |
| Prevention of Electronic Crimes Act, 2016 (with amendments) | `cybercrime\` | `cybercrime\peca_2016.txt` | Pakistan Code (pakistancode.gov.pk) |
| Muslim Family Laws Ordinance, 1961 | `family\` | `family\muslim_family_laws_ordinance_1961.txt` | Pakistan Code |
| Family Courts Act, 1964 | `family\` | `family\family_courts_act_1964.txt` | Pakistan Code |
| Dissolution of Muslim Marriages Act, 1939 | `family\` | `family\dissolution_of_muslim_marriages_act_1939.txt` | Pakistan Code |
| Pakistan Penal Code, 1860 | `criminal\` | `criminal\pakistan_penal_code_1860.txt` | Pakistan Code |
| Code of Criminal Procedure, 1898 | `criminal\` | `criminal\code_of_criminal_procedure_1898.txt` | Pakistan Code (also check for Punjab amendments) |
| Punjab Consumer Protection Act, 2005 | `consumer\` | `consumer\punjab_consumer_protection_act_2005.txt` | Punjab laws portal |

Download laws **in stages** (Section 8), not all at once. Right now you only need the tenancy files, then PECA.

### 2.3 Step-by-step download procedure (repeat for each law)

1. **Find the official page.** Federal laws: Pakistan Code. Punjab laws: the Punjab laws portal. Search by the full name of the Act. If a portal is down or the law is missing, use another official source (for example the Ministry of Law and Justice or the Punjab Law and Parliamentary Affairs Department) and record which one you used.
2. **Prefer the current, amended version.** If the site offers both the original Act and an "as amended / updated up to" version, take the amended one. Write down the "amended up to" date. Some federal laws also have provincial amendments (CrPC in particular); note them.
3. **Save the original PDF** into the matching `data\source_pdfs\<category>\` folder. Do not edit it.
4. **Make the clean text file** in `data\raw\<category>\` using ONE of these methods:
   - **Method A (preferred):** if you can select and copy text in the PDF, ask the model to extract the text with a script. It must extract, not retype.
   - **Method B:** open the PDF, select all, paste into Notepad, and save as **UTF-8** with the filename from the table above.
   - **Scanned PDFs:** if you cannot select text, the PDF is an image. Tell the model; it needs OCR, and OCR output needs much heavier checking.
5. **Clean the text.** Remove page numbers, running headers and footers, and website navigation text. Keep every section, proviso, explanation, illustration (for the PPC), and schedule.
6. **Verify the file (all four checks must pass):**
   - The section count matches the table of contents or the official count.
   - The first and last sections are present.
   - Provisos, explanations, and schedules are included.
   - Spot check **20 random sections** word for word against the PDF. The validator prints these for you (Section 5.3).
7. **Record the source details** in the registry fields for that law (Section 5.2): `source_url`, `downloaded_on`, `amended_up_to`, `expected_section_count`. Fill these yourself; do not let the model guess them.
8. **Tell the model the file is ready.** It then runs the parser validation and reports. You review the report before anything is indexed.

### 2.4 Common problems

| Problem | What it looks like | What to do |
|---|---|---|
| Scanned PDF | Cannot select text | OCR plus heavy spot checking, or find another source |
| Mixed-in page furniture | "Page 12 of 80" inside a section | Clean it from the text file |
| Missing amendments | Old wording, repealed sections still present | Download the amended version |
| Broken lines | Words split by line breaks | Re-extract, or fix the text file and re-check |
| Wrong encoding | Garbled characters | Save as UTF-8 |

---

## 3. Step 0: audit the existing tenancy data (do this before any code changes)

> **Status: owner part done** (section count confirmed as 36; verified text in place). Remaining model task: re-check every section number in the existing benchmark against the verified text, as described in Current project state, and report every change.

The two earlier plans disagree on the size of the Punjab Rented Premises Act (36 sections in one, 25 in the other). It is not clear whether the current text file was downloaded from the official source or produced from a model's memory.

**Owner tasks**
1. Download the official Act (Section 2.3) into `data\source_pdfs\tenancy_punjab\`.
2. Compare it with the current `data\raw\tenancy_punjab\punjab_rented_premises_act_2009.txt`: section count, section numbers and titles, and 20 random sections word for word.
3. If they differ, replace the text file with one made from the official PDF and re-verify.

**Model tasks**
1. Report how the current text file was created, if known.
2. Print the list of parsed sections (number, title) so the owner can compare.
3. **Re-check every section number in the existing 10 benchmark questions** (for example "Section 15", "Sections 6 and 10", "Section 13") against the verified text. Correct any that are wrong. Report every change.

Nothing else proceeds until Step 0 is complete.

---

## 4. Architecture gap analysis (updated)

| Component | Current (single-law) | Needed (multi-law) |
|---|---|---|
| Parser | Reads only `data/raw/tenancy_punjab/` | Reads each file listed in the registry, with its own section pattern, and validates the result |
| Scope handling | Binary: tenancy is in scope, everything else refused | Search all loaded laws, decide by retrieval confidence, refuse politely with a list of loaded laws |
| System prompt | Hardcoded to the Punjab Rented Premises Act | Dynamic: lists the Acts actually retrieved |
| Disclaimer | Hardcoded to one Act | Dynamic: lists the Acts cited in the answer |
| Refusal message | Hardcoded to tenancy | Dynamic: built from the registry of loaded laws |
| Vector store | One collection, no metadata | One collection with `law_id`, `law_category`, `jurisdiction`, `section_number` metadata |
| Embedding model | English-only (all-MiniLM-L6-v2) | Multilingual model, chosen now (Section 5.6) |
| Config | Single collection name | Paths and settings; laws come from the registry |
| Benchmark | 10 questions, one law | Stage-aware benchmark (Section 6) |

---

## 5. Architecture refactoring plan

### 5.1 Multi-law data pipeline

One ChromaDB collection holds all chunks, each tagged with metadata. One collection (not one per law) allows cross-law questions, such as "my landlord assaulted me," to retrieve from both tenancy and criminal law.

### 5.2 Law registry (`src/law_registry.py`), keyed by file

Each entry describes one law file. Two laws in the same folder (PPC and CrPC) are separate entries with their own file and pattern.

```python
LAW_REGISTRY = {
    "tenancy_punjab_2009": {
        "title": "The Punjab Rented Premises Act, 2009",
        "short_title": "Punjab Rented Premises Act",
        "year": 2009,
        "jurisdiction": "Punjab",
        "category": "tenancy",
        "file": "tenancy_punjab/punjab_rented_premises_act_2009.txt",
        "section_pattern": r"^Section\s+(\d+[A-Za-z]?)\.\s*(.*)",   # verify against the real file
        "hint_keywords": ["tenant", "landlord", "rent", "evict", "lease", "security deposit"],
        # Filled in by the owner after download:
        "source_url": None,
        "downloaded_on": None,
        "amended_up_to": None,
        "expected_section_count": None,
    },
    "ppc_1860": {
        "title": "The Pakistan Penal Code, 1860",
        "short_title": "Pakistan Penal Code",
        "year": 1860,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/pakistan_penal_code_1860.txt",
        "section_pattern": r"^(\d+[A-Z]?)\.\s+(.+)",                  # verify against the real file
        "hint_keywords": ["theft", "murder", "assault", "fraud", "defamation", "offence"],
        "always_include_sections": [],   # owner lists definition sections found in the real text
        "source_url": None, "downloaded_on": None, "amended_up_to": None, "expected_section_count": None,
    },
    "crpc_1898": {
        "title": "The Code of Criminal Procedure, 1898",
        "short_title": "CrPC",
        "year": 1898,
        "jurisdiction": "Federal",
        "category": "criminal",
        "file": "criminal/code_of_criminal_procedure_1898.txt",
        "section_pattern": r"^(?:Section\s+)?(\d+[A-Z]?)\.\s+(.+)",   # verify against the real file
        "hint_keywords": ["FIR", "bail", "arrest", "warrant", "magistrate", "investigation"],
        "source_url": None, "downloaded_on": None, "amended_up_to": None, "expected_section_count": None,
    },
    # peca_2016, mflo_1961, family_courts_1964, dmma_1939, ... follow the same shape
}
```

The patterns above are starting points. The real downloaded text decides the final pattern, and the validator (5.3) confirms it works. A law is "loaded" only if its file exists and passes validation; the registry and every refusal message use that list.

### 5.3 Parser generalization and validation (`src/parser.py`)

1. Read each file listed in the registry using that entry's own `section_pattern`.
2. Chunk **by section**, never by character count. Store: `law_id`, `law_title`, `jurisdiction`, `category`, `section_number`, `section_title`, `chapter/part` where available, `amended_up_to`, `text`. Split very long sections by subsection while keeping the parent title in each chunk's header. Short sections (many PPC sections) stay as single chunks.
3. A pattern such as `^(\d+[A-Z]?)\.` can wrongly match numbered list items, illustrations, or page numbers inside a section. Guard against this with the checks below.
   **Table of contents:** the law files begin with a table of contents listing every section number and title, then the full body. Detect and skip the table of contents (for example, treat the first run of consecutive short section-title lines, or lines without the body's dash-and-text format, as the contents list, and start parsing at the first full section heading whose text follows on the same line or next lines). Each section must end up as exactly one chunk. Verify with the duplicate-number check below and by comparing the chunk count with the table of contents count.
4. **Validation report** written to `data/processed/validation_report.txt` for every law:
   - Parsed section count versus `expected_section_count`.
   - Section numbers should increase in order. List every duplicate (a duplicate usually means the table of contents was parsed as sections), gap, or out-of-order number.
   - Chunk count must equal the number of entries in the table of contents.
   - First and last section found.
   - Empty or very short chunks, and unusually long chunks.
   - **20 randomly chosen sections printed in full** (number, title, text) so the owner can compare them with the PDF.
5. If validation fails, stop and report. Do not index a law that has not passed the owner's review.

### 5.4 Retrieval (replaces the keyword Topic Router in `src/generator.py` / a new `src/retrieval.py`)

The first draft routed each question to one law by keywords and filtered the search to that law. That fails on questions touching two laws and adds a point of failure. Instead:

1. **Search all loaded laws every time** with hybrid retrieval: embedding similarity plus keyword search (BM25), merged by reciprocal rank fusion.
2. **Rerank** the top results with a small, free, local cross-encoder reranker. This helps separate near-identical sections, such as theft, robbery, and extortion in the PPC.
3. **Relevance threshold.** If the best score is below the threshold, the bot answers that the loaded laws do not cover the question (and lists the loaded laws). Tune the threshold using the benchmark.
4. **Linked definitions.** If a retrieved section depends on defined terms, also include the sections listed under that law's `always_include_sections`.
5. **Soft hints only.** Registry `hint_keywords` may give a small score boost. They must never exclude a law from the search.
6. **Jurisdiction awareness.** If the user states a province for which no law is loaded (for example the tenancy Act covers Punjab only), the answer must say that the loaded law applies to Punjab.
7. Pass the top-k chunks to the LLM. The metadata filter on `law_category` stays available for tests and debugging but is not part of the default path.

### 5.5 Dynamic system prompt, disclaimer, and refusals

- Build `{laws_in_context}` from the Acts actually retrieved for this question.
- Citation format stays strict: `[Act Name - Section X]`. When several Acts are used, cite each fact to its own Act and never merge provisions from different Acts into one statement.
- Uncertainty rule: if the retrieved text does not address the question, say so and suggest consulting an advocate. Do not extrapolate.
- Out-of-scope and not-covered replies list the laws currently loaded (from the registry), for example: "This assistant currently covers: ...".
- The disclaimer names the Acts cited in that answer and states that this is legal information, not legal advice.

### 5.6 Embedding model (decide now, while only one small law is indexed)

The current English-only model should be replaced now by a multilingual one, so Roman Urdu and Urdu work in Phase 3 without a second full re-index. Candidates: `BAAI/bge-m3`, `intfloat/multilingual-e5-small` or `-base`, `paraphrase-multilingual-MiniLM-L12-v2`. All run locally and free. Choose using the benchmark (Gate 1) and note the choice in `src/config.py`. Changing the model later means re-indexing everything.

### 5.7 Generation model (the LLM that writes the final answer)

The embedding model (5.6) only finds the right sections. A separate LLM writes the answer from them. This plan does not hardcode one; it is chosen with the benchmark.

- **Config-driven, not hardcoded.** `src/config.py` holds `LLM_PROVIDER` and `LLM_MODEL`. `src/generator.py` calls a single `generate(prompt)` function, so changing provider or model is a config change. API keys come from `.env` only and are never printed or committed.
- **First task:** report which provider and model the current code uses (read `src/generator.py`, `.env.example` and `requirements.txt`; do not print any key).
- **Candidates, all free or local.** Verify current model names and free-tier limits on the provider's site before relying on them:
  - Groq-hosted Llama 3.3 70B (the original implementation plan named this, with Llama 3.1 8B as a faster option).
  - A Google Gemini free-tier Flash model.
  - A local Ollama model for offline use. Small models (about 3B parameters) are weaker at strict citation and refusal, so treat them as a fallback, not the default.
- **Choose by benchmark, not by reputation.** At Gate 1, run the same verified benchmark with each candidate and compare citation precision and recall, grounding, refusal accuracy, and how often it hits rate limits. Record the comparison in the README.
- **Any model change means re-running the full benchmark** before accepting it. A different model can change results even when retrieval is unchanged.
- **Settings:** temperature 0 or very low; the prompt instructs the model to answer only from the supplied sections.
- **Urdu and Roman Urdu:** test the chosen model on both before Phase 3 depends on it.

---

## 6. Evaluation plan (stage-aware benchmark)

### 6.1 Question format (`tests/benchmark_dataset.json`)

```json
{
  "id": "TEN-001",
  "question": "Can my landlord evict me without notice?",
  "language": "en",
  "type": "in_scope",
  "answered_by": ["tenancy_punjab_2009"],
  "expected_citations": [{"law_id": "tenancy_punjab_2009", "section": "15"}],
  "verified_by": "owner",
  "verified_on": "YYYY-MM-DD",
  "verification_source": "official PDF, page X"
}
```

`type` is one of: `in_scope`, `multi_law`, `not_covered_by_text` (the law is loaded but silent on the question), `out_of_scope`.

### 6.2 How expected behavior is decided

The harness checks which laws are currently loaded. If **all** laws in `answered_by` are loaded, the bot is expected to answer and cite them. Otherwise it is expected to refuse. This means "How do I file an FIR for motorcycle theft?" is correctly a refusal before the PPC/CrPC are loaded and correctly an answer after, with no manual edits to the benchmark.

### 6.3 Metrics

- **Citation precision:** share of cited sections that are correct.
- **Citation recall:** share of the required sections that were cited (matters for multi-section answers).
- **Grounding check:** every claim in the answer is supported by the cited text. Use an automated checker plus a manual review of a sample.
- **Refusal accuracy:** out-of-scope questions are refused without hallucination.
- **Not-covered calibration:** when the loaded law is silent, the bot says so instead of guessing.
- **Cross-contamination check:** after each new law is added, all earlier questions must still pass.

### 6.4 Benchmark size and quality

- Tenancy stage (Gate 1): grow from 10 to **40-50 questions**. Write them the way ordinary citizens ask: vague, emotional, incomplete. Include multi-section questions and several `not_covered_by_text` questions.
- Each new law adds **10-15 questions**, including at least two cross-law questions each time.
- **Every question's ground truth is verified by the owner against the official text** and marked with `verified_by`, `verified_on`. Unverified questions do not count toward reported results.
- Before the criminal law stage, have a **lawyer or law student review a sample** of answers. A wrong punishment or bail rule is a serious mistake.
- Free-tier LLM limits: cache LLM answers by question hash and add retry with backoff in the harness, so a 429 error does not fail a run.

---

## 7. Priority laws (revised order)

| Stage | Law | Why | Approx. size | Notes |
|---|---|---|---|---|
| Pilot | Prevention of Electronic Crimes Act (PECA), 2016 | Small, one self-contained Act, easy to verify by hand; good test of multi-law retrieval (for example threatening messages from a landlord) | ~50 sections | Check whether amendments are included in the text you download |
| Family | Muslim Family Laws Ordinance 1961; Family Courts Act 1964; **Dissolution of Muslim Marriages Act 1939** | Marriage, divorce, maintenance, family court procedure | Small | Khula and divorce grounds mainly sit in the 1939 Act. Ask a lawyer which other laws are needed for custody and inheritance (for example the Guardians and Wards Act, 1890). Some practice comes from case law, which this system does not hold; the bot must say "not covered" for such questions |
| Criminal | Pakistan Penal Code 1860; Code of Criminal Procedure 1898 | Highest citizen impact, highest risk | 500+ sections each | Special care (Section 8.4) |
| Later | Consumer protection, labour laws, Transfer of Property Act, 1882 | Broader coverage | Varies | Same download and validation process |

---

## 8. Implementation phases and tasks

### 8.1 Phase 2A: multi-law architecture refactoring

| # | Task | Type | Description |
|---|---|---|---|
| 2A-L2 | Config update | Less critical | Update `src/config.py` for new paths; set the **multilingual embedding model**; add `LLM_PROVIDER` / `LLM_MODEL` settings (Section 5.7) |
| 2A-L1 | Vector store metadata | Less critical | Store `law_id`, `law_category`, `jurisdiction`, `section_number`; add an optional `where` filter to `query()` |
| 2A-C1 | Law registry | Critical | Create `src/law_registry.py`, keyed by file (Section 5.2) |
| 2A-C2 | Parser generalization and validation | Critical | Per-file patterns, validation report, random section printout (Section 5.3) |
| 2A-C3 | Retrieval | Critical | Hybrid retrieval, reranker, threshold, soft hints, linked definitions (Section 5.4) |
| 2A-C4 | Dynamic prompt, disclaimer, refusals | Critical | Section 5.5 |
| 2A-L3 | Stage-aware benchmark harness | Critical | Section 6; includes caching and backoff |

### 8.2 Phase 2B: pilot law (PECA)

| # | Task | Type | Description |
|---|---|---|---|
| 2B-C1 | PECA data | Critical | Owner downloads, cleans, verifies (Section 2.3); model runs validation |
| 2B-C2 | PECA benchmark | Critical | 10-15 verified questions including cross-law ones |
| 2B-L1 | Index rebuild | Less critical | Rebuild the index with tenancy + PECA |

### 8.3 Phase 2C: family laws

| # | Task | Type | Description |
|---|---|---|---|
| 2C-C1 | Family law data | Critical | Three Acts (Section 7); owner downloads and verifies; lawyer confirms whether more laws are needed |
| 2C-C2 | Family benchmark | Critical | Including `not_covered_by_text` questions for areas that depend on case law |
| 2C-L1 | README | Less critical | List supported laws |

### 8.4 Phase 2D: PPC and CrPC (extra care)

| # | Task | Type | Description |
|---|---|---|---|
| 2D-C1 | PPC data and parsing | Critical | Handle explanations, illustrations, and lettered sections (for example "302A"-style numbers). Record `amended_up_to` |
| 2D-C2 | CrPC data and parsing | Critical | Part/Chapter/Section hierarchy; note any Punjab amendments |
| 2D-C3 | Linked definitions | Critical | Owner identifies definition sections in the real text and lists them under `always_include_sections` |
| 2D-C4 | Criminal benchmark | Critical | 15+ verified questions; **expert review of a sample** before the stage is considered passed |
| 2D-L1 | Index rebuild | Less critical | Expect several minutes for 800+ chunks |

Reasons for the extra care: the PPC and CrPC have been amended many times, PPC sections often depend on definitions elsewhere in the Code, and a wrong punishment or bail rule matters far more than a wrong tenancy rule.

### 8.5 Phase 3: user experience (after multi-law works)

| # | Task | Description |
|---|---|---|
| 3-1 | Web interface | Streamlit chat UI on top of the same `answer()` function |
| 3-2 | Urdu and Roman Urdu | Support Urdu input with the multilingual embeddings chosen in 2A; extend benchmark to those languages |
| 3-3 | Conversation memory | Session context for follow-up questions |
| 3-4 | WhatsApp bot | Twilio or WhatsApp Business API wrapper around the same core function |
| 3-5 | Response caching | Cache frequent questions to reduce LLM calls |

---

## 9. Execution order with gates

```text
Step 0   Audit the existing tenancy data (Section 3)            -> Owner + model
Step 1   2A-L2  Config + multilingual embedding model + LLM settings -> Other model
Step 2   2A-L1  Vector store metadata                            -> Other model
Step 3   2A-C1  Law registry (keyed by file)                     -> Critical model
Step 4   2A-C2  Parser generalization + validation               -> Critical model
Step 5   2A-C3  Retrieval (replaces the Topic Router)            -> Critical model
Step 6   2A-C4  Dynamic prompt, disclaimer, refusals             -> Critical model
Step 7   Re-index tenancy with the new embedding model; regression test
Step 8   2A-L3  Stage-aware benchmark harness
GATE 1   Benchmark hardening (tenancy): owner verifies ground truth, 40-50 questions,
         grounding check, failure analysis. Do not continue until the owner approves.
Step 9   Owner downloads and verifies PECA; model runs validation
GATE 2   Owner reviews validation report for PECA before indexing
Step 10  Index PECA; run tenancy + PECA benchmark (including cross-law questions)
GATE 3   Multi-law check: all tenancy questions still pass, no cross-contamination
Step 11  Family laws: download, validate, index, benchmark (repeat the Gate pattern)
Step 12  PPC: download, validate, index
Step 13  CrPC: download, validate, index
Step 14  Criminal benchmark + expert review of a sample
GATE 4   Full benchmark across all loaded laws; owner and reviewer sign-off
Step 15  Phase 3 (web UI, Urdu, WhatsApp)
```

At each GATE the model reports: what was done, benchmark size, results, failures with examples, and open questions. It then waits.

---

## 10. Key decisions (updated)

1. **One collection or several?** One collection with metadata. Cross-law questions work and the pipeline stays simple.
2. **Different section formats?** A configurable pattern per law file in the registry, checked by the validator.
3. **Keyword router or search-everything?** Search everything with hybrid retrieval, a reranker, and a relevance threshold. Keywords are only a soft hint. LLM-based routing is not needed.
4. **Which embedding model?** A multilingual one, chosen in 2A, so Urdu support does not force a re-index.
4a. **Which generation LLM?** Configurable, with candidates compared on the verified benchmark at Gate 1 (Section 5.7). No model is hardcoded.
5. **Web framework?** Streamlit first (fastest, built-in chat UI). The core stays UI-independent so WhatsApp can reuse it.
6. **Where does law text come from?** Manual downloads from official sources by the owner, verified before indexing. The model never supplies law text.

---

## 11. Estimated effort

| Phase | Estimated time | Dependencies |
|---|---|---|
| Step 0 audit | 0.5-1 session | Owner downloads the official tenancy Act |
| 2A: architecture refactoring | 2-3 sessions | Step 0 complete |
| Gate 1: benchmark hardening | 1-2 sessions | 2A complete; owner time for verification |
| 2B: PECA pilot | 1 session | Gate 1 passed; verified PECA text |
| 2C: family laws | 1-2 sessions | Gate 3 passed; verified texts |
| 2D: PPC + CrPC | 2-3 sessions | Verified texts; expert review |
| 3: Web UI | 1-2 sessions | 2D complete |
| 3: Urdu support | 1-2 sessions | 2D complete |

The biggest time sink is acquiring and verifying clean statutory text, especially for the PPC and CrPC. The code changes are well scoped because the existing architecture is already modular.

---

## 12. Standing disclaimers and limits

- This is a legal **information** tool, not legal advice, and every answer must say so.
- The bot answers only from the laws that have been loaded, verified, and dated. It does not hold case law, rules, notifications, or local practice unless those documents are added. When the question needs them, it must say it cannot answer.
- Laws change. Record `amended_up_to` for each law and re-download periodically.
- Reported accuracy is meaningful only for verified benchmark questions. Always state the benchmark size and who verified it.
