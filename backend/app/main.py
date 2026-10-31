"""FinSight API."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analysis, config, evaluation
from .classify import semantic
from .classify.categories import CATEGORIES
from .db import connect, jdump, q, q1
from .ingest import service as ingest
from .metrics import effective
from .review import overrides
from .security import audit, log_scrub
from .security.crypto import stable_id, vault_get
from .security.rbac import User, current_user, require

log_scrub.install()
log = logging.getLogger("finsight")
app = FastAPI(title="FinSight", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    connect()
    semantic.seed()


def _json(obj) -> JSONResponse:
    return JSONResponse(json.loads(jdump(obj)))


def _idempotent(key: str | None, request: dict, fn):
    """Same Idempotency-Key + same request returns the stored response; same key + different request is a 409."""
    if not key:
        return fn()
    req_hash = hashlib.sha256(jdump(request).encode()).hexdigest()
    row = q1("SELECT * FROM review.idempotency_keys WHERE key = ?", [key])
    if row:
        if row["request_hash"] != req_hash:
            raise HTTPException(409, "Idempotency-Key was already used with a different request")
        return json.loads(row["response"])
    result = json.loads(jdump(fn()))
    connect().execute("INSERT OR IGNORE INTO review.idempotency_keys VALUES (?, ?, ?, ?, ?)", [key, req_hash, 200, jdump(result), datetime.utcnow()])
    return result


def _case(case_id: str) -> dict:
    c = q1("SELECT * FROM silver.cases WHERE case_id = ?", [case_id])
    if not c:
        raise HTTPException(404, "case not found")
    return c


# ------------------------------------------------------------------ meta

@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


@app.get("/api/meta")
def meta():
    from .classify import jev_client
    from .security import egress
    return {"categories": CATEGORIES, "roles": ["analyst", "senior", "auditor", "admin"],
            "versions": {"pipeline": config.PIPELINE_VERSION, "rules": config.RULES_VERSION, "weights": config.WEIGHTS_VERSION,
                         "question_bank": config.QUESTION_BANK_VERSION},
            "policy": {"auto_min_p": config.AUTO_MIN_P, "auto_min_margin": config.AUTO_MIN_MARGIN, "review_min_p": config.REVIEW_MIN_P},
            "jev_enabled": jev_client.available(), "external_models_allowed": egress.external_allowed()}


# ------------------------------------------------------------------ cases

def _case_summary(c: dict) -> dict:
    snap = analysis.latest(c["case_id"])
    out = dict(c)
    if snap:
        inc = snap.get("metrics", {}).get("estimated_income", {})
        out.update({"n_transactions": snap["n_transactions"], "income": inc.get("value"), "profile_detected": snap.get("profile"),
                    "flags_high": sum(1 for f in snap["flags"] if f["severity"] == "high"),
                    "n_accounts": len(snap["accounts"]), "months": snap.get("months", [])})
    out["n_files"] = q1("SELECT count(*) AS n FROM bronze.files WHERE case_id = ?", [c["case_id"]])["n"]
    return out


@app.get("/api/cases")
def list_cases():
    return _json([_case_summary(c) for c in q("SELECT * FROM silver.cases ORDER BY created_at")])


@app.post("/api/cases")
def create_case(body: dict = Body(...), user: User = Depends(current_user), idempotency_key: str | None = Header(default=None)):
    require(user, "create_case")

    def do():
        case_id = "c_" + uuid.uuid4().hex[:12]
        app_date = date.fromisoformat(body.get("application_date") or date.today().isoformat())
        connect().execute("INSERT INTO silver.cases VALUES (?, ?, ?, ?, FALSE, NULL, ?)",
                          [case_id, (body.get("name") or "New applicant").strip()[:80], app_date, body.get("profile") or "UNKNOWN", datetime.utcnow()])
        audit.record("case.create", actor=user.name, role=user.role, case_id=case_id, target=case_id)
        return _case_summary(_case(case_id))
    return _json(_idempotent(idempotency_key, {"op": "create_case", **body}, do))


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return _json(_case_summary(_case(case_id)))


# ------------------------------------------------------------------ files

@app.post("/api/cases/{case_id}/files")
async def upload_file(case_id: str, file: UploadFile = File(...), password: str | None = Form(default=None), user: User = Depends(current_user)):
    require(user, "upload")
    _case(case_id)
    data = await file.read()
    try:
        rep = ingest.upload(case_id, file.filename or "upload", data, actor=user.name, role=user.role, password=password)
    except ingest.UploadRejected as e:
        audit.record("file.rejected", actor=user.name, role=user.role, case_id=case_id, details={"filename": file.filename, "reason": str(e)})
        raise HTTPException(422, str(e))
    finally:
        del data, password
    snap = analysis.run(case_id, f"upload:{rep.get('file_id')}")
    return _json({"file": rep, "snapshot_id": snap["snapshot_id"]})


@app.get("/api/cases/{case_id}/files")
def list_files(case_id: str):
    _case(case_id)
    files = [ingest.file_report(f["file_id"]) for f in q("SELECT file_id FROM bronze.files WHERE case_id = ? ORDER BY uploaded_at", [case_id])]
    events = q("SELECT filename, duplicate, uploaded_at, actor, file_id FROM bronze.upload_events WHERE case_id = ? ORDER BY uploaded_at", [case_id])
    cross = q("SELECT * FROM silver.cross_checks WHERE case_id = ?", [case_id])
    return _json({"files": files, "upload_events": events, "cross_checks": cross})


# ------------------------------------------------------------------ analysis

@app.get("/api/cases/{case_id}/analysis")
def get_analysis(case_id: str):
    _case(case_id)
    return _json(analysis.latest(case_id) or analysis.run(case_id, "initial"))


@app.get("/api/cases/{case_id}/snapshots")
def list_snapshots(case_id: str):
    return _json(q("SELECT snapshot_id, seq, trigger, created_at FROM gold.snapshots WHERE case_id = ? ORDER BY seq DESC", [case_id]))


@app.get("/api/cases/{case_id}/diff")
def snapshot_diff(case_id: str, from_id: str, to_id: str):
    a = q1("SELECT payload FROM gold.snapshots WHERE case_id = ? AND snapshot_id = ?", [case_id, from_id])
    b = q1("SELECT payload FROM gold.snapshots WHERE case_id = ? AND snapshot_id = ?", [case_id, to_id])
    if not a or not b:
        raise HTTPException(404, "snapshot not found")
    return _json(analysis.diff(json.loads(a["payload"]), json.loads(b["payload"])))


# ------------------------------------------------------------------ transactions

def _txn_view(t: dict) -> dict:
    keep = ["txn_id", "account_id", "txn_date", "description", "debit", "credit", "balance", "channel", "counterparty", "recon_status",
            "recon_note", "acct_masked", "bank_name", "category", "status", "model_category", "model_status", "tier", "source", "probability",
            "margin", "explanation", "attributes", "override_category", "override_reason", "override_actor", "override_at", "direction", "amount"]
    out = {k: t.get(k) for k in keep}
    out["counterparty"] = "[Holder]" if out["counterparty"] == "<HOLDER>" else out["counterparty"]
    return out


@app.get("/api/cases/{case_id}/transactions")
def list_transactions(case_id: str):
    _case(case_id)
    snap = analysis.latest(case_id)
    flagged: dict[str, list[str]] = {}
    for f in (snap or {}).get("flags", []):
        if f["category"] == "review":
            continue
        for tid in f["txn_ids"]:
            flagged.setdefault(tid, []).append(f["title"])
    out = []
    for t in effective.transactions(case_id):
        v = _txn_view(t)
        v["flags"] = flagged.get(t["txn_id"], [])
        out.append(v)
    return _json(out)


@app.get("/api/cases/{case_id}/transactions/{txn_id}")
def get_transaction(case_id: str, txn_id: str):
    t = next((x for x in effective.transactions(case_id) if x["txn_id"] == txn_id), None)
    if not t:
        raise HTTPException(404, "transaction not found")
    run_id = effective.latest_run(case_id)
    cls = q1("SELECT * FROM silver.classifications WHERE run_id = ? AND txn_id = ?", [run_id, txn_id])
    history = q("""SELECT c.run_id, r.seq, r.created_at, c.category, c.status, c.probability, c.source FROM silver.classifications c
                   JOIN silver.classification_runs r USING (run_id) WHERE c.txn_id = ? ORDER BY r.seq""", [txn_id])
    compact = []
    for h in history:  # keep runs where the outcome changed
        if not compact or (compact[-1]["category"], compact[-1]["status"]) != (h["category"], h["status"]):
            compact.append(h)
    sources = q("""SELECT s.statement_id, s.file_id, s.page_no, s.row_no, f.filename, st.period_start, st.period_end
                   FROM silver.txn_sources s JOIN bronze.files f USING (file_id) JOIN silver.statements st USING (statement_id)
                   WHERE s.txn_id = ? ORDER BY f.filename""", [txn_id])
    links = q("SELECT * FROM silver.txn_links WHERE case_id = ? AND (txn_a = ? OR txn_b = ?)", [case_id, txn_id, txn_id])
    all_t = {x["txn_id"]: x for x in effective.transactions(case_id)} if links else {}
    link_view = []
    for l in links:
        other = l["txn_b"] if l["txn_a"] == txn_id else l["txn_a"]
        if other in all_t:
            link_view.append({"kind": l["kind"], "reason": l["reason"], "txn": _txn_view(all_t[other])})
    events = q("SELECT * FROM silver.overrides WHERE txn_id = ? ORDER BY created_at", [txn_id])
    patterns = [dict(p, counterparties=json.loads(p["counterparties"]), months=json.loads(p["months"]), missed_months=json.loads(p["missed_months"]))
                for p in q("SELECT * FROM knowledge.periodic_patterns WHERE case_id = ?", [case_id]) if txn_id in json.loads(p["txn_ids"])]
    return _json({"txn": _txn_view(t), "classification": {
        **(cls or {}), "contributions": json.loads(cls["contributions"]) if cls else [], "candidates": json.loads(cls["candidates"]) if cls else [],
        "attributes": json.loads(cls["attributes"]) if cls else []}, "history": compact, "sources": sources, "links": link_view,
        "overrides": events, "patterns": patterns})


@app.post("/api/cases/{case_id}/transactions/{txn_id}/override")
def override_txn(case_id: str, txn_id: str, body: dict = Body(...), user: User = Depends(current_user),
                 idempotency_key: str | None = Header(default=None)):
    require(user, "override")
    event_id = body.get("event_id") or idempotency_key or uuid.uuid4().hex

    def do():
        try:
            res = overrides.apply(case_id, txn_id, body.get("category", ""), body.get("reason", ""), event_id, user.name, user.role)
        except overrides.OverrideError as e:
            raise HTTPException(422, str(e))
        return {"noop": res["noop"], "reason": res.get("reason"), "diff": res.get("diff"), "snapshot_id": (res.get("snapshot") or {}).get("snapshot_id")}
    return _json(_idempotent(idempotency_key, {"op": "override", "case": case_id, "txn": txn_id, **body}, do))


@app.post("/api/cases/{case_id}/transactions/{txn_id}/reveal")
def reveal(case_id: str, txn_id: str, body: dict = Body(...), user: User = Depends(current_user)):
    require(user, "reveal")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "state why you need the unmasked narration (at least 5 characters)")
    row = q1("SELECT desc_token FROM silver.transactions WHERE case_id = ? AND txn_id = ?", [case_id, txn_id])
    if not row:
        raise HTTPException(404, "transaction not found")
    audit.record("pii.reveal", actor=user.name, role=user.role, case_id=case_id, target=txn_id, details={"reason": reason, "field": "narration"})
    return {"description": vault_get(connect(), row["desc_token"]), "logged": True}


# ------------------------------------------------------------------ evaluation, audit, demo

@app.get("/api/cases/{case_id}/evaluation")
def get_evaluation(case_id: str):
    _case(case_id)
    return _json(evaluation.evaluate(case_id))


@app.get("/api/audit")
def get_audit(case_id: str | None = None, user: User = Depends(current_user)):
    require(user, "view_audit")
    rows = q("SELECT * FROM review.audit_log " + ("WHERE case_id = ? " if case_id else "") + "ORDER BY seq DESC LIMIT 300",
             [case_id] if case_id else [])
    return _json({"entries": rows, "verification": audit.verify()})


@app.post("/api/demo/load")
def load_demo(user: User = Depends(current_user)):
    require(user, "upload")
    meta_path = config.SAMPLE_DIR / "cases.json"
    if not meta_path.exists():
        raise HTTPException(404, "sample data not generated; run python datagen/generate.py")
    cases_meta = json.loads(meta_path.read_text())
    created = []
    for key, m in cases_meta.items():
        case_id = stable_id("c", "demo", key)[:14]
        if not q1("SELECT 1 FROM silver.cases WHERE case_id = ?", [case_id]):
            connect().execute("INSERT INTO silver.cases VALUES (?, ?, ?, ?, TRUE, ?, ?)",
                              [case_id, m["applicant"], date.fromisoformat(m["application_date"]), m["profile"], key, datetime.utcnow()])
            audit.record("case.create", actor=user.name, role=user.role, case_id=case_id, target=case_id, details={"demo": key})
        files = sorted((config.SAMPLE_DIR / key).iterdir(), key=lambda p: (" (" in p.name, p.name))  # originals before copies
        if key == "case_salaried":
            files += sorted((config.SAMPLE_DIR / "problem_files").iterdir())
        for f in files:
            try:
                ingest.upload(case_id, f.name, f.read_bytes(), actor=user.name, role=user.role)
            except ingest.UploadRejected as e:
                log.warning("demo file rejected: %s", e)
        analysis.run(case_id, "demo_load")
        created.append(case_id)
    return _json({"cases": created})


_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = _dist / path
        return FileResponse(target if path and target.is_file() else _dist / "index.html")
