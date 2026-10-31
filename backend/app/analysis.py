"""Silver -> gold orchestration and content-addressed snapshots.

A snapshot's id is derived from a hash of everything it was computed from. Recomputing with identical
inputs returns the existing snapshot, so a new snapshot exists only when something actually changed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .classify import engine
from .db import jdump, q, q1, tx
from .flags import rules as flag_rules
from .metrics import effective
from .metrics.engine import compute


def _context(case_id: str) -> dict:
    return {
        "accounts": q("SELECT account_id, acct_masked, bank_name, holder_masked, account_type FROM silver.accounts WHERE case_id = ?", [case_id]),
        "statements": q("""SELECT s.*, a.acct_masked, a.bank_name FROM silver.statements s JOIN silver.accounts a USING (account_id)
                           WHERE s.case_id = ? ORDER BY a.bank_name, s.period_start""", [case_id]),
        "coverage": q("SELECT * FROM silver.coverage WHERE case_id = ? ORDER BY account_id, month", [case_id]),
        "cross_checks": q("SELECT * FROM silver.cross_checks WHERE case_id = ?", [case_id]),
        "patterns": [dict(p, counterparties=json.loads(p["counterparties"]), months=json.loads(p["months"]),
                          missed_months=json.loads(p["missed_months"]), txn_ids=json.loads(p["txn_ids"]))
                     for p in q("SELECT * FROM knowledge.periodic_patterns WHERE case_id = ?", [case_id])],
        "files": q("SELECT file_id, filename, status, reason, kind FROM bronze.files WHERE case_id = ?", [case_id]),
        "bad_pages": q("""SELECT p.*, f.filename FROM bronze.pages p JOIN bronze.files f USING (file_id)
                          WHERE f.case_id = ? AND p.status IN ('needs_ocr', 'failed', 'partial')""", [case_id]),
        "duplicate_uploads": q("SELECT filename FROM bronze.upload_events WHERE case_id = ? AND duplicate", [case_id]),
        "edit_checks": [dict(d, signals=json.loads(d["signals"])) for d in q(
            """SELECT d.*, f.filename FROM silver.document_checks d JOIN bronze.files f USING (file_id)
               WHERE d.case_id = ? ORDER BY d.score DESC, f.filename""", [case_id])],
    }


def run(case_id: str, trigger: str) -> dict:
    case = q1("SELECT * FROM silver.cases WHERE case_id = ?", [case_id])
    run_id = engine.run(case_id, trigger)
    txns = effective.transactions(case_id)
    ctx = _context(case_id)
    versions = json.loads(q1("SELECT versions FROM silver.classification_runs WHERE run_id = ?", [run_id])["versions"]) if run_id else {}
    basis = jdump({"txns": [[t["txn_id"], t["category"], t["status"]] for t in txns], "coverage": ctx["coverage"],
                   "statements": [[s["statement_id"], s["recon_status"]] for s in ctx["statements"]],
                   "files": ctx["files"], "edit": [[d["file_id"], d["score"]] for d in ctx["edit_checks"]],
                   "versions": versions, "application_date": case["application_date"]})
    input_hash = hashlib.sha256(basis.encode()).hexdigest()
    existing = q1("SELECT * FROM gold.snapshots WHERE case_id = ? AND input_hash = ?", [case_id, input_hash])
    if existing:
        return json.loads(existing["payload"])
    gold = compute(case, txns, ctx["coverage"], ctx["statements"], ctx["patterns"]) if txns else {
        "months": [], "coverage": {}, "monthly": [], "metrics": {}, "regular_outflows": [], "balance_series": [],
        "account_balance_series": {}, "profile": case["profile"]}
    flags = flag_rules.evaluate(case, txns, gold, ctx) if txns else flag_rules.evaluate(case, [], {"metrics": {"estimated_income": {"monthly": []}}, "monthly": []}, ctx)
    last = q1("SELECT seq FROM gold.snapshots WHERE case_id = ? ORDER BY seq DESC LIMIT 1", [case_id])
    seq = (last["seq"] + 1) if last else 1
    snapshot_id = f"snap_{input_hash[:12]}"
    status_counts: dict[str, int] = {}
    for t in txns:
        status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1
    payload = {
        "snapshot_id": snapshot_id, "seq": seq, "case_id": case_id, "trigger": trigger, "run_id": run_id, "versions": versions,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"), **gold, "flags": flags,
        "accounts": ctx["accounts"], "statements": ctx["statements"], "cross_checks": ctx["cross_checks"], "patterns": ctx["patterns"],
        "edit_checks": ctx["edit_checks"],
        "status_counts": status_counts, "n_transactions": len(txns),
        "categories": {t["txn_id"]: [t["category"], t["status"]] for t in txns},
    }
    with tx() as c:
        c.execute("INSERT INTO gold.snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                  [snapshot_id, case_id, input_hash, trigger, datetime.utcnow(), seq, jdump(payload)])
    return json.loads(jdump(payload))


def latest(case_id: str) -> dict | None:
    s = q1("SELECT payload FROM gold.snapshots WHERE case_id = ? ORDER BY seq DESC LIMIT 1", [case_id])
    return json.loads(s["payload"]) if s else None


def diff(a: dict, b: dict) -> dict:
    """What changed between two snapshots: metric values and transaction categories."""
    metrics = []
    for k, mb in b.get("metrics", {}).items():
        ma = a.get("metrics", {}).get(k, {})
        if ma.get("value") != mb.get("value"):
            metrics.append({"key": k, "label": mb["label"], "unit": mb["unit"], "before": ma.get("value"), "after": mb.get("value"),
                            "method_before": ma.get("method"), "method_after": mb.get("method")})
    changed = []
    for tid, (cat, st) in b.get("categories", {}).items():
        before = a.get("categories", {}).get(tid)
        if before and (before[0] != cat or before[1] != st):
            changed.append({"txn_id": tid, "before": before, "after": [cat, st]})
    fa = {f["code"] + f["title"] for f in a.get("flags", [])}
    fb = {f["code"] + f["title"] for f in b.get("flags", [])}
    return {"from": a.get("snapshot_id"), "to": b.get("snapshot_id"), "metrics": metrics, "transactions": changed,
            "flags_added": [f for f in b.get("flags", []) if f["code"] + f["title"] not in fa],
            "flags_removed": [f for f in a.get("flags", []) if f["code"] + f["title"] not in fb]}
