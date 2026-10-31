"""Narration normalisation: payment channel, counterparty and reference tokens."""
from __future__ import annotations

import re

from ..security.crypto import token

CHANNELS = [
    ("NACH", r"\bNACH\b"), ("ACH", r"\bACH\b"), ("ECS", r"\bECS\b"), ("UPI", r"\bUPI\b|REV-UPI"),
    ("IMPS", r"\bIMPS\b"), ("NEFT", r"\bNEFT\b"), ("RTGS", r"\bRTGS\b"), ("ATM", r"\bATM\b"),
    ("CASH", r"\bCASH\b"), ("BILLPAY", r"BILLPAY"), ("CARD", r"\bPOS\b|\bCRED\b"), ("CHQ", r"\bCHQ\b|CHEQUE|\bCLG\b"),
    ("BANK", r"INT\.?PD|INTEREST|CHGS|CHARGES"),
]
_STOP = {"NEFT", "IMPS", "UPI", "P2A", "P2M", "NACH", "DR", "CR", "ACH", "RTGS", "BILLPAY", "REV-UPI", "REV", "TO", "BY",
         "TRF", "INB", "MB", "ECS", "REFUND", "UPI SETTLEMENT", "ACH DR", "ACH DR RTN", "NACH DR", "ATM WDL", "CASH DEPOSIT"}


def channel(norm: str) -> str:
    for name, pat in CHANNELS:
        if re.search(pat, norm):
            return name
    return "OTHER"


def counterparty(norm: str) -> str:
    for part in re.split(r"[/|]", norm):
        p = re.sub(r"\s+", " ", part).strip(" -.:")
        if not p or p in _STOP:
            continue
        if "<HOLDER>" in p:
            return "<HOLDER>"
        if p.startswith("<") or sum(ch.isdigit() for ch in p) > len(p) / 2:
            continue
        if len(re.sub(r"[^A-Z]", "", p)) >= 3:
            return p
    return ""


def counterparty_key(cp: str) -> str:
    """Grouping key: drop digits, legal suffixes and month words so payroll 'SALARY JAN26' and 'FEB26' match."""
    k = re.sub(r"\d+", " ", cp)
    k = re.sub(r"\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|THE|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def ref_tokens(raw: str) -> list[str]:
    refs = set(re.findall(r"\b[A-Z]{0,4}\d{6,}\b", raw.upper()))
    return sorted(token(r, "ref") for r in refs)
