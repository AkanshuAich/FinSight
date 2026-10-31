import json, os, sys, tempfile
os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_dbg_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app
from app.db import q, connect
from app.security.crypto import vault_get
with TestClient(app) as c:
    c.post("/api/demo/load")
    gt = json.load(open("../sample_data/ground_truth.json"))
    keys = {(r["date"], r["debit"], r["credit"]) : r["description"] for r in gt}
    for case in c.get("/api/cases").json():
        txns = c.get(f"/api/cases/{case['case_id']}/transactions").json()
        print("==", case["name"])
        for t in txns:
            if t["status"] != "auto":
                d = c.get(f"/api/cases/{case['case_id']}/transactions/{t['txn_id']}").json()
                cands = ", ".join(f"{x['category']}:{x['p']}" for x in d["classification"]["candidates"])
                print(f"  {t['status']:12s} {t['category']:18s} {t['description'][:60]:60s} | {cands}")
    con = connect()
    rows = q("SELECT txn_date, debit, credit, desc_token FROM silver.transactions")
    for r in rows:
        raw = vault_get(con, r["desc_token"])
        k = (r["txn_date"].isoformat(), r["debit"], r["credit"])
        if k in keys and keys[k] != raw:
            print("MISMATCH", repr(raw), "vs", repr(keys[k]))
