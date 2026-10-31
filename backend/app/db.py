"""DuckDB storage with one schema per medallion layer plus knowledge, review and security.

Lower layers are never overwritten: bronze is append-only, gold is always rebuilt from silver.
A single connection is shared behind a lock; a few thousand rows per case need nothing more.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager

import duckdb

from .config import DATA_DIR, DB_PATH, FILES_DIR

_lock = threading.RLock()
_con: duckdb.DuckDBPyConnection | None = None

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS review;
CREATE SCHEMA IF NOT EXISTS security;

CREATE TABLE IF NOT EXISTS silver.cases (
  case_id VARCHAR PRIMARY KEY, name VARCHAR, application_date DATE, profile VARCHAR,
  is_demo BOOLEAN DEFAULT FALSE, demo_key VARCHAR, created_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS bronze.files (
  file_id VARCHAR PRIMARY KEY, case_id VARCHAR, sha256 VARCHAR, filename VARCHAR, kind VARCHAR,
  size_bytes BIGINT, status VARCHAR, reason VARCHAR, uploaded_at TIMESTAMP, processed_at TIMESTAMP,
  UNIQUE (case_id, sha256));
CREATE TABLE IF NOT EXISTS bronze.upload_events (
  event_id VARCHAR PRIMARY KEY, case_id VARCHAR, file_id VARCHAR, filename VARCHAR,
  duplicate BOOLEAN, uploaded_at TIMESTAMP, actor VARCHAR);
CREATE TABLE IF NOT EXISTS bronze.pages (
  file_id VARCHAR, page_no INTEGER, status VARCHAR, reason VARCHAR, n_rows INTEGER, method VARCHAR,
  PRIMARY KEY (file_id, page_no));
CREATE TABLE IF NOT EXISTS bronze.raw_rows (
  file_id VARCHAR, page_no INTEGER, row_no INTEGER, cells_enc BLOB, PRIMARY KEY (file_id, page_no, row_no));
CREATE TABLE IF NOT EXISTS bronze.quarantine (
  q_id VARCHAR PRIMARY KEY, case_id VARCHAR, file_id VARCHAR, page_no INTEGER, row_no INTEGER,
  kind VARCHAR, reason VARCHAR, detail VARCHAR);

CREATE TABLE IF NOT EXISTS silver.accounts (
  account_id VARCHAR PRIMARY KEY, case_id VARCHAR, acct_token VARCHAR, acct_masked VARCHAR, bank_name VARCHAR,
  holder_token VARCHAR, holder_masked VARCHAR, account_type VARCHAR);
CREATE TABLE IF NOT EXISTS silver.statements (
  statement_id VARCHAR PRIMARY KEY, case_id VARCHAR, file_id VARCHAR, account_id VARCHAR, layout VARCHAR,
  period_start DATE, period_end DATE, opening_paise BIGINT, opening_source VARCHAR, closing_stated BIGINT,
  computed_closing BIGINT, total_debits BIGINT, total_credits BIGINT, recon_status VARCHAR, recon_diff BIGINT,
  n_rows INTEGER, n_breaks INTEGER);
CREATE TABLE IF NOT EXISTS silver.transactions (
  txn_id VARCHAR PRIMARY KEY, case_id VARCHAR, account_id VARCHAR, txn_date DATE, description VARCHAR,
  description_norm VARCHAR, desc_token VARCHAR, debit BIGINT, credit BIGINT, balance BIGINT, channel VARCHAR,
  counterparty VARCHAR, ref_tokens VARCHAR, recon_status VARCHAR, recon_note VARCHAR, first_statement_id VARCHAR,
  seq INTEGER);
CREATE TABLE IF NOT EXISTS silver.txn_sources (
  txn_id VARCHAR, statement_id VARCHAR, file_id VARCHAR, page_no INTEGER, row_no INTEGER,
  PRIMARY KEY (txn_id, statement_id, page_no, row_no));
CREATE TABLE IF NOT EXISTS silver.txn_links (
  case_id VARCHAR, txn_a VARCHAR, txn_b VARCHAR, kind VARCHAR, reason VARCHAR, run_id VARCHAR);
CREATE TABLE IF NOT EXISTS silver.classification_runs (
  run_id VARCHAR PRIMARY KEY, case_id VARCHAR, input_hash VARCHAR, versions VARCHAR, created_at TIMESTAMP, seq INTEGER);
CREATE TABLE IF NOT EXISTS silver.classifications (
  run_id VARCHAR, case_id VARCHAR, txn_id VARCHAR, category VARCHAR, status VARCHAR, tier VARCHAR, source VARCHAR,
  probability DOUBLE, margin DOUBLE, explanation VARCHAR, contributions VARCHAR, candidates VARCHAR, attributes VARCHAR,
  PRIMARY KEY (run_id, txn_id));
CREATE TABLE IF NOT EXISTS silver.overrides (
  event_id VARCHAR PRIMARY KEY, case_id VARCHAR, txn_id VARCHAR, from_category VARCHAR, to_category VARCHAR,
  reason VARCHAR, actor VARCHAR, role VARCHAR, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS silver.coverage (
  case_id VARCHAR, account_id VARCHAR, month VARCHAR, status VARCHAR, days_covered INTEGER, days_in_month INTEGER);
CREATE TABLE IF NOT EXISTS silver.document_checks (
  file_id VARCHAR PRIMARY KEY, case_id VARCHAR, score INTEGER, structure_score INTEGER, level VARCHAR, signals VARCHAR);
CREATE TABLE IF NOT EXISTS silver.cross_checks (
  case_id VARCHAR, account_id VARCHAR, prev_statement VARCHAR, next_statement VARCHAR, kind VARCHAR,
  expected BIGINT, actual BIGINT, gap_start DATE, gap_end DATE, detail VARCHAR);

CREATE TABLE IF NOT EXISTS gold.snapshots (
  snapshot_id VARCHAR PRIMARY KEY, case_id VARCHAR, input_hash VARCHAR, trigger VARCHAR, created_at TIMESTAMP,
  seq INTEGER, payload VARCHAR, UNIQUE (case_id, input_hash));

CREATE TABLE IF NOT EXISTS knowledge.semantic_examples (
  example_id VARCHAR PRIMARY KEY, scope VARCHAR, case_id VARCHAR, text_norm VARCHAR, category VARCHAR,
  source VARCHAR, approved_by VARCHAR, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS knowledge.periodic_patterns (
  case_id VARCHAR, pattern_id VARCHAR, account_id VARCHAR, direction VARCHAR, label VARCHAR, counterparties VARCHAR,
  median_amount BIGINT, amount_cv DOUBLE, typical_day INTEGER, months VARCHAR, missed_months VARCHAR,
  expected_next DATE, txn_ids VARCHAR, run_id VARCHAR);

CREATE TABLE IF NOT EXISTS review.audit_log (
  seq BIGINT PRIMARY KEY, ts TIMESTAMP, actor VARCHAR, role VARCHAR, action VARCHAR, case_id VARCHAR,
  target VARCHAR, details VARCHAR, prev_hash VARCHAR, hash VARCHAR);
CREATE TABLE IF NOT EXISTS review.idempotency_keys (
  key VARCHAR PRIMARY KEY, request_hash VARCHAR, status_code INTEGER, response VARCHAR, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS review.stage_runs (
  file_hash VARCHAR, case_id VARCHAR, stage VARCHAR, pipeline_version VARCHAR, ts TIMESTAMP,
  PRIMARY KEY (file_hash, case_id, stage, pipeline_version));

CREATE TABLE IF NOT EXISTS security.pii_vault (
  token VARCHAR PRIMARY KEY, kind VARCHAR, value_enc BLOB, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS security.egress_log (
  egress_id VARCHAR PRIMARY KEY, ts TIMESTAMP, target VARCHAR, payload_masked VARCHAR, blocked BOOLEAN, reason VARCHAR);
"""


def connect() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            FILES_DIR.mkdir(parents=True, exist_ok=True)
            _con = duckdb.connect(str(DB_PATH))
            _con.execute(SCHEMA)
        return _con


@contextmanager
def tx():
    """One database transaction under the process lock. Stage outputs are replaced atomically."""
    con = connect()
    with _lock:
        con.execute("BEGIN TRANSACTION")
        try:
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def q(sql: str, params: list | tuple = ()) -> list[dict]:
    con = connect()
    with _lock:
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def q1(sql: str, params: list | tuple = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def jdump(obj) -> str:
    return json.dumps(obj, default=str, sort_keys=True)
