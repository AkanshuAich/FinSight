# FinSight

Bank statement and financial analysis for credit review. FinSight extracts transactions from PDF, CSV, Excel and JSON statements, reconciles every row, removes own-account transfers, refunds and duplicates, classifies each transaction with visible evidence, and calculates income, obligations and cash-flow indicators. Every figure lists the transactions it includes and excludes, and an analyst correction recalculates everything that depends on it.

The design principle: **rules and arithmetic decide; models only add evidence; analysts approve changes to what the system remembers.**

## Run it

Requires Python 3.11+ and Node 18+.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
python datagen/generate.py      # writes sample_data/ with ground-truth labels
```

```bash
python -m uvicorn app.main:app --app-dir backend --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 and choose **Load sample cases**. For a single-process deployment, run `npm run build` in `frontend/`; the API then serves the built UI at http://localhost:8000.

Tests (each run uses a throwaway database):

```bash
python backend/tests/test_review_flow.py
python backend/tests/smoke.py
```

## Sample data

`datagen/generate.py` creates two fictional applicants covering every scenario in the brief:

| Case | Files | Scenarios |
|---|---|---|
| Rohan Malhotra (salaried) | Two PDF layouts (Northwind, Meridian), one duplicate upload, a corrupted PDF, a scanned PDF | Employer renamed mid-period, monthly ₹50,000 own-account transfer, EMI, rent, refund and failed-UPI reversal, overlapping statements, missing month, misprinted balance, large cash deposit, round-figure credit before application |
| Kavya Iyer / Sri Lakshmi Traders (SME) | CSV and XLSX current account (overlapping), JSON savings account | Irregular, declining business receipts, loan disbursal, EMI bounce with charges, cash deposits, low balances, negative net months |

## Architecture

```
upload ─► bronze (encrypted file, pages, raw rows, quarantine)
       ─► silver (accounts, statements, transactions, sources, classifications, override events, coverage)
       ─► gold   (content-addressed snapshots: metrics with lineage, flags)
knowledge store (versioned): rules, semantic examples, periodic patterns, entity lists
```

| Area | Where | Notes |
|---|---|---|
| Extraction | `backend/app/ingest/` | Column roles inferred from headers, so new layouts work without templates. Every page gets a status; unreadable rows are quarantined with a reason. Password-protected PDFs prompt for a password that is never stored. |
| Reconciliation | `backend/app/validate/reconcile.py` | Row chain, statement totals and continuity between statements. A single wrong printed balance is reported as a misprint, not two breaks. |
| Dedup and coverage | `ingest/service.py`, `dedup/coverage.py` | Transaction IDs are a hash of account, date, amounts, narration and balance, so overlapping statements add a source rather than a transaction. Missing months are flagged and never treated as zero. |
| Classification | `backend/app/classify/engine.py` | Tier 1 hard gates (transfer pairs across own accounts, reversal pairs, bounces). Tier 2 weighted log-odds fusion of keyword rules, entity lists, periodic memory, semantic memory and optional Jev answers. Tier 3 policy: auto at P ≥ 0.90 with margin ≥ 0.30, review from 0.60, otherwise unclassified. |
| Periodic memory | `classify/periodic.py` | Monthly series by counterparty, merged across renames when amount and day of month match. Drives salary detection, obligations and missed-payment flags. |
| Metrics | `backend/app/metrics/engine.py` | Income (median; recent 3-month average if income fell 15% or more), obligations, FOIR, net cash flow, balances. Each returns included and excluded transactions with reasons. |
| Corrections | `backend/app/review/overrides.py` | Append-only events. The original classification is preserved. A correction becomes a case-level memory example and triggers a full recompute with a before/after diff. |
| Security | `backend/app/security/` | HMAC tokenisation, Fernet-encrypted vault and files, masked narrations, logged reveal with reason, egress gateway that blocks residual PII, hash-chained audit log, role checks, log scrubbing. |
| Idempotency | throughout | File hash, deterministic transaction IDs, stage replacement in one DB transaction, `Idempotency-Key` on POSTs, unique event IDs, content-addressed snapshots. |

## Known limits

- OCR is not implemented: scanned pages are reported as `needs_ocr` and their content is not used.
- The Jev client is a placeholder until API access is available. It is off unless `JEV_API_URL`, `JEV_API_KEY` and `FINSIGHT_EXTERNAL_MODELS=1` are set. Fusion works without it.
- Fusion weights are hand-set (`w0`). The evaluation harness exists to compare them against learned weights later.
- Accuracy figures come from synthetic data written alongside the rules, so they overstate real-world performance.
- Roles come from request headers for the demo. Production would use SSO. Dev encryption keys are generated into `data/dev_keys.json`; production would use a KMS.
