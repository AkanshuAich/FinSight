"""Money is integer paise everywhere. Floats never touch amounts."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_AMOUNT_RE = re.compile(r"^\(?-?[\d,]*\.?\d+\)?$")


def to_paise(value) -> int | None:
    """Parse '1,23,456.78', '1234.5', 1234.5 (from Excel), '(500.00)' or '' into paise."""
    if value is None:
        return None
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return value * 100
    if isinstance(value, float):
        return int((Decimal(repr(value)) * 100).quantize(Decimal(1)))
    s = re.sub(r"(?i)^(rs\.?|inr|₹)\s*", "", str(value).strip()).replace("₹", "").replace("INR", "").replace(" ", "")
    s = re.sub(r"(?i)(cr|dr)$", "", s)
    if s in ("", "-", "--", "nan", "None"):
        return None
    if not _AMOUNT_RE.match(s):
        raise ValueError(f"not an amount: {value!r}")
    neg = s.startswith("(") or s.startswith("-")
    s = s.strip("()-").replace(",", "")
    try:
        p = int((Decimal(s) * 100).quantize(Decimal(1)))
    except InvalidOperation as e:
        raise ValueError(f"not an amount: {value!r}") from e
    return -p if neg else p


def fmt_inr(paise: int | None) -> str:
    if paise is None:
        return "-"
    neg = paise < 0
    r, p = divmod(abs(paise), 100)
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'-' if neg else ''}₹{s}.{p:02d}"


_DATE_FORMATS = ["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d %b %y",
                 "%d-%b-%y", "%d.%m.%Y", "%d %B %Y", "%Y-%m-%d %H:%M:%S"]


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # a date followed by a time, possibly glued together by a cell wrap ("01-01-202411:30:55")
    for pat in _DATE_PREFIXES:
        m = pat.match(s)
        if m:
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(m.group(0), fmt).date()
                except ValueError:
                    continue
    return None


_DATE_PREFIXES = [re.compile(p) for p in (
    r"\d{4}-\d{2}-\d{2}", r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}", r"\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{4}",
    r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2}(?!\d)", r"\d{1,2}[ -][A-Za-z]{3}[ -]\d{2}(?!\d)")]
