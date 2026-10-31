"""Accuracy and efficiency on datasets/multilingual_v1 (English, Hindi, Hinglish, Gujarati, Tamil).

Accuracy: category accuracy overall / by language / by split / by category, share decided automatically and
how often those automatic decisions are right, statement-level income error, expected-flag recall.
Efficiency: upload (extract + reconcile + dedup) and analysis (classify + metrics + flags) time, rows per second,
peak Python memory, and the latency of an analyst correction including full recalculation.

  python backend/tests/eval_multilingual.py [--out name]
"""
import collections
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_ml_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import analysis  # noqa: E402
from app.classify import engine, semantic  # noqa: E402
from app.classify.categories import INCOME  # noqa: E402
from app.db import connect, q  # noqa: E402
from app.ingest import service as ingest  # noqa: E402
from app.metrics import effective  # noqa: E402
from app.review import overrides  # noqa: E402
from app.security.crypto import vault_get  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DS = ROOT / "datasets" / "multilingual_v1"
out_name = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "multilingual_eval"
FLAG_CODES = {"returned_payment", "large_cash_deposit", "missed_salary", "income_decline"}

manifest = json.loads((DS / "manifest.json").read_text(encoding="utf-8"))
truth = {}
for line in (DS / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    truth[(r["account_number"], r["date"], r["debit"], r["credit"], r["description"])] = r

connect()
semantic.seed()
tracemalloc.start()
rows, stmt_results, timing = [], [], collections.defaultdict(list)
for m in manifest:
    case_id = f"c_{m['id']}"
    connect().execute("INSERT INTO silver.cases VALUES (?, ?, DATE '2026-07-10', ?, FALSE, NULL, now())", [case_id, m["name"], m["profile"]])
    n_rows = 0
    for fname in m["files"]:
        data = (DS / fname).read_bytes()
        t0 = time.perf_counter()
        rep = ingest.upload(case_id, fname, data, actor="eval", role="analyst")
        timing["upload_s"].append(time.perf_counter() - t0)
        timing["upload_rows"].append(sum(p["n_rows"] or 0 for p in rep["pages"]))
        n_rows += timing["upload_rows"][-1]
    t0 = time.perf_counter()
    engine.run(case_id, "eval")
    timing["classify_s"].append(time.perf_counter() - t0)
    t0 = time.perf_counter()
    snap = analysis.run(case_id, "eval")
    timing["analysis_s"].append(time.perf_counter() - t0)
    timing["case_rows"].append(n_rows)

    con = connect()
    acct = {a["account_id"]: vault_get(con, a["acct_token"]) for a in q("SELECT account_id, acct_token FROM silver.accounts WHERE case_id = ?", [case_id])}
    tok = {t["txn_id"]: t["desc_token"] for t in q("SELECT txn_id, desc_token FROM silver.transactions WHERE case_id = ?", [case_id])}
    unmatched = 0
    for t in effective.transactions(case_id):
        key = (acct.get(t["account_id"]), t["txn_date"].isoformat(), t["debit"], t["credit"], vault_get(con, tok[t["txn_id"]]))
        g = truth.get(key)
        if not g:
            unmatched += 1
            continue
        rows.append({"dataset": m["id"], "split": m["split"], "lang": g["lang"], "gold": g["category"], "pred": t["category"], "status": t["status"],
                     "desc": g["description"], "amount": t["amount"], "tags": g["tags"]})
    inc = (snap.get("metrics") or {}).get("estimated_income") or {}
    flags = {f["code"] for f in snap.get("flags", [])} & FLAG_CODES
    expected = set(m["expected_flags"])
    true_inc = m["true_income_median"]
    stmt_results.append({"id": m["id"], "split": m["split"], "name": m["name"], "profile_true": m["profile"], "profile_pred": snap.get("profile"),
                         "income_true": true_inc, "income_pred": inc.get("value"), "income_method": inc.get("method"),
                         "income_abs_pct_err": round(abs((inc.get("value") or 0) - true_inc) / true_inc, 3) if true_inc else None,
                         "flags_expected": sorted(expected), "flags_found": sorted(flags & expected), "flags_missed": sorted(expected - flags),
                         "flags_unexpected": sorted(flags - expected), "unmatched_rows": unmatched})
    print(f"{m['id']} {m['split']:4s} rows={n_rows:4d} upload={sum(timing['upload_s'][-len(m['files']):]):.2f}s "
          f"classify={timing['classify_s'][-1]:.2f}s analysis={timing['analysis_s'][-1]:.2f}s", flush=True)

# correction latency: one override with full recompute, on the largest case
big = max(manifest, key=lambda m: m["n_transactions"])
case_id = f"c_{big['id']}"
target = next(t for t in effective.transactions(case_id) if t["credit"])
t0 = time.perf_counter()
overrides.apply(case_id, target["txn_id"], "OTHER_CREDIT", "latency test", "evt-latency", "eval", "analyst")
timing["correction_s"].append(time.perf_counter() - t0)
_, peak = tracemalloc.get_traced_memory()


def summarise(rs):
    n = len(rs)
    if not n:
        return {}
    auto = [r for r in rs if r["status"] in ("auto", "confirmed")]
    return {"n": n, "accuracy": round(sum(r["pred"] == r["gold"] for r in rs) / n, 4),
            "auto_share": round(len(auto) / n, 4),
            "auto_accuracy": round(sum(r["pred"] == r["gold"] for r in auto) / len(auto), 4) if auto else None,
            "review_share": round(sum(r["status"] == "review" for r in rs) / n, 4),
            "unclassified_share": round(sum(r["status"] == "unclassified" for r in rs) / n, 4),
            "income_recall": (lambda inc: round(sum(r["pred"] == r["gold"] and r["status"] in ("auto", "confirmed") for r in inc) / len(inc), 4) if inc else None)(
                [r for r in rs if r["gold"] in INCOME])}


report = {"overall": summarise(rows)}
report["by_split"] = {s: summarise([r for r in rows if r["split"] == s]) for s in ("dev", "test")}
report["by_language"] = {lg: summarise([r for r in rows if r["lang"] == lg]) for lg in ("en", "hi", "hi-Latn", "gu", "ta")}
report["by_language_test"] = {lg: summarise([r for r in rows if r["lang"] == lg and r["split"] == "test"]) for lg in ("en", "hi", "hi-Latn", "gu", "ta")}
cats = sorted({r["gold"] for r in rows} | {r["pred"] for r in rows})
per_cat = []
for c in cats:
    tp = sum(r["pred"] == c and r["gold"] == c for r in rows)
    fp = sum(r["pred"] == c and r["gold"] != c for r in rows)
    fn = sum(r["pred"] != c and r["gold"] == c for r in rows)
    per_cat.append({"category": c, "support": tp + fn, "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 3) if tp + fn else None})
report["per_category"] = per_cat
conf = collections.Counter((r["gold"], r["pred"]) for r in rows if r["gold"] != r["pred"])
report["top_confusions"] = [{"gold": g, "pred": p, "count": c, "examples": [r["desc"] for r in rows if r["gold"] == g and r["pred"] == p][:3]}
                            for (g, p), c in conf.most_common(15)]
report["statements"] = stmt_results
errs = [s["income_abs_pct_err"] for s in stmt_results if s["income_abs_pct_err"] is not None]
report["statement_summary"] = {
    "profile_correct": sum(s["profile_true"] == s["profile_pred"] for s in stmt_results), "statements": len(stmt_results),
    "income_median_abs_pct_err": round(statistics.median(errs), 3) if errs else None,
    "income_within_10pct": sum(e <= 0.10 for e in errs),
    "flag_recall": f"{sum(len(s['flags_found']) for s in stmt_results)}/{sum(len(s['flags_expected']) for s in stmt_results)}",
    "unexpected_flags": sum(len(s["flags_unexpected"]) for s in stmt_results)}
total_rows = sum(timing["upload_rows"])
report["efficiency"] = {
    "statements": len(manifest), "files": len(timing["upload_s"]), "rows": total_rows,
    "upload_total_s": round(sum(timing["upload_s"]), 2), "upload_rows_per_s": round(total_rows / sum(timing["upload_s"]), 1),
    "classify_total_s": round(sum(timing["classify_s"]), 2), "classify_rows_per_s": round(total_rows / sum(timing["classify_s"]), 1),
    "analysis_total_s": round(sum(timing["analysis_s"]), 2),
    "end_to_end_per_statement_s_median": round(statistics.median(
        [u + a for u, a in zip([sum(timing["upload_s"][i:i + len(m["files"])]) for i, m in
                                zip(__import__("itertools").accumulate([0] + [len(m["files"]) for m in manifest]), manifest)], timing["analysis_s"])]), 2),
    "correction_with_recompute_s": round(timing["correction_s"][0], 2), "correction_case_rows": big["n_transactions"],
    "peak_python_memory_mb": round(peak / 1e6, 1)}
dest = Path(__file__).with_name(f"{out_name}.json")
dest.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: report[k] for k in ("overall", "by_split", "statement_summary", "efficiency")}, ensure_ascii=False, indent=1))
print("written", dest)
