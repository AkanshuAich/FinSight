"""Month coverage per account and continuity checks between consecutive statements.

A month with no statement is 'missing', never zero activity. Metrics use covered months only.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..money import fmt_inr


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_between(a: date, b: date) -> list[str]:
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def rebuild(con, case_id: str) -> None:
    con.execute("DELETE FROM silver.coverage WHERE case_id = ?", [case_id])
    con.execute("DELETE FROM silver.cross_checks WHERE case_id = ?", [case_id])
    stmts = con.execute("""SELECT statement_id, account_id, period_start, period_end, opening_paise, closing_stated, computed_closing
                           FROM silver.statements WHERE case_id = ? ORDER BY account_id, period_start, period_end""", [case_id]).fetchall()
    if not stmts:
        return
    window = months_between(min(s[2] for s in stmts), max(s[3] for s in stmts))
    by_acct: dict[str, list] = {}
    for s in stmts:
        by_acct.setdefault(s[1], []).append(s)
    for acct, ss in by_acct.items():
        covered: set[date] = set()
        for s in ss:
            d = s[2]
            while d <= s[3]:
                covered.add(d)
                d += timedelta(days=1)
        for mk in window:
            y, m = map(int, mk.split("-"))
            n = calendar.monthrange(y, m)[1]
            c = sum(1 for dd in range(1, n + 1) if date(y, m, dd) in covered)
            status = "full" if c == n else ("missing" if c == 0 else "partial")
            con.execute("INSERT INTO silver.coverage VALUES (?, ?, ?, ?, ?, ?)", [case_id, acct, mk, status, c, n])
        for prev, nxt in zip(ss, ss[1:]):
            p_id, n_id = prev[0], nxt[0]
            if nxt[2] > prev[3] + timedelta(days=1):
                con.execute("INSERT INTO silver.cross_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [case_id, acct, p_id, n_id, "gap", None, None, prev[3] + timedelta(days=1), nxt[2] - timedelta(days=1),
                             f"no statement covers {prev[3] + timedelta(days=1):%d %b %Y} to {nxt[2] - timedelta(days=1):%d %b %Y}"])
                continue
            # balance at the boundary according to the earlier statement
            row = con.execute("""SELECT t.balance FROM silver.txn_sources s JOIN silver.transactions t USING (txn_id)
                                 WHERE s.statement_id = ? AND t.txn_date < ? ORDER BY t.txn_date DESC, t.seq DESC LIMIT 1""",
                              [p_id, nxt[2]]).fetchone()
            expected = row[0] if row else prev[4]
            actual = nxt[4]
            if nxt[2] <= prev[3]:
                kind, detail = "overlap", f"statements overlap from {nxt[2]:%d %b %Y} to {min(prev[3], nxt[3]):%d %b %Y}; shared rows counted once"
            else:
                kind, detail = "continuous", "closing of the earlier statement carries into the next"
            if expected is not None and actual is not None and expected != actual:
                kind, detail = "balance_mismatch", f"opening {fmt_inr(actual)} does not match {fmt_inr(expected)} carried from the earlier statement"
            con.execute("INSERT INTO silver.cross_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [case_id, acct, p_id, n_id, kind, expected, actual, None, None, detail])
