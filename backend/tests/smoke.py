"""End-to-end smoke run on a throwaway database: load demo data, print key results."""
import json, os, sys, tempfile, time
os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_smoke_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app.main import app

def inr(p): return "-" if p is None else f"{p/100:,.0f}"

with TestClient(app) as c:
    t0 = time.time()
    r = c.post("/api/demo/load"); r.raise_for_status()
    print("demo load", round(time.time()-t0,1), "s", r.json())
    for case in c.get("/api/cases").json():
        cid = case["case_id"]
        a = c.get(f"/api/cases/{cid}/analysis").json()
        m = a["metrics"]
        print("\n====", case["name"], "| profile", a["profile"], "| txns", a["n_transactions"], "| status", a["status_counts"])
        for k in ("estimated_income","recurring_obligations","foir","net_cash_flow","average_balance"):
            v = m[k]["value"]; print(f"  {k:24s} {v if k=='foir' else inr(v):>14}  {m[k]['method'][:110]}")
        print("  months:", a["coverage"])
        for f in a["flags"]: print(f"  [{f['severity']:6s}] {f['title']}: {f['detail'][:140]}")
        for s in a["statements"]: print(f"  stmt {s['bank_name']} {s['acct_masked']} {s['period_start']}..{s['period_end']} {s['recon_status']} diff={s['recon_diff']} breaks={s['n_breaks']} rows={s['n_rows']}")
        for p in a["patterns"]: print(f"  pattern {p['direction']} {p['counterparties']} {inr(p['median_amount'])} months={len(p['months'])} missed={p['missed_months']}")
        e = c.get(f"/api/cases/{cid}/evaluation").json()
        print("  EVAL acc", e.get("accuracy"), "auto_share", e.get("auto_share"), "auto_acc", e.get("auto_accuracy"), "matched", e.get("matched"), e.get("by_status"))
        for err in e.get("errors", [])[:25]: print("    x", err["expected"], "->", err["predicted"], err["status"], "|", err["description"])
    files = c.get(f"/api/cases/{c.get('/api/cases').json()[0]['case_id']}/files").json()
    for f in files["files"]: print("FILE", f["filename"], f["status"], "|", f["reason"], [(p["page_no"], p["status"]) for p in f["pages"]])
