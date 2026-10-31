"""Evaluate FinSight end to end on AgamiAI/Indian-Bank-Statements (PDF + JSON label pairs).

Each PDF goes through the real upload pipeline in its own case, then is compared with its JSON label:
  header fields, row recall/precision (matched on date + amount + direction), amount, balance and
  narration fidelity, reconciliation, reversal detection (label `failed` rows and their reversals),
  agreement on narration types whose meaning is unambiguous, and scanned-page reporting.

  python backend/tests/eval_hf_statements.py <dataset train dir> [--limit N] [--types Digital_Type1,...] [--out name]
"""
import collections
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_hf_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rapidfuzz import fuzz  # noqa: E402

from app import analysis  # noqa: E402
from app.classify import semantic  # noqa: E402
from app.db import connect, q, q1  # noqa: E402
from app.ingest import service as ingest  # noqa: E402
from app.metrics import effective  # noqa: E402
from app.money import parse_date, to_paise  # noqa: E402
from app.security.crypto import vault_get  # noqa: E402

root = Path(sys.argv[1])
arg = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default  # noqa: E731
limit = int(arg("--limit", 0)) or None
types = arg("--types", "Digital_Type1,Digital_Type2,Scanned_Type1,Scanned_Type2").split(",")
out_name = arg("--out", "hf_eval")

# Narration prefixes whose meaning does not depend on our rules (the dataset generator's own types)
UNAMBIGUOUS = [
    (r"^ATM WDL", "D", "CASH_WITHDRAWAL"), (r"^(CASH WITHDRAWAL|Cash Withdrawal)", "D", "CASH_WITHDRAWAL"),
    (r"^CASH DEPOSIT", "C", "CASH_DEPOSIT"), (r"^(Service Charges|SERVICE CHARGES)", "D", "BANK_CHARGES"),
    (r"^Dividend Cr", "C", "OTHER_CREDIT"), (r"SALARY", "D", "PAYROLL_PAYMENT"),
]


def label_rows(j: dict) -> list[dict]:
    rows = []
    for t in j["transactions"]:
        if "transaction_amount" in t:  # Type 2: single amount column with CR/DR
            amt = to_paise(t["transaction_amount"])
            dr, cr = (amt, 0) if t["cr_dr"].upper() == "DR" else (0, amt)
            bal = to_paise(t.get("available_balance"))
        else:
            dr, cr, bal = to_paise(t.get("debit")) or 0, to_paise(t.get("credit")) or 0, to_paise(t.get("balance"))
        d = parse_date(str(t["date"]).split(" ")[0])
        rows.append({"date": d, "debit": dr, "credit": cr, "balance": bal, "description": t["description"], "failed": bool(t.get("failed"))})
    return rows


connect()
semantic.seed()
files = []
for t in types:
    d = root / f"India_Bank_Statement_{t}"
    files += [(t, p) for p in sorted(d.glob("*.pdf"))][: limit or None]

R = collections.defaultdict(collections.Counter)
examples = collections.defaultdict(list)
t0 = time.time()
for i, (typ, pdf) in enumerate(files):
    lab = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    truth = label_rows(lab)
    case_id = f"c_hf_{i:04d}"
    connect().execute("INSERT INTO silver.cases VALUES (?, ?, ?, 'UNKNOWN', FALSE, NULL, now())",
                      [case_id, f"{typ}/{pdf.name}", parse_date(lab["end_date"])])
    c = R[typ]
    c["statements"] += 1
    c["label_rows"] += len(truth)
    try:
        rep = ingest.upload(case_id, pdf.name, pdf.read_bytes(), actor="eval", role="analyst")
        analysis.run(case_id, "eval")
    except Exception as e:
        c["crashed"] += 1
        examples[typ + ":crash"].append(f"{pdf.name}: {type(e).__name__}: {e}")
        continue
    c[f"file_{rep['status']}"] += 1
    for p in rep["pages"]:
        c[f"page_{p['status']}"] += 1
    if typ.startswith("Scanned"):
        continue

    # ---- header
    acct = q1("SELECT * FROM silver.accounts WHERE case_id = ?", [case_id])
    st = q1("SELECT * FROM silver.statements WHERE case_id = ?", [case_id])
    con = connect()
    if acct:
        got = vault_get(con, acct["acct_token"]) or ""
        c["hdr_account_ok"] += got == lab["account_number"]
        if got != lab["account_number"] and len(examples[typ + ":acct"]) < 5:
            examples[typ + ":acct"].append(f"{pdf.name}: got {got!r} want {lab['account_number']!r}")
        holders = [vault_get(con, t) for t in json.loads(acct["holder_token"] or "[]")]
        c["hdr_holder_ok"] += any(h and fuzz.ratio(h, lab["account_holder"].upper()) >= 90 for h in holders)
        c["hdr_bank_ok"] += fuzz.ratio((acct["bank_name"] or "").upper(), lab["bank_name"].upper()) >= 85
    # does the label itself reconcile? (opening + credits - debits = closing)
    label_ok = to_paise(lab["opening_balance"]) + sum(t["credit"] - t["debit"] for t in truth) == to_paise(lab["closing_balance"])
    c["label_reconciles"] += label_ok
    if st:
        c["recon_agrees_with_label"] += (st["recon_status"] == "reconciled") == label_ok
        c["hdr_period_ok"] += (str(st["period_start"]) == lab["start_date"] and str(st["period_end"]) == lab["end_date"])
        c["hdr_opening_ok"] += st["opening_paise"] == to_paise(lab["opening_balance"]) and st["opening_source"] == "stated"
        c["hdr_closing_ok"] += st["closing_stated"] == to_paise(lab["closing_balance"])
        c[f"recon_{st['recon_status']}"] += 1
        if st["recon_status"] != "reconciled" and len(examples[typ + ":recon"]) < 5:
            examples[typ + ":recon"].append(f"{pdf.name}: {st['recon_status']} diff={st['recon_diff']} breaks={st['n_breaks']}")

    # ---- rows: match on (date, debit, credit); then compare balance and narration
    pred = effective.transactions(case_id)
    tokens = {r["txn_id"]: r["desc_token"] for r in q("SELECT txn_id, desc_token FROM silver.transactions WHERE case_id = ?", [case_id])}
    pool = collections.defaultdict(list)
    for p in pred:
        pool[(p["txn_date"], p["debit"], p["credit"])].append(p)
    c["pred_rows"] += len(pred)
    matched = []
    for t in truth:
        k = (t["date"], t["debit"], t["credit"])
        if pool[k]:
            p = pool[k].pop(0)
            matched.append((t, p))
        elif len(examples[typ + ":missed_row"]) < 8:
            examples[typ + ":missed_row"].append(f"{pdf.name}: {t['date']} dr={t['debit']} cr={t['credit']} {t['description'][:50]}")
    c["matched_rows"] += len(matched)
    # ground truth for reversals: the REVERSAL line and the original entry it undoes (same narration, same amount, earlier)
    for t in truth:
        t["is_rev"] = t["failed"] or t["description"].upper().startswith("REVERSAL")
    for r in [t for t in truth if t["description"].upper().startswith("REVERSAL")]:
        body = r["description"].split("-", 1)[1].strip().upper() if "-" in r["description"] else ""
        amt = r["debit"] or r["credit"]
        for o in truth:
            if not o["is_rev"] and (o["debit"] or o["credit"]) == amt and o["date"] <= r["date"] and o["description"].strip().upper() == body:
                o["is_rev"] = True
                break
    for t, p in matched:
        c["balance_ok"] += t["balance"] == p["balance"]
        raw = vault_get(con, tokens[p["txn_id"]]) or ""
        # case-insensitive: the dataset's PDFs and labels disagree on case for some narrations
        sim = fuzz.ratio(re.sub(r"\s+", " ", raw).strip().upper(), re.sub(r"\s+", " ", t["description"]).strip().upper())
        c["desc_exact"] += sim == 100
        c["desc_ge90"] += sim >= 90
        if sim < 90 and len(examples[typ + ":desc"]) < 6:
            examples[typ + ":desc"].append(f"{sim:.0f} | got {raw[:60]!r} | want {t['description'][:60]!r}")
        # reversals: the failed debit and its reversal credit should both be excluded as REFUND_REVERSAL
        is_rev = t["is_rev"]
        got_rev = p["category"] == "REFUND_REVERSAL"
        c["rev_tp"] += is_rev and got_rev
        c["rev_fn"] += is_rev and not got_rev
        c["rev_fp"] += got_rev and not is_rev
        if is_rev and not got_rev and len(examples[typ + ":rev_missed"]) < 6:
            examples[typ + ":rev_missed"].append(f"{t['description'][:60]} -> {p['category']}")
        direction = "C" if t["credit"] else "D"
        for pat, dirn, cat in UNAMBIGUOUS:
            if dirn == direction and not is_rev and re.search(pat, t["description"]):
                c["type_total"] += 1
                c["type_agree"] += p["category"] == cat
                if p["category"] != cat and len(examples[typ + ":type"]) < 8:
                    examples[typ + ":type"].append(f"{t['description'][:50]} -> {p['category']} (want {cat})")
                break
        c[f"status_{p['status']}"] += 1
    if (i + 1) % 25 == 0:
        print(f"{i + 1}/{len(files)} {time.time() - t0:.0f}s", flush=True)

summary = {}
for typ, c in R.items():
    s = dict(c)
    if not typ.startswith("Scanned") and c["statements"]:
        n, rows = c["statements"], c["label_rows"]
        s["row_recall"] = round(c["matched_rows"] / rows, 4) if rows else None
        s["row_precision"] = round(c["matched_rows"] / c["pred_rows"], 4) if c["pred_rows"] else None
        for k in ("hdr_account_ok", "hdr_holder_ok", "hdr_bank_ok", "hdr_period_ok", "hdr_opening_ok", "hdr_closing_ok"):
            s[k + "_rate"] = round(c[k] / n, 3)
        m = c["matched_rows"] or 1
        s["balance_exact_rate"] = round(c["balance_ok"] / m, 4)
        s["desc_exact_rate"] = round(c["desc_exact"] / m, 4)
        s["desc_ge90_rate"] = round(c["desc_ge90"] / m, 4)
        s["statements_reconciled_rate"] = round(c["recon_reconciled"] / n, 3)
        s["label_reconciles_rate"] = round(c["label_reconciles"] / n, 3)
        s["recon_agreement_with_label"] = round(c["recon_agrees_with_label"] / n, 3)
        zero = sum(1 for e in examples.get(typ + ":missed_row", []) if "dr=0 cr=0" in e)
        s["note_missed_rows"] = "missed rows are mostly zero-amount FAILED lines, quarantined with a reason"
        tp, fn, fp = c["rev_tp"], c["rev_fn"], c["rev_fp"]
        s["reversal_recall"] = round(tp / (tp + fn), 3) if tp + fn else None
        s["reversal_precision"] = round(tp / (tp + fp), 3) if tp + fp else None
        s["narration_type_agreement"] = round(c["type_agree"] / c["type_total"], 4) if c["type_total"] else None
        s["auto_share"] = round(c["status_auto"] / m, 4)
    summary[typ] = s
summary["_examples"] = examples
summary["_seconds"] = round(time.time() - t0, 1)
dest = Path(__file__).with_name(f"{out_name}.json")
dest.write_text(json.dumps(summary, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
print("written", dest)
