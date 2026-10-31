"""Accuracy against the synthetic ground truth: per-category precision/recall, auto-decision accuracy,
reconciliation pass rate. Matching uses account number, date, amounts and narration from the vault."""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from .classify.categories import CATEGORIES
from .config import SAMPLE_DIR
from .db import connect, q
from .metrics import effective
from .security.crypto import vault_get


def evaluate(case_id: str) -> dict:
    gt_path = SAMPLE_DIR / "ground_truth.json"
    if not gt_path.exists():
        return {"available": False, "reason": "no ground truth file"}
    truth = {}
    for r in json.loads(gt_path.read_text()):
        truth[(r["account_number"], r["date"], r["debit"], r["credit"], r["description"])] = r["category"]
    con = connect()
    acct_clear = {a["account_id"]: vault_get(con, a["acct_token"]) for a in q("SELECT account_id, acct_token FROM silver.accounts WHERE case_id = ?", [case_id])}
    tokens = {t["txn_id"]: t["desc_token"] for t in q("SELECT txn_id, desc_token FROM silver.transactions WHERE case_id = ?", [case_id])}
    rows = []
    for t in effective.transactions(case_id):
        key = (acct_clear.get(t["account_id"]), t["txn_date"].isoformat(), t["debit"], t["credit"], vault_get(con, tokens[t["txn_id"]]))
        if key in truth:
            rows.append((t, truth[key]))
    if not rows:
        return {"available": False, "reason": "this case is not a sample case with ground truth"}
    tp, fp, fn = Counter(), Counter(), Counter()
    errors = []
    for t, gold in rows:
        pred = t["category"]
        if pred == gold:
            tp[gold] += 1
        else:
            fp[pred] += 1
            fn[gold] += 1
            errors.append({"txn_id": t["txn_id"], "description": t["description"], "expected": gold, "predicted": pred, "status": t["status"],
                           "amount": t["amount"], "date": t["txn_date"].isoformat()})
    per_cat = []
    for cat in sorted(set(tp) | set(fp) | set(fn)):
        p = tp[cat] / (tp[cat] + fp[cat]) if tp[cat] + fp[cat] else None
        r = tp[cat] / (tp[cat] + fn[cat]) if tp[cat] + fn[cat] else None
        per_cat.append({"category": cat, "label": CATEGORIES.get(cat, {"label": cat})["label"], "support": tp[cat] + fn[cat],
                        "precision": round(p, 3) if p is not None else None, "recall": round(r, 3) if r is not None else None})
    auto = [(t, g) for t, g in rows if t["status"] in ("auto", "confirmed")]
    stmts = q("SELECT recon_status FROM silver.statements WHERE case_id = ?", [case_id])
    by_status = defaultdict(int)
    for t, _ in rows:
        by_status[t["status"]] += 1
    return {
        "available": True, "matched": len(rows), "accuracy": round(sum(tp.values()) / len(rows), 4),
        "auto_share": round(len(auto) / len(rows), 4),
        "auto_accuracy": round(sum(1 for t, g in auto if t["category"] == g) / len(auto), 4) if auto else None,
        "by_status": dict(by_status), "per_category": per_cat, "errors": errors[:60],
        "reconciliation_pass_rate": round(sum(1 for s in stmts if s["recon_status"] == "reconciled") / len(stmts), 3) if stmts else None,
    }
