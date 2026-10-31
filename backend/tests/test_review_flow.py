"""Corrections, idempotency, reveal logging, RBAC and audit chain."""
import os, sys, tempfile
os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_test_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    c.post("/api/demo/load").raise_for_status()
    sme = [x for x in c.get("/api/cases").json() if "Kavya" in x["name"]][0]["case_id"]
    txns = c.get(f"/api/cases/{sme}/transactions").json()
    school = next(t for t in txns if "VIDYA MANDIR" in t["description"])
    assert school["category"] == "BANK_CHARGES"
    snaps_before = len(c.get(f"/api/cases/{sme}/snapshots").json())

    # correction with an idempotency key
    body = {"category": "GENERAL_EXPENSE", "reason": "School term fees, personal spending", "event_id": "evt-test-1"}
    r1 = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json=body, headers={"Idempotency-Key": "k1"}).json()
    assert r1["noop"] is False, r1
    print("diff metrics:", [(m["key"], m["before"], m["after"]) for m in r1["diff"]["metrics"]])
    # retry: same key and body returns the stored response, no new event or snapshot
    r2 = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json=body, headers={"Idempotency-Key": "k1"}).json()
    assert r2 == r1
    # same key, different body -> 409
    r3 = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json={**body, "category": "INSURANCE"}, headers={"Idempotency-Key": "k1"})
    assert r3.status_code == 409, r3.status_code
    # same event id without key -> no-op
    r4 = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json=body).json()
    assert r4["noop"] is True
    snaps_after = len(c.get(f"/api/cases/{sme}/snapshots").json())
    assert snaps_after == snaps_before + 1, (snaps_before, snaps_after)

    d = c.get(f"/api/cases/{sme}/transactions/{school['txn_id']}").json()
    assert d["txn"]["category"] == "GENERAL_EXPENSE" and d["txn"]["status"] == "confirmed"
    assert d["txn"]["model_category"] == "BANK_CHARGES", "original classification must be preserved"
    print("history:", [(h["category"], h["status"]) for h in d["history"]], "| overrides:", len(d["overrides"]))

    # wrong direction is refused
    r5 = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json={"category": "SALARY", "reason": "test it"})
    assert r5.status_code == 422, r5.text

    # RBAC: auditor cannot override or reveal; analyst reveal needs a reason and is logged
    aud = {"X-Role": "auditor", "X-User": "audit.demo"}
    assert c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/override", json={**body, "event_id": "x"}, headers=aud).status_code == 403
    assert c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/reveal", json={"reason": ""}).status_code == 422
    rv = c.post(f"/api/cases/{sme}/transactions/{school['txn_id']}/reveal", json={"reason": "verify school name with applicant"}).json()
    print("revealed:", rv["description"])
    assert c.get("/api/audit").status_code == 403
    a = c.get("/api/audit", headers=aud).json()
    print("audit:", a["verification"], [e["action"] for e in a["entries"][:4]])
    assert a["verification"]["ok"]

    # re-loading demo data is idempotent: no new transactions
    n1 = len(c.get(f"/api/cases/{sme}/transactions").json())
    c.post("/api/demo/load")
    assert len(c.get(f"/api/cases/{sme}/transactions").json()) == n1
    # unsupported upload is rejected with a reason
    bad = c.post(f"/api/cases/{sme}/files", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert bad.status_code == 422, bad.text
    print("ALL CHECKS PASSED")
