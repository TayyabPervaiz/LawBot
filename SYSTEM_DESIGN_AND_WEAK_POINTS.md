# How Pakistan Law Bot Works — Tech, Weak Points, and Fixes

**Generated:** 2026-10-25 · Companion to `PROJECT_FULL_REPORT.md` (status and corpus). This document is about **mechanism**, **stack**, and **what is actually wrong**.

---

## 1. What the system is

A citizen types a question (English, Roman Urdu, or Urdu). The program does **not** let the LLM “remember Pakistani law.” It:

1. Optionally **refuses** the question before retrieval (foreign jurisdiction, tax, or a legal category with no loaded Act).
2. **Searches** a local vector database of statutory chunks (all loaded Acts together).
3. If nothing useful comes back, says the loaded laws do not cover the issue.
4. Otherwise **prompts Groq Llama 3.3 70B** with those chunks only, demanding `[Act Name - Section X]` citations and a disclaimer.

That pattern is RAG (retrieval-augmented generation) with extra legal guardrails. It is **legal information**, not advice.

---

## 2. End-to-end request path

```text
Browser (static/app.js)  or  CLI (src/bot.py)
        │  POST /api/ask { question, history, top_k }
        ▼
src/server.py  ThreadingHTTPServer  (or CLI skip this)
        │
        ▼
src/bot.ask()
        │
        ├─ 1. generator.detect_scope(question)
        │     keyword regex → refuse OR continue
        │
        ├─ 2. If history looks like a follow-up, prepend last user question
        │
        ├─ 3. retrieval.search() over ALL loaded laws
        │       Chroma vector query (pool 50)
        │       + BM25 over full corpus
        │       → Reciprocal Rank Fusion
        │       → optional cross-encoder (off)
        │       → tiny keyword hint boost
        │       → inject always_include definition sections
        │
        ├─ 4. If “below threshold” or empty → canned “not covered”
        │
        └─ 5. generator.generate_answer()
                format chunks as “PROVISION i”
                Groq chat (temp 0, max 1024 tokens)
                disk cache by prompt+model+question+context hash
                append disclaimer if missing
                extract “Section N” strings (telemetry only)
                return answer to UI
```

**Indexing path (one-time, owner-gated):**

```text
Official PDF  →  src/extract_pdf.py  →  data/raw/<category>/*.txt
        →  src/parser.py (per-law regex, skip table of contents, split long sections)
        →  data/processed/chunks.json + validation_report.txt
        →  owner reads the report
        →  python -m src.bot --index  →  ChromaDB at data/chroma_db/
```

The parser is the quality gate. `fetch_laws.py` may write **drafts** under `data/raw_draft/` only. Nothing in `data/source_pdfs/` is indexed.

---

## 3. Technology in use

| Layer | Choice | Why / notes |
|---|---|---|
| Language | Python 3.10+ (verified 3.13.5 / Windows) | Whole backend |
| Embeddings | `sentence-transformers` model `paraphrase-multilingual-MiniLM-L12-v2` | Local CPU, ~118 languages so Urdu later does not force a second index |
| Vector DB | ChromaDB persistent, collection `pakistan_laws` | One collection; `law_id` on every chunk |
| Keyword search | Hand-rolled Okapi BM25 in `src/retrieval.py` | No extra dependency |
| Fusion | Reciprocal Rank Fusion (`RRF_K=20`) | Mixes semantic + keyword ranks |
| LLM | Groq API, `llama-3.3-70b-versatile`, temperature 0 | Free tier; `LLM_PROVIDER` in config is **not wired** — Groq client is constructed directly |
| Web | stdlib `ThreadingHTTPServer` + `static/*.html/css/js` | No FastAPI/Flask |
| Config | `.env` via python-dotenv | API key, model names, retrieval knobs |
| Tests | pytest | Registry, parser, retrieval math, guardrails, a few HTTP checks |
| PDF extract | pypdf (`src/extract_pdf.py`); drafts used pdfplumber in `fetch_laws.py` | Extract, never retype |

**Not used (planned or stubbed):** Ollama dispatch, `HYBRID_VECTOR_WEIGHT` (config exists, retrieval never reads it), cross-encoder rerank (`RERANK_MODEL` empty).

---

## 4. How the important pieces actually behave

### Registry (`src/law_registry.py`)

One dict per Act: file path, section regex, hint keywords, definition sections to always append, expected section count. A law is “loaded” iff its `data/raw/...` file exists. Refusals and the benchmark use the **loaded** list, not the full registry.

### Parser (`src/parser.py`)

Pakistani gazettes start with a table of contents that looks like body headings. The parser drops ToC-style hits (short, no body dash) so each section number appears once. Sections longer than 1,500 characters split on `(1)`, `(a)`, etc. Validation writes 20 random full sections for the owner to compare to the PDF.

### Retrieval (`src/retrieval.py`)

Always searches the whole collection. Keywords never exclude a law; they multiply fused score by at most 5%. After fusion, scores are **rescaled so the best hit is 1.0**. Linked definition sections (`always_include_sections`) are queried by metadata filter and appended.

### Generator (`src/generator.py`)

System prompt is filled with the Act titles actually retrieved. Rules: cite or do not claim; no training-data law; match user language; always disclaimer. Answers cached in `data/processed/llm_cache.json`. `validate_citations` is **observational** — it does not rewrite the answer.

### Scope filter

Regex bags: criminal, family, cybercrime, tax, foreign place names. Criminal/family/cybercrime refuse **only if that category has no loaded file**. Tax and foreign always refuse.

### Web UI

Chat in the browser, history in memory (not persisted). Language buttons only change placeholder and text direction; the model infers language from the question. Markdown-ish formatting is done in JS after HTML-escaping.

---

## 5. Bugs and weak points (with fixes)

Severity: **P0** user-visible wrong legal behaviour · **P1** reliability / safety of the pipeline · **P2** hygiene, docs, scale.

### P0 — Retrieval “min score” cannot fire

**Where:** `src/retrieval.py` normalizes fused scores by dividing by the best score, then compares `top[0]["fused_score"]` to `RETRIEVAL_MIN_SCORE` (0.35).

**Why it is wrong:** After that division the best hit is always `1.0` (unless every score is 0). Irrelevant questions still retrieve *something* and the LLM is asked to answer from the wrong Acts.

**Fix:** Apply the threshold on the **raw** RRF (or hybrid) score *before* normalizing for display. Calibrate the cutoff on a labeled set at Gate 1. Keep the 0–1 display scores only for logging/UI.

### P0 — Scope check stops at the first keyword

**Where:** `detect_scope` loops topics and **returns immediately** when any pattern matches. If that topic’s category is loaded, it returns `in_scope: True` and never inspects later topics.

**Why it is wrong:** “Can I file an FIR in London?” matches `FIR` (criminal, now loaded) and **never** sees `London`. Foreign / tax refusals can be skipped whenever an in-scope legal word appears first. Dict order currently puts criminal before foreign, so this is live.

**Fix:** Collect **all** matching topics. If any is foreign jurisdiction or tax, refuse. If a matched category is unloaded, refuse. Only then allow retrieval. Add tests for mixed questions (FIR+London, rent+FBR, khula+Dubai).

### P0 — Hallucinated section numbers are still shown

**Where:** `generate_answer` fills `citations["unsupported"]` but still returns the raw LLM text. The UI does not surface unsupported cites.

**Why it is wrong:** The main product risk is a confident wrong `[Act - Section]`. Detection exists; enforcement does not.

**Fix:** If unsupported citations exist: strip those sentences, or append a warning and drop them, or regenerate once with a “you cited X which was not in context” repair prompt. Never hide the flag from the UI. Prefer parsing the required `[Act Name - Section X]` form, not bare `Section 15` (PPC and tenancy both have a 15).

### P0 — Linked definitions can attach the wrong Act

**Where:** After retrieval, missing `always_include_sections` numbers are looked up as “any registry law that lists this number,” then `law_id[0]` is used.

**Why it is wrong:** Section `"2"` is a definitions section for PECA, MFLO, consumer, and others. A consumer hit can inject **PECA section 2**. That is cross-contamination the plan explicitly forbade.

**Fix:** Resolve linked sections **per retrieved `law_id`**, not by global section number. Query `where: {law_id: this_chunk.law_id, section_number: "2"}`.

### P1 — Empty index is only handled in verbose CLI

**Where:** `bot.ask` checks `collection.count() == 0` only inside `if verbose:`.

**Why it is wrong:** Web and normal CLI get a generic “laws do not address this” when Chroma is empty, which looks like a legal refusal.

**Fix:** Always check count (or a dedicated health flag) and return the index-setup instructions.

### P1 — Follow-up detector is too greedy

**Where:** `_is_followup_query` treats **any question of ≤ 4 words** as a follow-up and concatenates the previous user turn for retrieval.

**Why it is wrong:** “What is murder?” after a rent question searches `…rent… What is murder?` and can mix Acts. Words like `penalty` / `fine` / `appeal` are always treated as follow-ups.

**Fix:** Require a pronoun/ellipsis **or** an explicit follow-up phrase; do not use raw length. Keep a short coreference rewrite via the LLM only when those fire. Add tests: short new-topic questions must not inherit history.

### P1 — Answer cache version never bumped

**Where:** `PROMPT_VERSION = "2B-1"` in `src/config.py` while prompts, registry, and languages have moved on. Cache is a JSON file rewritten on every miss.

**Why it is wrong:** Stale answers from the PECA+tenancy era can be served. Under `ThreadingHTTPServer`, read-modify-write of that file is not locked — concurrent `/api/ask` can clobber the cache. The file grows without bound.

**Fix:** Bump `PROMPT_VERSION` on every prompt or generation-logic change. File lock (or skip disk cache in web mode). Cap entries / TTL. Do not cache `Error:` strings.

### P1 — Keyword scope is English-centric and coarse

**Where:** `OUT_OF_SCOPE_PATTERNS` are mostly English (`theft`, `divorce`, `WhatsApp`). Urdu/Roman Urdu criminal questions may skip the filter and depend entirely on retrieval.

**Fix:** Add Roman Urdu and Urdu terms already used in `LEGAL_SYNONYMS`. Keep refusals category-based, not a second router.

### P1 — Web server is a demo, not a product host

**Where:** `src/server.py` — CORS `*`, no body-size cap (`Content-Length` trusted), no timeouts, shared process-wide Chroma/embedding/LLM cache, `top_k` taken from the client (default **8** vs config **10**).

**Why it is wrong:** Fine on `127.0.0.1` for the owner. Unsafe if bound to a LAN. Client-chosen `top_k` changes grounding. LLM output is escaped before markdown (good), but there is no rate limit on Groq spend.

**Fix:** Ignore client `top_k` or clamp it. Cap `Content-Length` (e.g. 32 KB). Drop CORS `*` or restrict origin. Do not bind `0.0.0.0` until auth exists. Optional: FastAPI + one worker if you need production.

### P1 — Footgun: `python -m src.vector_store` wipes the index

**Where:** Module `__main__` upserts toy chunks then `reset_collection()`.

**Fix:** Remove the reset from `__main__`, or require an env flag. README already warns; the code should not be able to destroy 1,635 embeddings by accident.

### P1 — Ground-truth and live eval are not trustworthy yet

**Where:** 0/114 questions owner-verified; `evaluation_results.json` is from 2026-10-22 with two laws. PPC/CrPC mis-cites are high harm.

**Fix:** Close Gate 1 on tenancy+PECA first. Re-run live eval. Do not quote percentages. Extra human review for criminal answers.

### P2 — Config dead knobs and docs drift

- `HYBRID_VECTOR_WEIGHT` is never applied (fusion is rank-based RRF only). Either implement a weighted score mix or delete the setting.
- `LLM_PROVIDER` is unused; Groq is hardcoded. Implement a thin `generate()` or drop the setting.
- README lists Family Courts Act as Federal; registry correctly says **Punjab**.
- Tenancy registry `source_url` / `downloaded_on` still `None`.
- UI language toggle does not pass `lang` to the API (acceptable if the question text is in that language).
- `MAX_TOKENS = 1024` will truncate long multi-section criminal answers — raise for those categories or stream.
- BM25 is rebuilt and scored over all 1,635 docs **every query** in Python. Fine at this size; if the corpus grows, persist BM25 and cap the keyword candidate list.
- Benchmark language field is `en` only — Urdu quality is unmeasured.
- `formatLegalMarkdown` numbered-list regex can wrap lines that start with `15. Title` as `<li>` if the model echoes a heading.

---

## 6. Suggested fix order

1. **Correctness (do these before any public demo of criminal answers)**  
   Threshold on raw scores · scope collects all topics · link definitions by `law_id` · strip or flag unsupported citations using `[Act - Section]` · empty-index message in all modes.

2. **Cache and follow-ups**  
   Bump `PROMPT_VERSION` · lock or disable disk cache in the web server · tighten follow-up detection.

3. **Measurement**  
   Owner PDF spot-check · verify tenancy/PECA expected cites · live `python -m tests.evaluate` labelled unverified until Gate 1.

4. **Hygiene**  
   Align README jurisdiction · remove or implement dead config · neutralize `vector_store` `__main__` reset · clamp API `top_k`.

---

## 7. What is already solid

- Registry as the only place for law names and regexes.
- ToC-aware parser with expected-count checks and owner spot-check dumps.
- Hybrid search over **all** laws instead of a brittle topic router (the original plan’s main architecture fix).
- Dynamic prompt that names only retrieved Acts.
- Stage-aware benchmark so adding PPC does not break old “refuse FIR” items.
- HTML-escape before injecting model text into the chat DOM.
- Zero paid infrastructure for embeddings and storage.

The remaining work is not “build RAG.” It is **stop the known ways a wrong section can reach a citizen**, then **prove** citation quality on owner-verified questions.
