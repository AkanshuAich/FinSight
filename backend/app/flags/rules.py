"""Risk indicators. Every flag says 'review recommended' with its reason and evidence, never 'fraud'."""
from __future__ import annotations

import statistics
from datetime import timedelta

from .. import config
from ..money import fmt_inr


def _flag(code, severity, title, detail, txn_ids=None, months=None, category="risk"):
    return {"code": code, "severity": severity, "title": title, "detail": detail, "txn_ids": txn_ids or [], "months": months or [],
            "category": category}


def evaluate(case: dict, txns: list[dict], gold: dict, ctx: dict) -> list[dict]:
    flags = []
    m = gold["metrics"]
    inc = m["estimated_income"]
    series = [x["value"] for x in inc["monthly"]]
    if len(series) >= 4:
        h = min(3, len(series) // 2)  # latest months vs the same number before them
        recent, prior = statistics.mean(series[-h:]), statistics.mean(series[-2 * h:-h])
        if prior and (recent - prior) / prior <= -0.20:
            drop = (prior - recent) / prior
            flags.append(_flag("income_decline", "high" if drop >= 0.35 else "medium", "Declining income",
                               f"Income in the last {h} covered months averaged {fmt_inr(int(recent))}, down {drop * 100:.0f}% from "
                               f"{fmt_inr(int(prior))} in the {h} months before.", months=[x["month"] for x in inc["monthly"][-2 * h:]]))
    full = [r for r in gold["monthly"] if r["coverage"] == "full"]
    # rising expenses: later half of the covered months vs the earlier half
    if len(full) >= 4:
        h = len(full) // 2
        early, late = statistics.mean(r["debits_adjusted"] for r in full[:h]), statistics.mean(r["debits_adjusted"] for r in full[-h:])
        if early and (late - early) / early >= 0.25:
            flags.append(_flag("rising_expenses", "medium", "Expenses rising",
                               f"Average monthly outflows rose {(late - early) / early * 100:.0f}%, from {fmt_inr(int(early))} in "
                               f"{full[0]['month']}–{full[h - 1]['month']} to {fmt_inr(int(late))} in {full[-h]['month']}–{full[-1]['month']}.",
                               months=[r["month"] for r in full[-h:]]))
    # several unusually large, non-routine credits
    income_est = inc.get("value") or 0
    routine = {"SALARY", "INTERNAL_TRANSFER", "REFUND_REVERSAL", "LOAN_DISBURSAL", "BOUNCE_RETURN"}
    credit_amts = [t["credit"] for t in txns if t["direction"] == "C" and t["category"] not in routine]
    base = income_est or (statistics.median(credit_amts) * 2 if credit_amts else 0)
    large = [t for t in txns if t["direction"] == "C" and t["category"] not in routine and base and t["credit"] >= 1.5 * base
             and t["credit"] >= 50_000_00]
    if len(large) >= 2:
        flags.append(_flag("multiple_large_credits", "medium", "Several unusually large credits",
                           f"{len(large)} credits of at least 1.5× the estimated monthly income ({fmt_inr(int(base))}): "
                           + ", ".join(f"{fmt_inr(t['credit'])} on {t['txn_date']:%d %b}" for t in large[:5]) + ". Confirm their source.",
                           txn_ids=[t["txn_id"] for t in large]))
    # sudden behaviour change: the latest covered month against the typical earlier month
    if len(full) >= 3:
        last, prior = full[-1], full[:-1]
        changes = []
        for key, label in (("credits_adjusted", "inflows"), ("debits_adjusted", "outflows"), ("n_txns", "transaction count")):
            typical = statistics.median(r[key] for r in prior)
            if typical and (last[key] >= 2 * typical or last[key] <= 0.5 * typical):
                shown = (lambda v: str(int(v))) if key == "n_txns" else (lambda v: fmt_inr(int(v)))
                changes.append(f"{label} {shown(last[key])} vs a typical {shown(typical)}")
        if changes:
            flags.append(_flag("behaviour_change", "medium", "Sudden change in account behaviour",
                               f"In {last['month']}: " + "; ".join(changes) + ".", months=[last["month"]]))
    neg = [r for r in gold["monthly"] if r["coverage"] == "full" and r["net"] < 0]
    if len(neg) >= 2:
        flags.append(_flag("negative_net_cash_flow", "medium", "Repeated negative net cash flow",
                           f"Outflows exceeded inflows in {len(neg)} fully covered months: "
                           + ", ".join(f"{r['month']} ({fmt_inr(r['net'])})" for r in neg) + ".", months=[r["month"] for r in neg]))
    accts = {a["account_id"]: a for a in ctx["accounts"]}
    for acct, a in accts.items():
        low = [(r["month"], r["balances"][acct]["low_days"], r["balances"][acct]["days"]) for r in gold["monthly"] if acct in r["balances"]]
        low_days, days = sum(x[1] for x in low), sum(x[2] for x in low)
        if days and low_days / days >= 0.08:
            flags.append(_flag("low_balance", "medium", "Frequent low balances",
                               f"{a['bank_name']} {a['acct_masked']} closed below {fmt_inr(config.LOW_BALANCE_PAISE)} on {low_days} of {days} "
                               f"covered days.", months=[x[0] for x in low if x[1]]))
    bounces = [t for t in txns if t["category"] == "BOUNCE_RETURN" or "bounce_charge" in t["attributes"]]
    if bounces:
        flags.append(_flag("returned_payment", "high", "Returned / bounced payment",
                           f"{sum(1 for t in bounces if t['category'] == 'BOUNCE_RETURN' and t['direction'] == 'C')} payment(s) returned unpaid, "
                           f"with {sum(1 for t in bounces if 'bounce_charge' in t['attributes'])} return charge(s).",
                           txn_ids=[t["txn_id"] for t in bounces]))
    by_id = {t["txn_id"]: t for t in txns}
    for p in ctx["patterns"]:
        members = [by_id[i] for i in p["txn_ids"] if i in by_id]
        cats = {t["category"] for t in members}
        if not p["missed_months"] or not members:
            continue
        if "SALARY" in cats:
            # a month with any salary credit on the account is not missed, even if worded differently from the series
            paid = {f"{t['txn_date']:%Y-%m}" for t in txns if t["category"] == "SALARY" and t["account_id"] == p["account_id"]}
            p = dict(p, missed_months=[m for m in p["missed_months"] if m not in paid])
            if not p["missed_months"]:
                continue
            flags.append(_flag("missed_salary", "high", "Expected salary not received",
                               f"Monthly salary of about {fmt_inr(p['median_amount'])} (day ~{p['typical_day']}) did not arrive in "
                               f"{', '.join(p['missed_months'])}, although those months are fully covered.", txn_ids=p["txn_ids"], months=p["missed_months"]))
        elif cats & {"LOAN_EMI", "RENT"}:
            flags.append(_flag("missed_obligation", "medium", "Expected EMI or rent not seen",
                               f"A recurring payment of about {fmt_inr(p['median_amount'])} was not seen in {', '.join(p['missed_months'])}.",
                               txn_ids=p["txn_ids"], months=p["missed_months"]))
    credits = [t["credit"] for t in txns if t["direction"] == "C"]
    med_credit = statistics.median(credits) if credits else 0
    big_cash = [t for t in txns if t["category"] == "CASH_DEPOSIT"
                and (t["credit"] >= config.LARGE_CASH_PAISE or (med_credit and t["credit"] >= 3 * med_credit and t["credit"] >= 1_00_000_00))]
    if big_cash:
        flags.append(_flag("large_cash_deposit", "medium", "Large cash deposit",
                           "Cash deposited without a documented source: " + ", ".join(f"{fmt_inr(t['credit'])} on {t['txn_date']:%d %b %Y}" for t in big_cash)
                           + ". Verify the source before relying on it.", txn_ids=[t["txn_id"] for t in big_cash]))
    app = case.get("application_date")
    if app:
        pre = [t for t in txns if t["direction"] == "C" and t["credit"] >= config.ROUND_FIGURE_MIN_PAISE and t["credit"] % 1_000_000 == 0
               and app - timedelta(days=config.PRE_APPLICATION_DAYS) <= t["txn_date"] <= app
               and t["category"] not in ("SALARY", "INTERNAL_TRANSFER", "REFUND_REVERSAL", "LOAN_DISBURSAL", "CASH_DEPOSIT")]
        if pre:
            flags.append(_flag("round_figure_pre_application", "medium", "Round-figure credit shortly before application",
                               ", ".join(f"{fmt_inr(t['credit'])} on {t['txn_date']:%d %b %Y}" for t in pre)
                               + f", within {config.PRE_APPLICATION_DAYS} days of the application date. Confirm the source.",
                               txn_ids=[t["txn_id"] for t in pre]))
    # data quality
    for s in ctx["statements"]:
        if s["recon_status"] in ("unreconciled", "breaks", "reconciled_with_row_breaks"):
            breaks = [t for t in txns if t["recon_status"] == "break" and t["account_id"] == s["account_id"]
                      and s["period_start"] <= t["txn_date"] <= s["period_end"]]
            sev = "medium" if s["recon_status"] == "unreconciled" else "low"
            detail = (f"Opening + credits - debits differs from the stated closing balance by {fmt_inr(s['recon_diff'])}. "
                      if s["recon_status"] == "unreconciled" else "Totals reconcile, but ")
            detail += f"{s['n_breaks']} row(s) break the running-balance chain." if s["n_breaks"] else ""
            flags.append(_flag("reconciliation", sev, f"Statement does not fully reconcile ({s['bank_name']} {s['acct_masked']})",
                               detail.strip(), txn_ids=[t["txn_id"] for t in breaks], category="data"))
    acct_name = {a["account_id"]: f"{a['bank_name']} {a['acct_masked']}" for a in ctx["accounts"]}
    for c in ctx["cross_checks"]:
        where = acct_name.get(c["account_id"], "")
        detail = c["detail"][:1].upper() + c["detail"][1:]
        if c["kind"] == "gap":
            flags.append(_flag("coverage_gap", "medium", f"Missing statement period ({where})", detail + ". Metrics skip these months.",
                               months=[], category="data"))
        elif c["kind"] == "balance_mismatch":
            flags.append(_flag("statement_balance_mismatch", "medium", f"Statements do not chain ({where})", detail + ".", category="data"))
        elif c["kind"] == "overlap":
            flags.append(_flag("overlapping_statements", "info", f"Overlapping statements ({where})", detail + ".", category="data"))
    if ctx["duplicate_uploads"]:
        flags.append(_flag("duplicate_upload", "info", "Duplicate upload ignored",
                           f"{len(ctx['duplicate_uploads'])} file(s) were uploaded more than once: "
                           + ", ".join(sorted({d['filename'] for d in ctx['duplicate_uploads']})) + ". Each was processed once.", category="data"))
    for d in ctx.get("edit_checks", []):
        if d["level"] in ("medium", "high"):
            reasons = "; ".join(s["detail"].rstrip(".") for s in d["signals"] if s["weight"] > 0)
            flags.append(_flag("possible_document_edit", "high" if d["level"] == "high" else "medium",
                               f"Possible editing: {d['filename']} (edit risk {d['score']}/100)",
                               reasons + ". Verify against a copy obtained directly from the bank or via Account Aggregator."))
    for f in ctx["files"]:
        if f["status"] in ("failed", "needs_password"):
            flags.append(_flag("file_not_processed", "high", f"File not processed: {f['filename']}", f["reason"] or "", category="data"))
    for p in ctx["bad_pages"]:
        flags.append(_flag("page_not_processed", "high", f"Page {p['page_no']} of {p['filename']} not read", p["reason"] or "", category="data"))
    review = [t for t in txns if t["status"] in ("review", "unclassified")]
    if review:
        flags.append(_flag("review_queue", "low", f"{len(review)} transaction(s) need a category decision",
                           "Low-confidence or conflicting evidence. Income excludes these until confirmed.", txn_ids=[t["txn_id"] for t in review],
                           category="review"))
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(flags, key=lambda f: (order[f["severity"]], f["category"] != "risk", f["title"]))
