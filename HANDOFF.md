# FinSight handoff

Context for teammates (and their Claude Code) to continue this project. Written 31 Oct 2026 at the end of the first
build session. Read this first, then `README.md` for setup.

**Status in one line:** a working bank statement analyser for the hackathon's Problem 9, Level 1 complete and tested on
four datasets. Weak spot: Gujarati, Tamil and Hindi narrations. Nothing is committed to git yet (branch `main`, no commits).

---

## 1. The problem

Hackathon brief "9. Bank Statement & Financial Analysis": ingest bank statements (PDF in several layouts, CSV, Excel,
JSON), extract and reconcile every transaction with a reference to its file and page, classify transactions (salary,
business receipts, internal transfers, refunds/reversals, EMIs, rent, utilities, card payments…) with a visible reason,
calculate income, obligations, cash flow and balance trends with a breakdown of included and excluded transactions,
and let analysts correct a classification with dependent figures recalculated and the original preserved. It must
handle irregular income, duplicates, overlapping and incomplete statements and suspicious items **without inventing
missing information**. The organiser judges the running application, not slides.

Six scenarios: (1) salary despite description changes, (2) irregular/self-employed income, (3) transfers, refunds and
reversals excluded, (4) recurring obligations and cash-flow stress, (5) duplicate/overlapping/missing statements,
(6) unusual transactions flagged for review, not called fraud.

---

## 2. Design principles (do not break these)

1. **Rules and arithmetic decide; models only add evidence.** No LLM in the scoring path. Money is integer paise; floats never touch amounts.
2. **Reproducible.** Same inputs plus same versions give the same output. `PIPELINE_VERSION`, `RULES_VERSION`, `WEIGHTS_VERSION`, `QUESTION_BANK_VERSION` live in `backend/app/config.py` and are recorded in every analysis. **Bump `RULES_VERSION` whenever you change rules, weights or categories**, otherwise cached classification runs are reused (an analysis is skipped when its input hash, which includes versions, is unchanged).
3. **Traceable.** Every metric returns `included` and `excluded` (with reasons) transaction ids. Every transaction keeps file, page and row (`silver.txn_sources`).
4. **Never invent.** Missing months are `missing`, never zero. Unreadable rows and pages are quarantined with a reason. Uncertain items go to review; income excludes them until confirmed (a provisional figure is shown separately).
5. **Idempotent.** File SHA-256 per case, deterministic transaction ids (hash of account, date, amounts, narration token, balance, ordinal), stage outputs replaced in one DB transaction, `Idempotency-Key` on POSTs, unique override `event_id`, content-addressed gold snapshots.
6. **Flags say "review recommended", never "fraud".**
7. **PII masked by default.** Account numbers, UPI IDs, phones, cards, PAN, Aadhaar and holder names are masked in display and replaced with placeholders for classification. Clear values live only in the encrypted vault; reveal requires a reason and is audit-logged.

---

## 3. Architecture

A shareable architecture page (private Claude artifact, owner must share it): https://claude.ai/artifact/2MnC49jnbaqtznjNfxxVjg

**Medallion layers in one DuckDB file** (`data/finsight.duckdb`, schemas `bronze`, `silver`, `gold`, `knowledge`, `review`, `security`):

```
upload ─► bronze: files (sha256), pages (status per page), raw_rows (encrypted), quarantine (reason per item)
       ─► silver: accounts, statements (reconciliation), transactions, txn_sources, txn_links (pairs),
                  classification_runs + classifications (history kept), overrides (events), coverage, cross_checks,
                  document_checks (edit risk)
       ─► gold:   snapshots (content-addressed; metrics with lineage, flags, monthly table)
knowledge: semantic_examples (global seed + case corrections), periodic_patterns
review:    audit_log (hash chain), idempotency_keys, stage_runs
security:  pii_vault (Fernet-encrypted), egress_log
```

**Classification** (`backend/app/classify/engine.py`), three tiers:

1. **Hard gates** (never averaged): transfer pairs across the customer's own accounts (equal amount, opposite direction, ±1 day), bounce/return pairs, bounce charges, reversal/refund pairs (either direction, shared reference preferred).
2. **Weighted log-odds fusion** of signals: keyword rules (`rules.py`), entity lists (lenders, utilities), own-bank mentions, account trading pattern, periodic memory (monthly series, merged across employer renames), semantic memory (char n-gram TF-IDF kNN over approved examples), optional Jev answers. `P = softmax(scores)` with a baseline category per direction.
3. **Policy:** auto if P ≥ 0.90 and margin ≥ 0.30; review if P ≥ 0.60 or a near tie or a kNN disagreement; otherwise unclassified. Debits with no evidence default to General spending (see backlog: should go to review when the text is in an unreadable script).

**Corrections** (`review/overrides.py`): append an override event, write the narration to case-level semantic memory, re-run classification and gold, return a before/after diff. The model's own result and history are kept.

**Edit-risk score** (`validate/tamper.py`): structure signals (PDF editor or office producer, incremental saves, modified after creation, font/size mismatch inside a table, text printed over different text) plus arithmetic signals (unreconciled totals, balance-chain breaks). 0–100, levels none/low/medium/high. PDF libraries as producer are neutral.

---

## 4. Repository map

```
backend/app/
  main.py            FastAPI routes (also serves frontend/dist on :8000 if built)
  config.py          paths, versions, thresholds
  db.py              DuckDB schema and helpers
  money.py           paise parsing (Rs./₹/INR, Indian and Western grouping), date parsing incl. date+time cells
  analysis.py        silver -> gold orchestration, snapshots, diff
  evaluation.py      accuracy vs sample ground truth (Accuracy tab)
  ingest/            extract.py (PDF tables, watermark removal, CSV/XLSX/JSON), layout.py (column roles, header fields),
                     normalize.py (channel, counterparty, refs), service.py (upload pipeline)
  validate/          reconcile.py (row chain with misprint detection), tamper.py (edit risk)
  dedup/coverage.py  month coverage, gaps, overlaps, balance continuity between statements
  classify/          categories.py (categories + metric treatment), rules.py, periodic.py, semantic.py, engine.py, jev_client.py
  metrics/           effective.py (category in effect = latest override else latest run), engine.py (all metrics)
  flags/rules.py     all indicators
  review/overrides.py
  security/          crypto.py (HMAC tokens, vault), pii.py, egress.py, audit.py, rbac.py, log_scrub.py
backend/tests/       tests and evaluation harnesses (section 6)
datagen/             generate.py (2 English demo cases), multilingual.py (16 multilingual statements)
datasets/            multilingual_v1/ + README.md
sample_data/         generated demo cases, problem_files/ (corrupted + scanned PDF), tampered/ (edited PDFs for demos)
frontend/            React + TypeScript + Vite + Recharts UI
```

---

## 5. Running it

Windows notes: set `PYTHONIOENCODING=utf-8` for scripts that print ₹ or Indic text. Packages were installed into the
user site-packages during development; use a venv for a clean setup (see `README.md`).

```bash
pip install -r backend/requirements.txt pypdf
python datagen/generate.py
python datagen/multilingual.py
python -m uvicorn app.main:app --app-dir backend --port 8000
```

UI: either `cd frontend && npm install && npm run dev` (http://localhost:5173, proxies /api) or `npm run build` and use
http://localhost:8000. **The Vite dev server hung once during heavy background evaluations; the built UI on :8000 was reliable.**

Load demo data with the "Load sample cases" button or `curl -X POST http://127.0.0.1:8000/api/demo/load`.
Demo roles via the sidebar (headers `X-User`/`X-Role`): analyst, senior, auditor (read only), admin.

**Reset the local DB after changing tokenisation, rules or schema:** stop the API, delete `data/finsight.duckdb*` and
`data/files/`, restart, reload demo data. `GET /analysis` returns the latest stored snapshot and does not re-run.

---

## 6. Tests and evaluations

All tests create a throwaway DB in the temp folder.

| Command | What it checks | Latest result |
|---|---|---|
| `python backend/tests/test_brief_examples.py` | The brief's worked examples with assertions | Pass |
| `python backend/tests/test_review_flow.py` | Corrections, idempotency, RBAC, reveal logging, audit chain, re-upload | Pass |
| `python backend/tests/test_tokens.py` | Tokeniser keeps all scripts distinct | Pass |
| `python backend/tests/smoke.py` | Demo cases end to end | 99.2% / 99.5% category accuracy |
| `python backend/tests/eval_multilingual.py` | 16 multilingual statements, accuracy + efficiency | 62% overall (see below) |
| `python backend/tests/eval_hf_statements.py <train dir>` | AgamiAI PDFs vs JSON labels | see below |
| `python backend/tests/eval_tamper.py [--n 25] [--demo-out sample_data/tampered]` | Edit-risk detection | 162/162 edits caught |
| `python backend/tests/eval_vlm_dataset.py <zip>` | VLM dataset labels through the pipeline | see below |

Result JSON files are written next to the scripts (`*.json` in `backend/tests/`).

### Datasets used

| Dataset | Where | Notes |
|---|---|---|
| Demo cases | `sample_data/` (generated) | 2 customers, 2 PDF layouts + CSV/XLSX/JSON, all six scenarios planted, ground truth in `ground_truth.json` |
| Multilingual v1 | `datasets/multilingual_v1/` (generated) | 16 statements, 2,551 labelled rows: English, Hindi, Hinglish, Gujarati, Tamil. 8 dev / 8 held-out test with different wording. **Tune on dev only.** |
| AgamiAI Indian-Bank-Statements | `hf download AgamiAI/Indian-Bank-Statements --repo-type dataset --include "train/*"` (was saved to `Downloads/hf_indian_bank_statements`) | 400 business statements: 200 digital PDFs (2 layouts, diagonal watermark) + 200 scanned, JSON labels without categories. **Labels' own arithmetic is broken in 184/200 statements.** |
| VLM training dataset | `Downloads/vlm_training_dataset_1000_real.zip` (local only) | 2,913 page images + extraction JSON, Hindi/Gujarati narrations, no category labels |

### Latest numbers

- **AgamiAI digital PDFs (200):** row recall 99.2% (all misses are zero-amount `FAILED` lines, quarantined), row precision 100%, header fields 100%, balances 100%, narration ≥ 90% similar 100%, reversal recall 100%, reconciliation verdict correct for all 200, auto-decided 35% (type 1) / 56% (type 2) before the r2 rules. A re-run with r2 rules was in progress (`--out hf_eval_v2`); check `backend/tests/hf_eval_v2.json`. Scanned: 1,194 pages all reported `needs_ocr`.
- **Multilingual v1 (2,548 rows):** English 87%, Hinglish 82%, Hindi 65%, Gujarati 37%, Tamil 28% category accuracy. Hindi automatic decisions are only ~65% right (unreadable debits default to General spending). Income exact on salaried statements with Latin-script employers; badly underestimated for regional-language business statements.
- **VLM test split (120 statements, 7,527 rows):** ingestion 100%, reconciliation 120/120, 63% auto-decided, about 86% of a hand-checked sample of automatic decisions correct. Run before the tokeniser fix, so redo it.
- **Edit risk:** all 162 applicable edits caught, 0 false alarms from structure checks on 54 clean files. AgamiAI clean files score "medium" only because their arithmetic is broken.
- **Efficiency (multilingual set):** upload 67 rows/s, classification 430 rows/s, about 2.3 s per statement end to end, correction with full recompute 0.78 s on a 323-row case, peak Python heap 3.4 MB.

---

## 7. Decisions made, and why

| Decision | Why |
|---|---|
| Deterministic core, LLM only optional and outside scoring | Credit decisions need reproducible, defensible numbers; LLM output is nondeterministic and can expose data |
| Medallion layers in DuckDB, not Spark | Thousands of rows per case; layers give lineage and immutability cheaply |
| Weighted log-odds fusion instead of an OR cascade | Agreeing signals raise confidence, conflicts become visible, per-signal contributions explain the result |
| Hard facts as gates, not averaged | A confirmed own-account pair must never be outvoted by a keyword |
| Jev (TypeSafe's calibrated classification model) behind an interface, off by default | Early access, unknown API; calibrated probabilities fit our thresholds; fusion works without it |
| Approval tiers (HITL): analyst for labels affecting income, senior for new categories, rules, weights and global memory | A wrong global approval spreads; customer memory first |
| Keep LLMs out of the multilingual path; prefer word lists, transliteration and a small local multilingual model (MuRIL / LaBSE / multilingual-e5); optionally a local open-weight LLM for leftovers, or an LLM as an offline teacher on public data | Mentor raised data exposure; most errors are missing vocabulary, not reasoning |
| Interpretation of mentor's "editing confidence score" = edit-risk score for the PDF | Best fit to the brief's "suspicious inconsistencies" and to competitor CART's tamper detection; mentor could not be asked |
| Median for income; recent 3-month average if income fell 15%+; conservative = 25th percentile; provisional shown separately | Brief asks for sustainable, not peak, income; never mix unconfirmed credits into the main figure |
| Competitor CART (novelpatterns.ai) reviewed from public pages only | Closed SaaS; "reverse-engineer-anything" tools decompile binaries and do not apply |

---

## 8. Bugs found by testing (all fixed)

- **Tokeniser erased Indic scripts** (kept only A–Z0–9), so different Tamil/Gujarati narrations shared a vault token and were shown and classified as each other. Now Unicode-aware; narrations hashed exactly. Guarded by `test_tokens.py`. **Earlier Hindi/Gujarati results were affected.**
- PDF reading was 0% on AgamiAI: diagonal watermark letters leaked into cells (fixed by dropping rotated characters), `Rs.` prefixes, date+time cells, "Posted Date" headers, header labels without colons.
- Wrapped cells split long numbers with spaces (`APR2 6`); now joined without a space between digits or next to `/`.
- Reversals only paired refunds of debits; now both directions (reversed credits too), plus a reversal keyword rule.
- Recurrence wrongly added EMI/rent evidence to every fixed monthly debit (SIPs, insurance); now only strengthens existing obligation evidence.
- False "salary not received" when one month's salary was worded differently; single months now merge into a series, and any salary credit in a month prevents the flag.
- Client payments left unclassified; business-income keywords added; recurrence no longer pushes business receipts toward salary.
- Income showed ₹0 when likely receipts were in review; provisional income now shown.
- A scanned PDF created a phantom "unidentified" account; accounts are created only from files that yield rows.
- Similarity memory matched on rail words (`IMPS/P2A`), letting one correction pull unrelated payments; rail words stripped.
- `datagen/generate.py` deleted `sample_data/tampered`; it now only replaces its own folders.

---

## 9. Backlog, in priority order

1. **Multilingual layer** (biggest accuracy gap): word lists for Hindi/Gujarati/Tamil/Hinglish (salary वेतन/પગાર/சம்பளம்/pagar, rent किराया/ભાડું/வாடகை, sales बिक्री/વેચાણ/விற்பனை, cash नकद/રોકડ/ரொக்க, interest ब्याज/વ્યાજ/வட்டி…), transliteration (e.g. `indic-transliteration`), a local multilingual embedding model in the semantic-memory slot, and **send unreadable-script debits to review instead of defaulting to General spending**. Tune on `multilingual_v1` dev, report on test.
2. **PII masking for Indic names:** other people's names in Devanagari/Gujarati/Tamil are not masked. Must be fixed before any external model is enabled.
3. Re-run the VLM evaluation after the tokeniser fix; check the AgamiAI `hf_eval_v2.json` results.
4. Remaining narration types: `UPI/CR/…/SENT-TRANSFER FROM` person-to-person credits; dividends in the holder's own name are labelled internal transfers; `FEES` in "school fees" triggers bank charges.
5. Spending categories beyond Food & dining (Shopping, Travel) if the judges expect them.
6. Real HDFC/ICICI/SBI PDF layouts (need sample statements with personal details removed).
7. OCR for scanned PDFs (Tesseract with hin+guj+tam, or a vision model); the VLM dataset is a ready benchmark.
8. Speed: batch the per-row vault writes during upload (upload is the slowest stage).
9. Learned fusion weights (logistic regression on dev labels + corrections) and a calibration check.
10. Improvement loop from the architecture: cluster unclassified items, propose categories, impact preview, senior approval, promotion to global memory.
11. A re-run endpoint so changed rules apply to existing cases without a DB reset.

---

## 10. Gotchas

- Changing rules without bumping `RULES_VERSION` silently reuses old classifications.
- `GET /api/cases/{id}/analysis` returns the stored snapshot; it does not recompute.
- The edit-risk flag on AgamiAI files comes from their broken arithmetic, not file edits; look at `structure_score`.
- Recharts bars animate in for about a second; screenshots taken immediately look empty.
- `pypdf` is needed only for `eval_tamper.py`. `huggingface_hub[cli]` (`hf`) only for downloading AgamiAI.
- During setup, pip upgraded `attrs` and changed `httpx` in the user site-packages, which conflicts with unrelated packages on the original dev machine (`fireworks-ai`, `langgraph-sdk`). Use a venv.
- Sample data, datasets and keys are synthetic or dev-only. `data/dev_keys.json` is generated locally and git-ignored; production keys belong in a KMS.
