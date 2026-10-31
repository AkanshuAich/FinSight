"""Layout understanding shared by every format: column roles and statement header fields."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..money import parse_date, to_paise

ROLE_PATTERNS = [
    ("value_date", r"value\s*d(ate|t)"),
    ("date", r"^(txn|tran|transaction|posting|post)?\s*\.?\s*date$|^date$|txn\s*date|tran\s*date|posted\s*date"),
    ("drcr", r"^(dr\s*/\s*cr|cr\s*/\s*dr|type|txn\s*type)$"),
    ("description", r"narration|description|particulars|details|remarks|transaction\s*details"),
    ("ref", r"chq|cheque|ref"),
    ("debit", r"withdrawal|debit|dr\s*amount|^dr$|paid\s*out"),
    ("credit", r"deposit|credit|cr\s*amount|^cr$|paid\s*in"),
    ("balance", r"balance"),
    ("amount", r"amount"),
]


def _clean(h) -> str:
    return re.sub(r"[^a-z/ ]", " ", str(h or "").lower()).strip()


def infer_roles(header: list) -> dict[str, int] | None:
    """Map column roles to indexes. Returns None if the row does not look like a transaction header."""
    roles: dict[str, int] = {}
    for i, h in enumerate(header):
        c = re.sub(r"\s+", " ", _clean(h))
        if not c:
            continue
        for role, pat in ROLE_PATTERNS:
            if role not in roles and re.search(pat, c):
                roles[role] = i
                break
    has_money = ("debit" in roles and "credit" in roles) or "amount" in roles
    if "date" in roles and "description" in roles and has_money:
        return roles
    return None


@dataclass
class Meta:
    bank_name: str | None = None
    holders: list[str] = field(default_factory=list)
    account_number: str | None = None
    account_type: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    opening: int | None = None
    closing: int | None = None


KV_PATTERNS = {
    "holder": r"(account\s*holder|customer\s*name|account\s*name|name\s*of\s*(the\s*)?customer)",
    "account_number": r"(account\s*(number|no)|a/c\s*(no|number))",
    "account_type": r"(account\s*type|a/c\s*type)",
    "period": r"(statement\s*period|period)",
    "opening": r"opening\s*balance",
    "closing": r"closing\s*balance",
}
_DATE_TOKEN = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[\s-][A-Za-z]{3,9}[\s-]\d{2,4}|\d{4}-\d{2}-\d{2})"
_AMT = r"(-?[\d,]+\.\d{2})"
_CUR = r"(?:Rs\.?|INR|₹)?\s*"


def clean_holder(v: str) -> str:
    v = re.sub(r"(?i)^(mr|mrs|ms|miss|dr|m/s)\.?\s+", "", v.strip())
    return re.sub(r"\s+", " ", v).strip().upper()


def parse_period(text: str) -> tuple[date | None, date | None]:
    m = re.search(_DATE_TOKEN + r"\s*(?:to|-|–|till)\s*" + _DATE_TOKEN, text, flags=re.I)
    if m:
        return parse_date(m.group(1)), parse_date(m.group(2))
    return None, None


def meta_from_pairs(pairs: list[tuple[str, str]], meta: Meta) -> Meta:
    for k, v in pairs:
        k_l, v = k.lower(), str(v).strip()
        if not v:
            continue
        if re.search(KV_PATTERNS["holder"], k_l):
            h = clean_holder(v)
            if h and h not in meta.holders:
                meta.holders.append(h)
        elif re.search(KV_PATTERNS["account_number"], k_l) and not meta.account_number:
            meta.account_number = re.sub(r"\D", "", v) or None
        elif re.search(KV_PATTERNS["account_type"], k_l):
            meta.account_type = v.upper()
        elif re.search(KV_PATTERNS["period"], k_l):
            meta.period_start, meta.period_end = parse_period(v)
        elif re.search(KV_PATTERNS["opening"], k_l) and meta.opening is None:
            meta.opening = to_paise(v)
        elif re.search(KV_PATTERNS["closing"], k_l) and meta.closing is None:
            meta.closing = to_paise(v)
    return meta


def meta_from_text(text: str, meta: Meta) -> Meta:
    """Header fields from free PDF text. Handles 'Key : value' lines and 'From X To Y' periods."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines and not meta.bank_name:
        meta.bank_name = lines[0].title() if lines[0].isupper() else lines[0]
    for line in lines[:40]:
        # labels with or without a colon: "Account Holder : X", "Account Holders Name X"
        for m in re.finditer(r"(Account Holders?(?: Name)?|Customer Name|Account Name)\s*:?\s+([A-Za-z .&]+?)(?=\s{2,}|$|\s+[A-Z][a-z/]+\s*(No|Number)\s*:)", line):
            h = clean_holder(m.group(2))
            if h and h not in meta.holders:
                meta.holders.append(h)
        m = re.search(r"(Account Number|A/c No|Account No)\.?\s*:?\s*(\d{6,20})", line, flags=re.I)
        if m and not meta.account_number:
            meta.account_number = m.group(2)
        m = re.search(r"Account Type\s*:?\s*([A-Za-z]+)", line, flags=re.I)
        if m:
            meta.account_type = m.group(1).upper()
        if meta.period_start is None and re.search(r"period|from", line, flags=re.I):
            meta.period_start, meta.period_end = parse_period(line)
        m = re.search(r"Opening Balance\s*:?\s*" + _CUR + _AMT, line, flags=re.I)
        if m and meta.opening is None:
            meta.opening = to_paise(m.group(1))
        m = re.search(r"Closing Balance\s*:?\s*" + _CUR + _AMT, line, flags=re.I)
        if m and meta.closing is None:
            meta.closing = to_paise(m.group(1))
    return meta


def meta_from_footer(text: str, meta: Meta) -> Meta:
    """Summary blocks at the end of a statement (Opening/Closing in a closing summary)."""
    for key in ("opening", "closing"):
        if getattr(meta, key) is None:
            m = re.search(rf"{key} Balance\s*:?\s*" + _CUR + _AMT, text, flags=re.I)
            if m:
                setattr(meta, key, to_paise(m.group(1)))
    return meta
