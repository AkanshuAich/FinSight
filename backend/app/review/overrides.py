"""Analyst corrections as events. The original classification is never modified.

A correction (1) appends an override event, (2) writes the narration to customer-level semantic memory,
(3) recomputes classification and gold, and (4) returns the before/after diff. A retried event_id, or
setting a confirmed category to its current value, is a no-op.
"""
from __future__ import annotations

from datetime import datetime

from .. import analysis
from ..classify import semantic
from ..classify.categories import CATEGORIES
from ..db import q1, tx
from ..metrics import effective
from ..security import audit


class OverrideError(Exception):
    pass


def apply(case_id: str, txn_id: str, to_category: str, reason: str, event_id: str, actor: str, role: str) -> dict:
    if to_category not in CATEGORIES or to_category == "UNCLASSIFIED":
        raise OverrideError(f"unknown category {to_category!r}")
    if not reason or len(reason.strip()) < 3:
        raise OverrideError("a reason is required for every correction")
    if q1("SELECT 1 FROM silver.overrides WHERE event_id = ?", [event_id]):
        return {"noop": True, "reason": "this correction was already applied", "snapshot": analysis.latest(case_id)}
    txn = next((t for t in effective.transactions(case_id) if t["txn_id"] == txn_id), None)
    if not txn:
        raise OverrideError("transaction not found in this case")
    direction = "C" if txn["credit"] else "D"
    if CATEGORIES[to_category]["dir"] not in (direction, "B"):
        raise OverrideError(f"{CATEGORIES[to_category]['label']} does not apply to a {'credit' if direction == 'C' else 'debit'}")
    if txn["category"] == to_category and txn["status"] == "confirmed":
        return {"noop": True, "reason": "category already confirmed", "snapshot": analysis.latest(case_id)}
    before = analysis.latest(case_id) or analysis.run(case_id, "pre-override")
    with tx() as c:
        c.execute("INSERT INTO silver.overrides VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  [event_id, case_id, txn_id, txn["category"], to_category, reason.strip(), actor, role, datetime.utcnow()])
        semantic.add_case_example(c, case_id, txn["description_norm"], to_category, actor)
    audit.record("classification.override", actor=actor, role=role, case_id=case_id, target=txn_id,
                 details={"event_id": event_id, "from": txn["category"], "from_status": txn["status"], "to": to_category,
                          "reason": reason.strip(), "memory": "case"})
    after = analysis.run(case_id, f"override:{txn_id}")
    d = analysis.diff(before, after)
    d["transactions"] = [x for x in d["transactions"] if x["txn_id"] != txn_id]
    return {"noop": False, "diff": d, "snapshot": after}
