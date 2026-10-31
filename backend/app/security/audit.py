"""Append-only, tamper-evident audit log: each entry carries the hash of the previous one."""
from __future__ import annotations

import hashlib
from datetime import datetime

from ..db import connect, jdump, q, _lock


def _digest(prev_hash: str, seq: int, ts: str, actor: str, role: str, action: str, case_id: str, target: str, details: str) -> str:
    return hashlib.sha256("|".join([prev_hash, str(seq), ts, actor, role, action, case_id or "", target or "", details]).encode()).hexdigest()


def record(action: str, *, actor: str = "system", role: str = "system", case_id: str | None = None,
           target: str | None = None, details: dict | None = None, con=None) -> None:
    con = con or connect()
    with _lock:
        last = con.execute("SELECT seq, hash FROM review.audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        seq = (last[0] + 1) if last else 1
        prev = last[1] if last else "GENESIS"
        ts = datetime.utcnow().isoformat(timespec="microseconds")
        det = jdump(details or {})
        h = _digest(prev, seq, ts, actor, role, action, case_id or "", target or "", det)
        con.execute("INSERT INTO review.audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [seq, ts, actor, role, action, case_id, target, det, prev, h])


def verify() -> dict:
    rows = q("SELECT * FROM review.audit_log ORDER BY seq")
    prev = "GENESIS"
    for r in rows:
        ts = r["ts"].isoformat(timespec="microseconds") if hasattr(r["ts"], "isoformat") else str(r["ts"])
        expect = _digest(prev, r["seq"], ts, r["actor"], r["role"], r["action"], r["case_id"] or "", r["target"] or "", r["details"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return {"ok": False, "entries": len(rows), "broken_at": r["seq"]}
        prev = r["hash"]
    return {"ok": True, "entries": len(rows), "head": prev}
