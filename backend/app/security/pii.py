"""Deterministic PII detection and masking for transaction narrations.

Two outputs per narration:
  display  what the analyst sees: identifiers masked to last 4, holder shown as [Holder]
  norm     what classifiers and external models see: placeholders such as <HOLDER>, <OWN_ACCT>, <UPI>
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}\b")
UPI = re.compile(r"\b[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}\b")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
AADHAAR_SPACED = re.compile(r"\b[2-9]\d{3}\s\d{4}\s\d{4}\b")
PHONE = re.compile(r"(?<![\d])(?:\+?91[\-\s]?)?[6-9]\d{9}(?![\d])")
LONG_NUM = re.compile(r"(?<![A-Za-z\d])[A-Za-z]?\d{9,19}(?![\d])")
CARD_SPACED = re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class Span:
    start: int
    end: int
    kind: str
    value: str


def detect(text: str, own_accounts: set[str] | None = None, holder_names: list[str] | None = None) -> list[Span]:
    """Find PII spans. Earlier detectors win over overlapping later ones."""
    own_accounts = own_accounts or set()
    spans: list[Span] = []

    def add(m, kind):
        s, e = m.start(), m.end()
        if any(not (e <= x.start or s >= x.end) for x in spans):
            return
        spans.append(Span(s, e, kind, m.group(0)))

    for name in sorted(holder_names or [], key=len, reverse=True):
        if len(name) >= 4:
            for m in re.finditer(re.escape(name), text, flags=re.I):
                add(m, "HOLDER")
    for m in EMAIL.finditer(text):
        add(m, "EMAIL")
    for m in UPI.finditer(text):
        add(m, "UPI")
    for m in PAN.finditer(text):
        add(m, "PAN")
    for m in AADHAAR_SPACED.finditer(text):
        add(m, "AADHAAR")
    for m in CARD_SPACED.finditer(text):
        if luhn_ok(re.sub(r"\D", "", m.group(0))):
            add(m, "CARD")
    for m in LONG_NUM.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if digits in own_accounts:
            add(m, "OWN_ACCT")
        elif PHONE.fullmatch(digits):
            add(m, "PHONE")
        elif len(digits) == 16 and luhn_ok(digits):
            add(m, "CARD")
        else:
            add(m, "NUM")
    for m in PHONE.finditer(text):
        add(m, "PHONE")
    return sorted(spans, key=lambda s: s.start)


def _mask_value(kind: str, v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if kind == "HOLDER":
        return "[Holder]"
    if kind in ("UPI", "EMAIL"):
        user, _, dom = v.partition("@")
        return f"{user[:1]}{'*' * max(len(user) - 1, 3)}@{dom}"
    if kind == "PAN":
        return "XXXXX" + v[5:9] + "X"
    if kind in ("OWN_ACCT", "NUM", "CARD", "AADHAAR", "PHONE"):
        return "X" * max(len(digits) - 4, 4) + digits[-4:]
    return "****"


PLACEHOLDER = {"HOLDER": "<HOLDER>", "OWN_ACCT": "<OWN_ACCT>", "UPI": "<UPI>", "EMAIL": "<EMAIL>", "PAN": "<PAN>",
               "AADHAAR": "<AADHAAR>", "CARD": "<CARD>", "PHONE": "<PHONE>", "NUM": "<NUM>"}


def render(text: str, spans: list[Span], mode: str) -> str:
    out, pos = [], 0
    for s in spans:
        out.append(text[pos:s.start])
        out.append(_mask_value(s.kind, s.value) if mode == "display" else PLACEHOLDER[s.kind])
        pos = s.end
    out.append(text[pos:])
    return "".join(out)


def mask(text: str, own_accounts: set[str] | None = None, holder_names: list[str] | None = None) -> tuple[str, str, list[Span]]:
    spans = detect(text, own_accounts, holder_names)
    return render(text, spans, "display"), render(text, spans, "norm").upper(), spans


def mask_account(acct: str) -> str:
    d = re.sub(r"\D", "", acct)
    return "X" * max(len(d) - 4, 4) + d[-4:] if d else "unknown"


def mask_name(name: str) -> str:
    return " ".join(w[:1] + "*" * (len(w) - 1) for w in name.split()) if name else ""


def residual_pii(text: str) -> list[str]:
    """Egress re-scan: anything still detectable after masking. Placeholders are ignored."""
    cleaned = re.sub(r"<[A-Z_0-9]+>", " ", text)
    return [s.kind for s in detect(cleaned) if s.kind != "NUM" or len(re.sub(r"\D", "", s.value)) >= 9]
