# How Pakistan Law Bot Works — Tech, Weak Points, Fixes

**Date:** 2026-10-25 · Companion to `PROJECT_FULL_REPORT.md` (status and corpus). This file is the **mechanics and defect** report.

---

## 1. What the product does

A user asks a question about Pakistani statute (English, Roman Urdu, or Urdu). The bot:

1. Refuses immediately if the question is tax, a foreign jurisdiction, or a legal category with **no loaded Act**.
2. Otherwise **searches every loaded Act** (not one guessed topic).
3. Sends the top statutory chunks to an LLM with a hard “cite only this text” prompt.
4. Returns an answer plus a legal-information disclaimer.

It is **not** a lawyer, not a case-law search, and not a form-filing tool.

---

## 2. End-to-end path (one question)

```text
Browser / CLI
    │  POST /api/ask  or  bot.ask()
    ▼
detect_scope()                  keyword pre-filter (registry-aware)
    │  refuse → done
    ▼
optional follow-up rewrite      prepend last user question if short/pronouns
    ▼
hybrid search                   Chroma vector + BM25 → RRF → top-K
    │  (threshold intended here — see Bug A)
    ▼
inject always_include sections  e.g. definitions (see Bug B)
    ▼
format_context()                "Law / Chapter / Section" headers + text
    ▼
Groq Llama 3.3 70B              temperature 0, cached by prompt hash
    ▼
ensure_disclaimer()
validate_citations()            flags unsupported section numbers (not stripped)
    ▼
JSON / CLI print / HTML bubble
```

**Index path (once per corpus change):** owner PDF → `src/extract_pdf.py` → `data/raw/<category>/*.txt` → `python -m src.parser` → owner reads `validation_report.txt` → `python -m src.bot --index`.

The parser **never** reads `data/source_pdfs/` or `data/raw_draft/`. Those are provenance and unreviewed drafts.

---

## 3. Technology in use

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.10+ (verified 3.13.5 / Windows) | Single process, easy local run |
| Embeddings | `sentence-transformers` `paraphrase-multilingual-MiniLM-L12-v2` | Local, free, Urdu/English in one vector space |
| Vector DB | ChromaDB persistent dir `data/chroma_db/`, collection `pakistan_laws` | One collection; `law_id` on every chunk |
| Keyword search | In-process Okapi BM25 | No extra service |
| Fusion | Reciprocal Rank Fusion (`RRF_K=20`) | Combines dense + sparse ranks |
| LLM | Groq API, `llama-3.3-70b-versatile`, temp 0 | Free-tier chat; deterministic for cache |
| PDF extract | `pypdf` (`src/extract_pdf.py`); `fetch_laws.py` used pdfplumber for drafts | Extract, never retype |
| Web | stdlib `ThreadingHTTPServer` + `static/` HTML/CSS/JS | No FastAPI/Flask dependency |
| Config | `.env` via python-dotenv | API key stays out of git |
| Tests | pytest | Registry, parser, retrieval math, guardrails, HTTP smoke |

**Configured but unused:** `LLM_PROVIDER` (Groq is hardcoded in `generator.call_llm`), `HYBRID_VECTOR_WEIGHT` (fusion is RRF ranks, not a weighted score mix), `RERANK_MODEL` (empty → no cross-encoder).

**Interfaces**

| Surface | Entry |
|---|---|
| Interactive CLI | `python -m src.bot` |
| One-shot | `python -m src.bot --ask "…"` |
| Web + REST | `python -m src.bot --web` → `http://127.0.0.1:8000` |
| REST | `GET /api/health\|laws\|stats`, `POST /api/ask` |

---

## 4. Module map

| File | Job |
|---|---|
| `src/law_registry.py` | Single source of Act metadata, regexes, hint keywords, linked definition sections |
| `src/parser.py` | ToC de-dupe, section extract, subsection split, validation report, `chunks.json` |
| `src/vector_store.py` | Embed + upsert + kNN query |
| `src/retrieval.py` | Hybrid search, synonyms, jurisdiction footnote, linked definitions |
| `src/generator.py` | Prompt, refusals, Groq call, cache, citation scrape |
| `src/bot.py` | `ask()`, CLI, `--index` / `--web` |
| `src/server.py` | Static files + JSON API |
| `src/extract_pdf.py` | Owner PDF → UTF-8 |
| `src/config.py` | Paths and knobs |
| `static/app.js` | Chat, history, citation badges |

---

## 5. Bugs and weak points (with fixes)

Severity: **P0** user-visible correctness · **P1** safety / eval honesty · **P2** reliability · **P3** hygiene.

### P0 — A. Relevance threshold is dead

**Where:** `src/retrieval.py` `search()`, after RRF.

Scores are **normalized so the best hit is 1.0**, then compared to `RETRIEVAL_MIN_SCORE` (0.35). The best hit is therefore **always** ≥ threshold. `below_threshold` is effectively only true when the collection is empty.

**Effect:** Off-topic in-scope questions (or weak matches) still go to the LLM with the “least bad” chunks. The model is asked not to guess, but it often will. The “not covered by loaded laws” path almost never runs.

**Fix:** Compare the **raw** fused score (or vector distance) to the threshold **before** min-max / best-hit normalization. Tune the cutoff on a labeled set at Gate 1. Add a unit test: a gibberish query with a non-empty index must return `below_threshold=True`.

---

### P0 — B. Linked definitions can pull the wrong Act

**Where:** `retrieval.search()` `always_include_sections` block.

Missing section numbers are looked up as “first registry entry that lists this number.” Section `"2"` is a definitions section for PECA, MFLO, Family Courts, and Consumer. Registry order means **PECA s.2 can be injected into a consumer or family answer**.

**Fix:** Keep `(law_id, section_number)` pairs from the **hits already in `top`**, not a global number lookup. Query Chroma with that `law_id`. Test: consumer-only top-K must append `punjab_consumer_2005` s.2, never `peca_2016` s.2.

---

### P0 — C. Foreign / tax refusals lose to the first keyword

**Where:** `generator.detect_scope()`.

The loop **returns on the first matching topic**. `"How do I file an FIR in London?"` matches `FIR` (criminal). Criminal is loaded → `in_scope: True`. `"London"` is never checked.

**Fix:** Scan **all** topic groups. If any hit is `foreign jurisdiction` or `tax`, refuse. Only then apply category-loaded logic. Add tests for mixed questions.

---

### P1 — D. Hallucinated citations are logged, not blocked

**Where:** `generator.generate_answer()` + `validate_citations()`.

The scraper looks for `Section 15`, **not** `[Act Name - Section 15]`. Numbers are not bound to an Act, so PPC s.15 and tenancy s.15 collide. Unsupported cites are attached to the JSON but **the user still sees the raw LLM text**.

**Fix:** Parse the bracket format; key by `(act, section)`. If `unsupported` is non-empty, strip those sentences or regenerate once with a “you cited X which was not in context” repair prompt. Never show an ungrounded section number as fact. Evaluator should use the same parser.

---

### P1 — E. No trustworthy accuracy number (Gate 1 open)

**Where:** process, not a line of code. 0/114 questions owner-verified. Last live file is 2026-10-22, two laws only.

**Fix:** Owner verifies tenancy then PECA expected cites against `data/raw/`. Re-run `python -m tests.evaluate`. Report n and verified flag with every percentage. Do not quote Phase-1 10/10 as current quality.

---

### P1 — F. Empty index is a silent “not covered” in production

**Where:** `bot.ask()`. The “knowledge base is empty, run parser/index” message runs only if `verbose=True`. Web/`--ask` hit empty Chroma and look like a legal refusal.

**Fix:** If `collection.count()==0`, return a setup error for all paths. `/api/stats` should expose `status: "empty"` and the UI should disable send.

---

### P1 — G. Stale LLM cache (`PROMPT_VERSION = "2B-1"`)

Prompt, registry, and languages moved on through 2C–2E. Cache key includes version, so **old answers stay valid forever** until the string is bumped.

**Fix:** Bump to e.g. `2E-1` on every prompt/guardrail change. Optionally include a hash of `SYSTEM_PROMPT_TEMPLATE`. Delete `data/processed/llm_cache.json` after bump.

---

### P2 — H. Follow-ups are over-eager

**Where:** `bot._is_followup_query()` — **any question with ≤ 4 words** is a follow-up.

`"What is murder?"` after a rent chat is retrieved as `"<old rent question> What is murder?"`, mixing Acts.

**Fix:** Require a pronoun / `what about` / `agar` **or** explicit session “continue” ; do not use length alone. Cap history sent to Groq (already last 4 turns) but retrieval rewrite should be conservative.

---

### P2 — I. Answer cache is not safe under the threaded web server

**Where:** `call_llm` reads whole JSON, writes whole JSON. `ThreadingHTTPServer` can overlap writes. Cache file grows without bound.

**Fix:** `threading.Lock` around load/save, or SQLite. Cap entries (LRU). Don’t cache `Error:` strings if that path is ever keyed.

---

### P2 — J. Web API hardening

- `Access-Control-Allow-Origin: *` (fine on localhost; dangerous if bound to `0.0.0.0`).
- No `Content-Length` cap on `POST /api/ask`.
- `top_k` taken from the client (default **8**, config is **10**) — clients can request a huge K.
- LLM HTML is escaped in `formatLegalMarkdown` (good). Error path also goes through that formatter after `escapeHtml` in the template string — double-escape on errors only, cosmetic.

**Fix:** Bind 127.0.0.1 by default (already). Drop `*` CORS or lock to the UI origin. Cap body (e.g. 32 KiB) and clamp `top_k` to 1..20 server-side. Ignore client `top_k` unless you need it for eval.

---

### P2 — K. `python -m src.vector_store` wipes the index

`__main__` upserts samples then **`reset_collection()`**. README warns; the footgun remains.

**Fix:** Remove reset from `__main__`, or require `LAWBOT_ALLOW_RESET=1`. Indexing stays `python -m src.bot --index`.

---

### P2 — L. Index skip heuristic

`build_index` skips if `collection.count() >= len(chunks)` without `--force`. A **smaller** new corpus after removing a law would not re-index; a same-size rewrite of text would also skip.

**Fix:** Store a content hash / chunk-file mtime in collection metadata; re-index on mismatch.

---

### P3 — M. Dead config and docs drift

- `HYBRID_VECTOR_WEIGHT` and `LLM_PROVIDER` unused.
- README: Family Courts Act “Federal”; registry: **Punjab**.
- Language chips in the UI only change the placeholder; the API does not receive `language`.
- `MAX_TOKENS=1024` will truncate long PPC/CrPC walkthroughs.
- BM25 rebuilds the whole 1,635-doc scorer **every query** (OK now; cache the `BM25` object next to the corpus cache).
- Chroma metadata may include `amended_up_to: null` for some laws — some Chroma versions reject `None`.

**Fix:** Wire or delete unused knobs. Align README with the registry. Pass `language` from UI or drop the chips. Raise `max_tokens` for criminal questions. Coerce `None` metadata to omit the key.

---

### P3 — N. Data / process gaps (not code crashes)

- All `data/source_log.json` entries: `verified_by_owner: false`.
- Optional Punjab Rented Premises Rules 2010 not loaded.
- Criminal statutes are high-harm if mis-cited (see A–D).
- Benchmark language field is `en` only while the product claims Urdu.

**Fix:** Owner PDF spot-check using the validation report; add a small Urdu/Roman Urdu eval slice after Gate 1.

---

## 6. Suggested fix order

1. **P0 A+B+C** in `retrieval.py` / `detect_scope` + unit tests (no API key).
2. Bump `PROMPT_VERSION`, clear LLM cache.
3. Empty-index error on every `ask` path; clamp API `top_k`.
4. Citation parser + don’t display unsupported cites.
5. Owner Gate 1 verification, then a full live eval.
6. Cache lock, remove vector-store reset footgun, README/registry alignment.

---

*Read from: `src/bot.py`, `src/retrieval.py`, `src/generator.py`, `src/server.py`, `src/vector_store.py`, `src/parser.py`, `src/config.py`, `src/law_registry.py`, `static/app.js`, `tests/evaluation_results.json`.*
