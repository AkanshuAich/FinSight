"""Gold metrics. Pure functions over the categories in effect; every value carries its lineage:
the transactions included, those excluded with a reason, and the months used or missing.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from .. import config
from ..classify.categories import CATEGORIES, EXCLUDED, INCOME, OBLIGATIONS
from ..ingest.normalize import counterparty_key
from ..money import fmt_inr

TRUSTED = {"auto", "confirmed"}


def _m(d: date) -> str:
    return f"{d:%Y-%m}"


def _label(cat: str) -> str:
    return CATEGORIES.get(cat, {"label": cat})["label"]


def coverage_by_month(coverage: list[dict]) -> tuple[list[str], dict[str, str], dict[str, dict[str, str]]]:
    months = sorted({c["month"] for c in coverage})
    per_acct: dict[str, dict[str, str]] = defaultdict(dict)
    for c in coverage:
        per_acct[c["account_id"]][c["month"]] = c["status"]
    combined = {}
    for m in months:
        st = [per_acct[a].get(m, "missing") for a in per_acct]
        combined[m] = "full" if all(s == "full" for s in st) else ("missing" if all(s == "missing" for s in st) else "partial")
    return months, combined, per_acct


def daily_balances(txns: list[dict], statements: list[dict]) -> dict[str, dict[date, int]]:
    """End-of-day balance per account on covered days only."""
    out: dict[str, dict[date, int]] = {}
    by_acct = defaultdict(list)
    for t in txns:
        if t["balance"] is not None:
            by_acct[t["account_id"]].append(t)
    for s in sorted(statements, key=lambda s: s["period_start"]):
        acct = s["account_id"]
        series = out.setdefault(acct, {})
        rows = sorted((t for t in by_acct[acct] if s["period_start"] <= t["txn_date"] <= s["period_end"]), key=lambda t: (t["txn_date"], t["seq"]))
        eod = {}
        for t in rows:
            eod[t["txn_date"]] = t["balance"]
        bal = s["opening_paise"]
        d = s["period_start"]
        while d <= s["period_end"]:
            bal = eod.get(d, bal)
            if bal is not None and d not in series:
                series[d] = bal
            d += timedelta(days=1)
    return out


def compute(case: dict, txns: list[dict], coverage: list[dict], statements: list[dict], patterns: list[dict]) -> dict:
    months, combined, per_acct = coverage_by_month(coverage)
    full_months = [m for m in months if combined[m] == "full"]
    by_month = defaultdict(list)
    for t in txns:
        by_month[_m(t["txn_date"])].append(t)

    # ---------------------------------------------------------------- monthly table and balances
    balances = daily_balances(txns, statements)
    monthly = []
    for m in months:
        ts = by_month[m]
        cr = sum(t["credit"] for t in ts)
        dr = sum(t["debit"] for t in ts)
        cr_adj = sum(t["credit"] for t in ts if t["category"] not in EXCLUDED)
        dr_adj = sum(t["debit"] for t in ts if t["category"] not in EXCLUDED)
        inc = sum(t["credit"] for t in ts if t["category"] in INCOME and t["status"] in TRUSTED)
        obl = sum(t["debit"] for t in ts if t["category"] in OBLIGATIONS)
        acct_bal = {}
        for acct, series in balances.items():
            vals = [v for d, v in series.items() if _m(d) == m]
            if vals:
                acct_bal[acct] = {"avg": int(statistics.mean(vals)), "min": min(vals),
                                  "low_days": sum(1 for v in vals if v < config.LOW_BALANCE_PAISE), "days": len(vals)}
        monthly.append({"month": m, "coverage": combined[m], "coverage_by_account": {a: per_acct[a].get(m, "missing") for a in per_acct},
                        "credits": cr, "debits": dr, "credits_adjusted": cr_adj, "debits_adjusted": dr_adj,
                        "income": inc, "obligations": obl, "net": cr_adj - dr_adj, "n_txns": len(ts),
                        "avg_balance": sum(b["avg"] for b in acct_bal.values()) if len(acct_bal) == len(balances) and acct_bal else None,
                        "balances": acct_bal})

    # ---------------------------------------------------------------- income
    income_accts = {t["account_id"] for t in txns if t["category"] in INCOME}
    eligible = [m for m in months if all(per_acct[a].get(m) == "full" for a in income_accts)] if income_accts else full_months
    salary = [t for t in txns if t["category"] == "SALARY" and t["status"] in TRUSTED]
    salary_months = {_m(t["txn_date"]) for t in salary}
    profile = "SALARIED" if len(salary_months) >= 3 else "SELF_EMPLOYED"
    income_cats = {"SALARY"} if profile == "SALARIED" else INCOME
    use_months = eligible[-12:]
    included, excluded = [], []
    totals = {m: 0 for m in use_months}
    pending_totals = {m: 0 for m in use_months}  # likely income still awaiting review: shown as provisional, never mixed in
    for t in txns:
        if t["direction"] != "C":
            continue
        m = _m(t["txn_date"])
        cat = t["category"]
        if cat in income_cats and t["status"] in TRUSTED and m in totals:
            totals[m] += t["credit"]
            included.append(t["txn_id"])
        elif cat in income_cats and t["status"] not in TRUSTED:
            if m in pending_totals and t["status"] == "review":
                pending_totals[m] += t["credit"]
            excluded.append({"txn_id": t["txn_id"], "reason": f"{_label(cat)} pending analyst review"})
        elif cat in income_cats:
            excluded.append({"txn_id": t["txn_id"], "reason": f"{m} has incomplete statement coverage"})
        elif cat == "CASH_DEPOSIT":
            excluded.append({"txn_id": t["txn_id"], "reason": "Cash deposit: excluded until its source is verified"})
        elif cat in EXCLUDED:
            excluded.append({"txn_id": t["txn_id"], "reason": f"{_label(cat)}: not income"})
        elif cat in INCOME:
            excluded.append({"txn_id": t["txn_id"], "reason": f"{_label(cat)}: not used for a {profile.lower().replace('_', '-')} estimate"})
        else:
            excluded.append({"txn_id": t["txn_id"], "reason": f"{_label(cat)}: not counted as income"})
    series = [totals[m] for m in use_months]
    notes = []
    income_value, method = None, "insufficient covered months"
    stats = {}
    if series:
        med = int(statistics.median(series))
        income_value = med
        method = f"median of {len(series)} monthly {'salary' if profile == 'SALARIED' else 'income'} totals over fully covered months"
        stats = {"median": med, "mean": int(statistics.mean(series)), "highest": max(series), "lowest": min(series)}
        prov_series = [totals[m] + pending_totals[m] for m in use_months]
        if prov_series != series:
            stats["provisional"] = int(statistics.median(prov_series))
            stats["pending_review_monthly"] = int(statistics.median(pending_totals[m] for m in use_months))
        if len(series) >= 5:
            trimmed = sorted(series)[1:-1]
            stats["trimmed_mean"] = int(statistics.mean(trimmed))
        if len(series) >= 2 and statistics.mean(series):
            stats["cv"] = round(statistics.pstdev(series) / statistics.mean(series), 3)
        # conservative: the level income reached in at least three of every four months (25th percentile)
        stats["conservative"] = int(statistics.quantiles(series, n=4, method="inclusive")[0]) if len(series) >= 3 else min(series)
        if len(series) >= 6:
            recent, prior = statistics.mean(series[-3:]), statistics.mean(series[-6:-3])
            change = (recent - prior) / prior if prior else 0
            stats["trend_3m"] = round(change, 3)
            if change <= -0.15 and recent < med:
                income_value = int(recent)
                method = f"recent 3-month average, because income fell {abs(change) * 100:.0f}% versus the prior 3 months (median {fmt_inr(med)})"
        if profile == "SELF_EMPLOYED" and stats.get("cv", 0) > 0.25:
            notes.append(f"Income is volatile (coefficient of variation {stats['cv']:.2f}); estimate uses the median, not the highest month. "
                         f"Conservative estimate {fmt_inr(stats['conservative'])}: income reached at least this in three of every four months.")
        pending = [e for e in excluded if "pending analyst review" in e["reason"]]
        if not any(series) and pending:
            method = f"no confirmed income yet; {len(pending)} possible income credit(s) await analyst review"
        if "provisional" in stats and stats["provisional"] > (income_value or 0):
            notes.append(f"Confirmed income only. Including the {len(pending)} likely income credit(s) still awaiting review, the "
                         f"provisional estimate is {fmt_inr(stats['provisional'])}. Confirm them in the review queue to firm this up.")
    missing_for_income = [m for m in months if m not in eligible]
    if missing_for_income:
        notes.append(f"Excluded months with incomplete coverage: {', '.join(missing_for_income)}. Missing months are not treated as zero.")
    metrics = {}
    metrics["estimated_income"] = {
        "key": "estimated_income", "label": "Estimated monthly income", "unit": "paise", "value": income_value, "method": method,
        "profile": profile, "monthly": [{"month": m, "value": totals[m]} for m in use_months], "stats": stats,
        "included": included, "excluded": excluded, "months_used": use_months, "months_missing": missing_for_income, "notes": notes}

    # ---------------------------------------------------------------- obligations
    groups = defaultdict(list)
    obl_excluded = []
    for t in txns:
        if t["direction"] != "D":
            continue
        if t["category"] in OBLIGATIONS:
            key = counterparty_key(t["counterparty"] or t["description_norm"][:24]) or "OTHER"
            groups[(t["category"], key)].append(t)
        elif t["category"] == "BOUNCE_RETURN":
            obl_excluded.append({"txn_id": t["txn_id"], "reason": "EMI debit returned unpaid (bounce); not counted as paid"})
    last_month = months[-1] if months else None
    obl_items, obl_included, obl_total = [], [], 0
    for (cat, key), ts in sorted(groups.items()):
        per = defaultdict(int)
        for t in ts:
            per[_m(t["txn_date"])] += t["debit"]
        med = int(statistics.median(per.values()))
        recent = max(per) >= (months[-2] if len(months) >= 2 else last_month)
        active = len(per) >= 2 and recent
        obl_items.append({"category": cat, "label": _label(cat), "counterparty": key, "monthly_amount": med, "months": sorted(per),
                          "active": active, "txn_ids": [t["txn_id"] for t in ts]})
        if active:
            obl_total += med
            obl_included += [t["txn_id"] for t in ts]
        else:
            obl_excluded += [{"txn_id": t["txn_id"], "reason": "not recurring or no longer active"} for t in ts]
    metrics["recurring_obligations"] = {
        "key": "recurring_obligations", "label": "Recurring obligations", "unit": "paise", "value": obl_total,
        "method": "sum of the median monthly amount of each active EMI and rent commitment", "items": obl_items,
        "included": obl_included, "excluded": obl_excluded, "months_used": months, "months_missing": [], "notes": []}
    foir = round(obl_total / income_value, 3) if income_value else None
    metrics["foir"] = {"key": "foir", "label": "Obligation-to-income (FOIR)", "unit": "ratio", "value": foir,
                       "method": "recurring obligations / estimated monthly income", "included": [], "excluded": [],
                       "months_used": use_months, "months_missing": [], "notes": [] if foir is not None else ["income could not be estimated"]}

    # ---------------------------------------------------------------- regular outflows (informational)
    regular = []
    for cat in ("UTILITIES", "CARD_PAYMENT", "INSURANCE", "INVESTMENT", "TAX", "SUPPLIER_PAYMENT", "PAYROLL_PAYMENT"):
        ts = [t for t in txns if t["category"] == cat]
        if not ts:
            continue
        per = defaultdict(int)
        for t in ts:
            per[_m(t["txn_date"])] += t["debit"]
        regular.append({"category": cat, "label": _label(cat), "monthly_median": int(statistics.median(per.values())),
                        "months": len(per), "txn_ids": [t["txn_id"] for t in ts]})

    # ---------------------------------------------------------------- monthly surplus: what is left after typical outflows
    spend_cats = [c for c, v in CATEGORIES.items() if v["treatment"] in ("expense", "obligation")]
    n_full = len(full_months)
    out_items, out_included, out_total = [], [], 0
    for cat in spend_cats:
        ts = [t for t in txns if t["category"] == cat and t["direction"] == "D" and _m(t["txn_date"]) in full_months]
        if not ts or not n_full:
            continue
        per_month = int(sum(t["debit"] for t in ts) / n_full)  # average over covered months, so one-off bills are spread, not inflated
        out_total += per_month
        out_included += [t["txn_id"] for t in ts]
        out_items.append({"category": cat, "label": _label(cat), "counterparty": "", "monthly_amount": per_month,
                          "months": sorted({_m(t["txn_date"]) for t in ts}), "active": True, "txn_ids": [t["txn_id"] for t in ts]})
    out_items.sort(key=lambda i: -i["monthly_amount"])
    surplus = income_value - out_total if income_value is not None and n_full else None
    metrics["monthly_surplus"] = {
        "key": "monthly_surplus", "label": "Monthly surplus", "unit": "paise", "value": surplus,
        "method": f"estimated monthly income {fmt_inr(income_value)} minus typical monthly outflows {fmt_inr(out_total)} "
                  f"(average per fully covered month, by category)",
        "items": out_items, "outflows": out_total, "included": out_included,
        "excluded": [{"txn_id": t["txn_id"], "reason": f"{_label(t['category'])}: not spending"} for t in txns
                     if t["direction"] == "D" and t["category"] in EXCLUDED],
        "months_used": full_months, "months_missing": [m for m in months if m not in full_months],
        "notes": ([] if surplus is None or surplus >= 0 else ["Typical outflows exceed estimated income."])
                 + ([f"With provisional income of {fmt_inr(stats['provisional'])}, the surplus would be {fmt_inr(stats['provisional'] - out_total)}."]
                    if stats.get("provisional", 0) > (income_value or 0) and n_full else [])}

    # ---------------------------------------------------------------- net cash flow and balances
    net_rows = [r for r in monthly if r["coverage"] == "full"]
    net_excl = [{"txn_id": t["txn_id"], "reason": f"{_label(t['category'])}: excluded from adjusted cash flow"}
                for t in txns if t["category"] in EXCLUDED]
    metrics["net_cash_flow"] = {
        "key": "net_cash_flow", "label": "Average monthly net cash flow", "unit": "paise",
        "value": int(statistics.mean(r["net"] for r in net_rows)) if net_rows else None,
        "method": "average of (adjusted credits - adjusted debits) over fully covered months; transfers, reversals, loan proceeds and bounces excluded",
        "monthly": [{"month": r["month"], "value": r["net"]} for r in net_rows],
        "included": [t["txn_id"] for t in txns if t["category"] not in EXCLUDED and _m(t["txn_date"]) in {r["month"] for r in net_rows}],
        "excluded": net_excl, "months_used": [r["month"] for r in net_rows],
        "months_missing": [m for m in months if combined[m] != "full"], "notes": []}
    combined_days = defaultdict(dict)
    for acct, ser in balances.items():
        for d, v in ser.items():
            combined_days[d][acct] = v
    total_series = sorted((d, sum(v.values())) for d, v in combined_days.items() if len(v) == len(balances))
    avg_bal = int(statistics.mean(v for _, v in total_series)) if total_series else None
    month_avgs = [(r["month"], r["avg_balance"]) for r in monthly if r["avg_balance"] is not None]
    metrics["average_balance"] = {
        "key": "average_balance", "label": "Average daily balance", "unit": "paise", "value": avg_bal,
        "method": "mean end-of-day balance across all accounts on days every account is covered",
        "monthly": [{"month": m, "value": v} for m, v in month_avgs],
        "trend": round((month_avgs[-1][1] - month_avgs[0][1]) / month_avgs[0][1], 3) if len(month_avgs) >= 2 and month_avgs[0][1] else None,
        "included": [], "excluded": [], "months_used": [m for m, _ in month_avgs],
        "months_missing": [m for m in months if m not in dict(month_avgs)], "notes": []}

    balance_series = []
    for d, total in total_series:
        balance_series.append({"date": d.isoformat(), "total": total})
    per_account_series = {acct: [{"date": d.isoformat(), "balance": v} for d, v in sorted(ser.items())] for acct, ser in balances.items()}
    return {"months": months, "coverage": combined, "monthly": monthly, "metrics": metrics, "regular_outflows": regular,
            "balance_series": balance_series, "account_balance_series": per_account_series, "profile": profile}
