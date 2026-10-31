"""Balance reconciliation at row, statement and cross-statement level.

Row chain: balance[i-1] + credit[i] - debit[i] must equal balance[i]. When one printed balance is wrong
but the next row continues from the computed value, it is reported as a single misprint rather than
two breaks. A jump that does not recover suggests missing rows and is reported as a gap.
"""
from __future__ import annotations

from ..money import fmt_inr


def reconcile_rows(rows: list, opening: int | None) -> tuple[list[tuple[str, str]], dict]:
    """rows have .debit .credit .balance. Returns per-row (status, note) and a summary."""
    out: list[tuple[str, str]] = []
    prev = opening
    breaks = 0
    for i, r in enumerate(rows):
        if r.balance is None:
            out.append(("unverified", "no running balance on statement"))
            prev = None
            continue
        if prev is None:
            out.append(("ok", "chain starts here"))
            prev = r.balance
            continue
        expected = prev + r.credit - r.debit
        if expected == r.balance:
            out.append(("ok", ""))
            prev = r.balance
            continue
        breaks += 1
        diff = r.balance - expected
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is not None and nxt.balance is not None and expected + nxt.credit - nxt.debit == nxt.balance:
            out.append(("break", f"printed balance differs from computed by {fmt_inr(diff)}; next row continues from the "
                                 f"computed balance, so this looks like a misprint on the statement"))
            prev = expected
        else:
            out.append(("break", f"balance jumps by {fmt_inr(diff)} versus the previous row; possible missing or misread transaction"))
            prev = r.balance
    total_cr = sum(r.credit for r in rows)
    total_dr = sum(r.debit for r in rows)
    return out, {"breaks": breaks, "total_credits": total_cr, "total_debits": total_dr}


def statement_status(opening: int | None, closing_stated: int | None, total_cr: int, total_dr: int, breaks: int) -> tuple[str, int | None, int | None]:
    if opening is None:
        return "unverified", None, None
    computed = opening + total_cr - total_dr
    if closing_stated is None:
        return ("reconciled_no_closing" if breaks == 0 else "breaks"), computed, None
    diff = closing_stated - computed
    if diff == 0 and breaks == 0:
        return "reconciled", computed, 0
    if diff == 0:
        return "reconciled_with_row_breaks", computed, 0
    return "unreconciled", computed, diff
