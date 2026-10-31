"""Periodic memory: recurring monthly series per account.

Series are found by counterparty similarity first, then clusters with disjoint months, similar amounts
and the same day of month are merged. That merge is what keeps a salary recognisable when the employer
or payroll provider renames itself: the money still arrives on the same day for about the same amount.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from rapidfuzz import fuzz

from ..ingest.normalize import counterparty_key


@dataclass
class Series:
    pattern_id: str
    account_id: str
    direction: str
    txns: list = field(default_factory=list)  # dicts with txn_id, txn_date, amount, counterparty

    @property
    def months(self) -> list[str]:
        return sorted({f"{t['txn_date']:%Y-%m}" for t in self.txns})

    def monthly_amounts(self) -> list[int]:
        per: dict[str, int] = {}
        for t in self.txns:
            k = f"{t['txn_date']:%Y-%m}"
            per[k] = per.get(k, 0) + t["amount"]
        return [per[m] for m in sorted(per)]

    @property
    def median_amount(self) -> int:
        return int(statistics.median(self.monthly_amounts()))

    @property
    def cv(self) -> float:
        a = self.monthly_amounts()
        return statistics.pstdev(a) / statistics.mean(a) if len(a) > 1 and statistics.mean(a) else 0.0

    @property
    def typical_day(self) -> int:
        return int(statistics.median(t["txn_date"].day for t in self.txns))

    @property
    def counterparties(self) -> list[str]:
        return sorted({t["counterparty"] for t in self.txns if t["counterparty"]})

    def is_monthly(self) -> bool:
        m = self.months
        return len(m) >= 3 and len(self.txns) <= len(m) * 1.5


def _add_month(d: date, day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for dd in (day, 30, 29, 28):
        try:
            return date(y, m, dd)
        except ValueError:
            continue
    return d + timedelta(days=30)


def detect(account_id: str, txns: list[dict], full_months: set[str]) -> list[dict]:
    """txns: non-gated transactions of one account. Returns serialisable series with members."""
    out = []
    for direction in ("C", "D"):
        items = [t for t in txns if t["direction"] == direction and t["amount"] >= 500_00 and t["counterparty"]]
        clusters: list[Series] = []
        for t in sorted(items, key=lambda x: (x["txn_date"], x["txn_id"])):
            key = counterparty_key(t["counterparty"])
            for c in clusters:
                rep = counterparty_key(c.txns[0]["counterparty"])
                if key and rep and fuzz.token_set_ratio(key, rep) >= 88:
                    c.txns.append(t)
                    break
            else:
                clusters.append(Series(f"{account_id}:{direction}:{len(clusters)}", account_id, direction, [t]))
        # merge renamed counterparties: disjoint months, amount within 8%, same day of month (+-4)
        merged = True
        while merged:
            merged = False
            for i, a in enumerate(clusters):
                for b in clusters[i + 1:]:
                    # a series of 2+ months may absorb a single month worded differently ("ABC TECH PVT LTD SAL SEP")
                    if max(len(a.months), len(b.months)) < 2 or set(a.months) & set(b.months):
                        continue
                    if abs(a.median_amount - b.median_amount) > 0.08 * max(a.median_amount, b.median_amount):
                        continue
                    if abs(a.typical_day - b.typical_day) > 4:
                        continue
                    if len(a.txns) > len(a.months) * 1.5 or len(b.txns) > len(b.months) * 1.5:
                        continue
                    a.txns.extend(b.txns)
                    clusters.remove(b)
                    merged = True
                    break
                if merged:
                    break
        for s in clusters:
            if not s.is_monthly():
                continue
            months = s.months
            last = max(t["txn_date"] for t in s.txns)
            span = [m for m in sorted(full_months) if months[0] <= m]
            missed = [m for m in span if m not in months and m <= max(full_months)]
            out.append({
                "pattern_id": s.pattern_id, "account_id": account_id, "direction": direction,
                "counterparties": s.counterparties, "renamed": len({counterparty_key(c) for c in s.counterparties}) > 1,
                "median_amount": s.median_amount, "amount_cv": round(s.cv, 4), "typical_day": s.typical_day,
                "months": months, "missed_months": missed, "expected_next": _add_month(last, s.typical_day),
                "txn_ids": [t["txn_id"] for t in sorted(s.txns, key=lambda x: x["txn_date"])],
            })
    return out
