"""Run the FinSight pipeline on the VLM bank statement dataset's ground-truth JSON.

The dataset pairs page images with extraction labels (header + transactions) but has no category labels.
This script merges each statement's pages, ingests it through the real JSON path, and reports:
  ingestion fidelity (rows in = rows out), reconciliation, classification confidence and coverage.
Reads the zip directly; images are not extracted.

  python backend/tests/eval_vlm_dataset.py <path-to-zip> [split] [--limit N]
"""
import collections
import json
import os
import re
import sys
import tempfile
import time
import zipfile

os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_vlm_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import analysis  # noqa: E402
from app.classify import semantic  # noqa: E402
from app.db import connect, q  # noqa: E402
from app.ingest import service as ingest  # noqa: E402
from app.metrics import effective  # noqa: E402
from app.money import parse_date  # noqa: E402

zip_path = sys.argv[1]
split = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "test"
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

z = zipfile.ZipFile(zip_path)
records = [json.loads(l) for l in z.read(f"vlm_training_dataset/{split}.jsonl").decode("utf-8").splitlines()]
by_src = collections.defaultdict(list)
for r in records:
    by_src[r["source"]].append(r)
sources = sorted(by_src)[:limit]

connect()
semantic.seed()
out = {"statements": 0, "label_rows": 0, "ingested_rows": 0, "row_mismatch": [], "file_status": collections.Counter(),
       "recon": collections.Counter(), "status": collections.Counter(), "status_nonascii": collections.Counter(),
       "category": collections.Counter(), "profile": collections.Counter(), "income_found": 0, "flags": collections.Counter(),
       "review_examples": collections.Counter(), "errors": []}
t0 = time.time()
for i, src in enumerate(sources):
    pages = sorted(by_src[src], key=lambda r: r["page"])
    labels = [json.loads(p["conversations"][-1]["content"]) for p in pages]
    head = labels[0]
    txns = [t for l in labels for t in l.get("transactions", [])]
    closing = next((l["closing_balance"] for l in reversed(labels) if l.get("closing_balance") is not None), None)
    doc = {"bank_name": head.get("bank_name"), "account_holder": head.get("account_holder_name"),
           "account_number": head.get("account_number"), "account_type": head.get("account_type"),
           "statement_period": head.get("statement_period") or {}, "opening_balance": head.get("opening_balance"),
           "closing_balance": closing, "transactions": txns}
    case_id = f"c_vlm_{i:04d}"
    app_date = parse_date(doc["statement_period"].get("to")) or max((parse_date(t["date"]) for t in txns if parse_date(t["date"])), default=None)
    connect().execute("INSERT INTO silver.cases VALUES (?, ?, ?, 'UNKNOWN', FALSE, NULL, now())", [case_id, src, app_date])
    try:
        rep = ingest.upload(case_id, f"{src}.json", json.dumps(doc).encode(), actor="eval", role="analyst")
        snap = analysis.run(case_id, "eval")
    except Exception as e:  # keep going; report the failure
        out["errors"].append(f"{src}: {type(e).__name__}: {e}")
        continue
    out["statements"] += 1
    out["file_status"][rep["status"]] += 1
    n_in = len(effective.transactions(case_id))
    out["label_rows"] += len(txns)
    out["ingested_rows"] += n_in
    if n_in != len(txns):
        out["row_mismatch"].append((src, len(txns), n_in))
    for s in q("SELECT recon_status FROM silver.statements WHERE case_id = ?", [case_id]):
        out["recon"][s["recon_status"]] += 1
    for t in effective.transactions(case_id):
        out["status"][t["status"]] += 1
        out["category"][t["category"]] += 1
        if re.search(r"[^\x00-\x7f]", t["description"] or ""):
            out["status_nonascii"][t["status"]] += 1
        if t["status"] in ("review", "unclassified"):
            pattern = re.sub(r"\d+|X{3,}\d*", "#", t["description_norm"] or "")[:48]
            out["review_examples"][f"{'CR' if t['credit'] else 'DR'} {pattern}"] += 1
    out["profile"][snap.get("profile")] += 1
    out["income_found"] += bool((snap.get("metrics", {}).get("estimated_income") or {}).get("value"))
    for f in snap.get("flags", []):
        out["flags"][f["code"]] += 1
    if (i + 1) % 20 == 0:
        print(f"{i + 1}/{len(sources)} statements, {time.time() - t0:.0f}s", flush=True)

out["seconds"] = round(time.time() - t0, 1)
for k in ("file_status", "recon", "status", "status_nonascii", "category", "profile", "flags"):
    out[k] = dict(out[k].most_common())
out["review_examples"] = out["review_examples"].most_common(30)
dest = os.path.join(os.path.dirname(__file__), f"vlm_eval_{split}.json")
with open(dest, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("written", dest)
