# Bug-fix, remaining core work, and accuracy verification

**For the implementing agent.** Project root: `D:\Work\Projects\LawBot`. Use the existing `venv`.  
**Out of scope:** Phase 3 (Streamlit rebuild, WhatsApp/Twilio, new Urdu UI, new conversation-product work). A web UI, session history, and LLM cache already exist — harden them only where this plan names a defect. Do not add channels or rewrite the frontend.

**Companion docs (read, do not replace unless a task says so):** `NEXT_PHASE_PLAN_v2.md` (gates, data rules), `SYSTEM_HOW_IT_WORKS.md` (defect write-up), `PROJECT_FULL_REPORT.md` (corpus snapshot).

---

## 0. Rules (read first)

1. **Never write, recall, or patch statutory text.** Parser reads only `data/raw/`. Do not invent sections. If a raw file is missing or validation fails, stop and report.
2. **No law names, section regexes, or topic keywords outside `src/law_registry.py`.** Tests may use law_ids.
3. **Work in waves, in order.** Finish a wave’s tests before starting the next. Stop at every **GATE** and wait for the owner.
4. **No unexplained percentages.** Every accuracy number must include: `n` questions run, `n_verified` (owner-checked against official text), and that unverified items are **excluded** from headline %.
5. **Stay $0:** local embeddings, local ChromaDB, Groq free tier. Keep retry/backoff and the LLM cache.
6. **Do not implement Phase 3.** Do not add Streamlit, WhatsApp, or extra languages to the benchmark until the owner asks.
7. **Do not commit or push** unless the owner asks.
8. **Do not run `python -m src.vector_store`** — its `__main__` resets the collection (Wave 3 removes that). Index only with `python -m src.bot --index`.
9. Ignore the “only tenancy is loaded” paragraph in `NEXT_PHASE_PLAN_v2.md` § Current project state. **All 8 registered laws are in `data/raw/` and indexed.** That plan’s *data-integrity rules* still apply.

---

## 1. Current facts (do not re-audit from scratch)

| Fact | Value |
|---|---|
| Loaded Acts | 8 (`src/law_registry.py` + files under `data/raw/`) |
| Validated sections / chunks | 1,308 / 1,635 |
| Benchmark | `tests/benchmark_dataset.json` — 114 questions, **`verified` false on all** |
| Last live eval | `tests/evaluation_results.json` — 2026-10-22, **2 laws only**, 6 questions — **stale, do not quote** |
| LLM | Groq `llama-3.3-70b-versatile`, `PROMPT_VERSION = "2B-1"` in `src/config.py` |
| Ask entry | `src.bot.ask()` — CLI, `--ask`, and `POST /api/ask` |

---

## 2. Goal of this plan

Make the **shared `ask()` path** correct and measurable:

1. Fix P0 retrieval/scope bugs so refusals and “not covered” actually work.
2. Stop showing ungrounded citations; fail closed on empty index; invalidate stale LLM cache.
3. Harden cache, follow-ups, and API limits (still not Phase 3).
4. Give the owner a **Gate 1** procedure, then run a live eval whose reported % uses **only owner-verified** items.

Success is not “Phase 3 done.” Success is: unit tests for A/B/C/D pass, full `pytest` green, offline evaluate green, and a live report that states `n` and `n_verified` honestly.

---

## Wave 1 — P0 correctness (do this first)

No Groq key required for the new unit tests. Do not re-index unless a test needs Chroma; prefer **pure functions** extracted from `search()` / `detect_scope()`.

### 1-A. Relevance threshold is dead — `src/retrieval.py`

**Bug:** After RRF, scores are divided by the best score (top hit becomes `1.0`), then compared to `RETRIEVAL_MIN_SCORE` (0.35). `below_threshold` is almost never true.

**Fix:**

- Keep a **raw** fused score (or a documented distance) on each candidate.
- Apply `RETRIEVAL_MIN_SCORE` to the **raw best score**, *then* normalize 0–1 for display/LLM ranking if you still want relative ranks.
- Empty collection → `results=[]`, `below_threshold=True` (already).
- Leave the numeric cutoff in `src/config.py` (`RETRIEVAL_MIN_SCORE`). Do not “tune” it by guessing; if tests need a fixture, inject the threshold as an argument.

**Tests** (add to `tests/test_retrieval.py` or a new `tests/test_retrieval_search.py`):

- Pure helper: given fused scores `{A: 0.10, B: 0.08}` and min=0.35 → `below_threshold True`.
- Given `{A: 0.90, B: 0.40}` and min=0.35 → `below_threshold False`, and after normalize A is 1.0, B is 0.40/0.90.
- Document in the test name that **normalization must not run before the threshold**.

If `search()` cannot be tested without Chroma, extract `_apply_threshold_and_normalize(candidates, min_score) -> (top, below)`.

**Done when:** a comment in `search()` states “threshold uses raw fused score”; tests fail if someone normalizes first.

---

### 1-B. Linked definitions pull the wrong Act — `src/retrieval.py`

**Bug:** Missing `always_include_sections` are resolved as “first registry law that lists this section number.” Section `"2"` exists on PECA, MFLO, Family Courts, Consumer → PECA wins.

**Fix:** Build extras from **`(law_id, section_number)` of chunks already in `top`**, not from a global number. Query Chroma `where` with that `law_id` + `section_number`. Do not inject another Act’s definitions.

Extract a pure function, e.g. `linked_section_keys(top_hits, registry) -> list[tuple[law_id, section]]`, and unit-test it **without** Chroma:

- Top hits only `punjab_consumer_2005` → extra key `("punjab_consumer_2005", "2")` only.
- Top hits PECA + tenancy (tenancy has empty `always_include_sections`) → extra PECA `"2"` only, never consumer/MFLO.
- Two laws both needing `"2"` → both `(law_id, "2")` pairs.

**Done when:** those tests pass; the Chroma `where` clause uses the pair’s `law_id`.

---

### 1-C. First keyword wins over foreign/tax — `src/generator.py` `detect_scope()`

**Bug:** Loop returns on the first topic. `"How do I file an FIR in London?"` matches FIR (criminal loaded) → in scope; London never checked.

**Fix:** Scan **all** `OUT_OF_SCOPE_PATTERNS`. If **any** hit is `foreign jurisdiction` or `tax`, refuse those (tax has no category; foreign always refuses). Only then apply “category loaded → in scope.”

**Tests** in `tests/test_generator_logic.py` (monkeypatch `loaded_categories` as existing tests do):

| Question | Expect |
|---|---|
| `How do I file an FIR in London?` | `in_scope False`, topic foreign |
| `Landlord in Dubai and also FIR` | foreign refuse |
| `How do I pay FBR sales tax after theft?` | tax refuse |
| `How do I file an FIR for motorcycle theft?` | in scope if `criminal` loaded; refuse if not |
| `Can my landlord evict me?` | in scope |

**Done when:** mixed foreign+criminal and tax+criminal tests pass.

**Wave 1 gate (agent, not owner):** `python -m pytest tests/test_retrieval.py tests/test_generator_logic.py tests/test_parser.py tests/test_law_registry.py -q` all pass.

---

## Wave 2 — P1 safety on the answer path

### 2-D. Citations: parse Act+section; do not show unsupported cites

**Files:** `src/generator.py` (`validate_citations`, `generate_answer`); `tests/evaluate.py` (`check_citation_precision_recall`); `tests/test_generator_logic.py`; `tests/test_evaluate_logic.py`.

**Bug:** Regex is `Section\s+(\d+)` only. PPC s.15 vs tenancy s.15 collide. `unsupported` is JSON-only; the user still sees the hallucinated number.

**Fix:**

1. One shared parser (put it in `generator.py` and import from `evaluate.py`, or a tiny `src/citations.py` — **no new package**). Match `[Act Name - Section X]` and `Section X(y)` with optional Act. Key by `(normalized_act_or_unknown, section)`.
2. A cite is **supported** only if that section number appears in **retrieved chunk metadata for a matching Act** (if Act omitted, require the section to appear in retrieved metadata, not merely in chunk body text — the current body-text fallback is too loose).
3. If `unsupported` is non-empty: **do not leave them in the user-visible answer**. Preferred: one repair LLM call with the unsupported list; fallback if repair fails or cache/rate-limit: append a short note and **strip sentences that contain only unsupported sections**. Do not silently drop the whole answer.
4. Bump `PROMPT_VERSION` in the same wave as 2-G so old cached answers are not reused.

**Tests:**

- `[Punjab Rented Premises Act, 2009 - Section 15]` supported if retrieved metadata has that law + `15`.
- Same section number from a different Act in the answer, not in retrieval → unsupported and **removed or footnoted** in `answer`.
- Evaluator precision/recall uses the same parser (update `tests/test_evaluate_logic.py`).

**Done when:** unit tests prove unsupported cites are not in `result["answer"]` (or are clearly marked non-statutory), and evaluate logic tests still pass.

---

### 2-F. Empty index must look like a setup error — `src/bot.py`, `src/server.py`

**Bug:** “Knowledge base is empty…” only runs if `verbose=True`. Production `--ask` / web look like a legal “not covered” refusal.

**Fix:** If collection count is 0, `ask()` always returns a setup error (`in_scope` can stay true, `not_covered` false, no legal refusal wording). `/api/stats` `status` field: `"empty"` vs `"ready"`. Do **not** build a new UI for this (Phase 3). Optional one-line check in existing `static/app.js` to disable send if stats status is empty is allowed.

**Tests:** `tests/test_server_and_memory.py` or bot tests with monkeypatched empty collection.

---

### 2-G. Stale LLM cache

**Fix:** Set `PROMPT_VERSION` to `2E-1` (or `2E-2` if you already bumped in 2-D). Delete `data/processed/llm_cache.json` if present (it is gitignored; deleting locally is required). Optionally fold a short hash of `SYSTEM_PROMPT_TEMPLATE` into `_cache_key` so forgotten bumps hurt less.

**Wave 2 gate:** `python -m pytest tests/ -q` (full suite). If `/api/ask` tests need a live index, keep them as they are; do not skip unrelated failures.

---

## Wave 3 — P2 reliability (still not Phase 3)

### 3-H. Follow-up detector — `src/bot.py` `_is_followup_query`

**Bug:** Any question with ≤ 4 words is treated as a follow-up → `"What is murder?"` after a rent chat concatenates into retrieval.

**Fix:** Remove the length-only rule. Keep pronoun set, `_FOLLOWUP_PHRASES`, and Roman Urdu phrases. Add tests: 4-word standalone criminal question with history about rent → **must not** concatenate. `"What about the deposit?"` with rent history → concatenate.

### 3-I. Cache thread-safety — `src/generator.py`

`threading.Lock` around load-modify-save. Cap cache size (e.g. 500 entries, drop oldest). Do not cache strings starting with `Error:`.

### 3-J. API clamps — `src/server.py`

- Cap POST body (e.g. 32 KiB) → 413 if larger.
- Clamp `top_k` to `1..20`; default from `config.TOP_K_RESULTS` (not hardcoded 8). Align `static/app.js` `top_k` with that default **or omit `top_k`** and let the server decide.
- Keep bind `127.0.0.1`. CORS `*` is acceptable while localhost-only; add a comment. Do not bind `0.0.0.0`.

### 3-K. Vector-store footgun — `src/vector_store.py`

Remove `reset_collection()` from `__main__` (keep a print that indexing is `python -m src.bot --index`). Keep `reset_collection` for `--index --force`.

### 3-L. Index skip heuristic — `src/bot.py` `build_index`

Skipping when `count >= len(chunks)` misses same-size rewrites. Store a hash of `chunks.json` (or count + mtime) in collection metadata; re-index on mismatch. `--force` still resets.

**Wave 3 gate:** `python -m pytest tests/ -q`.

---

## Wave 4 — Hygiene (small, do after 1–3)

| ID | Task |
|---|---|
| 4-M1 | `HYBRID_VECTOR_WEIGHT`: **delete** from config/`.env.example` or actually use it. Do not leave a dead knob. RRF-only is fine; if you keep RRF, delete the weight. |
| 4-M2 | `LLM_PROVIDER`: either a one-line dispatch that errors on non-`groq`, or delete the unused setting. Do not add a second provider. |
| 4-M3 | README: Family Courts Act jurisdiction must match registry (**Punjab**, not Federal). Scope-enforcement bullet in README is stale (criminal/family/cybercrime are loaded). |
| 4-M4 | Chroma metadata: omit keys whose value is `None` (e.g. `amended_up_to`) in `parser._finalize_chunk`. |
| 4-M5 | Cache the `BM25` object next to `_corpus_cache` so it is not rebuilt every query (same invalidation as corpus count). |

No new features. **Wave 4 gate:** pytest + `python -m tests.evaluate --offline`.

---

## Wave 5 — Accuracy harness (code, still no owner)

These make live numbers honest. They are **not** Phase 3 language expansion.

1. **Evaluator and generator share the citation parser** (if not done in 2-D).
2. Confirm `tests/evaluate.py` still **excludes** `verified`/`verified_by` null from headline % (read the file; keep that behavior). Print `n_verified` / `n_unverified` clearly in stdout and `tests/evaluation_results.json`.
3. Add `--ids TEN-001,TEN-002` (or `--prefix TEN`) so the owner can run a **small verified slice** without burning Groq quota on 114 items.
4. Offline mode must keep passing with 114 questions (structure only).
5. Do **not** mark any benchmark row `verified: true` yourself. Only the owner does that.

**Wave 5 gate:** `python -m tests.evaluate --offline` PASS; pytest PASS.

**GATE H (agent stop):** Report Waves 1–5: files changed, tests run, any leftover risk. **Wait for the owner** before live Groq eval and before editing `verified` flags.

---

## Wave 6 — Owner Gate 1 (accuracy ground truth)

**Owner does the legal checking. Agent prepares lists and applies owner decisions.**

### 6.1 PDF spot-check (owner)

Use `data/processed/validation_report.txt` (20 random sections per Act). Compare word-for-word to `data/source_pdfs/...`. Agent does not “fix” mismatches by rewriting statute. If a mismatch is real: stop, report law_id + section, wait.

### 6.2 Re-derive tenancy expected citations (owner + agent)

Plan v2 still flags old tenancy items. For every `TEN-*` row in `tests/benchmark_dataset.json`:

- Open `data/raw/tenancy_punjab/punjab_rented_premises_act_2009.txt`.
- Set `expected_citations` from **that file**, not from model memory.
- List every change in the agent’s report for the owner.
- Owner sets `verified: true` / `verified_by` only after agreeing.

Then the same for **PECA** (`PECA-*`), then stop unless the owner asks for FAM/CRIM/CON.

Known v2 hints (confirm in the raw file, do not assume): s.12 obligations of landlord, s.13 tenant, s.10 effect of other agreement, s.15 grounds for eviction.

### 6.3 Do not expand the dataset in this plan

114 questions is enough. No Urdu split, no WhatsApp items, no new OUT-* unless a Wave 1 fix requires one mixed foreign+FIR row (allowed if it is `out_of_scope` and owner-verified).

**GATE 1 (owner):** At least the tenancy in-scope items the owner cares about (target: all `TEN-*` that are `in_scope` / `not_covered_by_text`) marked verified. Agent must not proceed to Wave 7 headline % until that exists. If the owner wants a PECA slice too, wait for those flags.

---

## Wave 7 — Live accuracy run

**Needs:** Groq key in `.env`, current index (`python -m src.bot --index --force` if chunks or embeddings changed in earlier waves).

1. Bump cache already done (2-G). Optional: delete `llm_cache.json` again before the official run.
2. Run a **verified-only** slice first:  
   `python -m tests.evaluate --prefix TEN`  
   (or `--ids` once implemented). Confirm Groq/index work.
3. Full run: `python -m tests.evaluate`  
   Writes `tests/evaluation_results.json`.
4. Report **only**:
   - `n_verified`, citation precision/recall, refusal accuracy, not-covered calibration, disclaimer rate — **on verified rows**.
   - `n_unverified` run for smoke but **not** in the headline %.
   - Failures with question id, expected vs cited, answer preview.
5. If P0-A threshold is too strict or too loose on verified TEN items, **propose** a new `RETRIEVAL_MIN_SCORE` with the table of true/false not-covered; do not silently change it without owner OK.

**GATE 2 (owner):** Accept or reject the verified-% report. No Phase 3 until the owner says so.

---

## 3. Commands cheat sheet

```text
venv\Scripts\activate
python -m pytest tests/ -q
python -m tests.evaluate --offline
python -m src.parser                          # only if raw text changed; owner must read the report
python -m src.bot --index --force             # after accepted validation, or after embedding/chunk changes
python -m tests.evaluate --prefix TEN         # after Wave 5; needs API key
python -m tests.evaluate                      # full live; needs API key + index
```

Never: `python -m src.vector_store` to index.

---

## 4. Explicitly not in this plan (Phase 3)

- Streamlit (or replacing `static/` + `server.py`)
- WhatsApp / Twilio
- Adding Urdu/Roman Urdu rows to the benchmark
- New product UX (auth, accounts, deploy to the public internet)

Existing web/CLI may be touched **only** for defects named above (empty index, `top_k`, follow-up detector).

---

## 5. Suggested agent commit messages (if the owner asks to commit)

Do not commit until asked. If asked, one commit per wave is enough, e.g.:

- `Fix retrieval threshold, linked definitions, and mixed-jurisdiction scope`
- `Ground citations in retrieved Act+section and fail closed on empty index`
- `Harden follow-up detection, LLM cache, and index skip`

Do not commit `.env`, `data/chroma_db/`, or `data/processed/llm_cache.json`.

---

## 6. Definition of done

- [x] Waves 1–5 code + tests merged in the working tree
- [x] `python -m pytest tests/` pass
- [x] `python -m tests.evaluate --offline` pass
- [x] Owner completed Gate 1 for at least tenancy verified flags
- [x] Live eval report with `n_verified` ≥ 1 and **no** unverified % presented as product quality
- [x] Phase 3 items untouched as new work
