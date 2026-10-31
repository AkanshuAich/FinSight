"""Jev question bank behind a Classifier interface.

Jev is in early access and its API is not public, so the HTTP shape below is a placeholder to adapt
once access is granted. Until JEV_API_URL and JEV_API_KEY are set (and external models are allowed for
the deployment), the classifier is unavailable and fusion simply receives no Jev signals.
Every call goes through the egress gateway, answers are cached by (input, question bank, model) hash.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

from ..config import QUESTION_BANK_VERSION
from ..security import egress

QUESTIONS = {
    "q_payroll":   ("yes_no", "Does the narration indicate salary or payroll?", "SALARY"),
    "q_lender":    ("yes_no", "Is the counterparty a bank, NBFC or lender?", None),
    "q_reversal":  ("yes_no", "Does it indicate a reversal, return or refund?", "REFUND_REVERSAL"),
    "q_self":      ("yes_no", "Does the counterparty refer to <HOLDER> or their own account?", "INTERNAL_TRANSFER"),
    "q_cash":      ("yes_no", "Is this a cash deposit or withdrawal?", None),
    "q_loan_disb": ("yes_no", "Is this a loan disbursement?", "LOAN_DISBURSAL"),
    "q_business":  ("score",  "How likely is this a business or trade receipt? (0-10)", "BUSINESS_RECEIPT"),
}
WEIGHT = 0.6
_cache: dict[str, dict] = {}


def available() -> bool:
    return bool(os.environ.get("JEV_API_URL") and os.environ.get("JEV_API_KEY")) and egress.external_allowed()


def _transport(payload: dict) -> dict:
    import httpx
    r = httpx.post(os.environ["JEV_API_URL"], json=payload, headers={"Authorization": f"Bearer {os.environ['JEV_API_KEY']}"}, timeout=20)
    r.raise_for_status()
    return r.json()


def ask(masked_text: str, context: dict) -> dict[str, float]:
    key = hashlib.sha256(json.dumps([masked_text, context, QUESTION_BANK_VERSION, os.environ.get("JEV_MODEL", "jev")]).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    payload = {"text": json.dumps({"narration": masked_text, **context}),
               "questions": [{"id": k, "type": t, "question": q} for k, (t, q, _) in QUESTIONS.items()]}
    answers = egress.send("jev", payload, _transport)
    _cache[key] = {k: float(v) for k, v in answers.get("answers", {}).items()}
    return _cache[key]


def signals(answers: dict[str, float], direction: str) -> list[tuple[str, str, float, str]]:
    """(signal, category, contribution, detail) from calibrated probabilities as log-odds."""
    out = []
    for qid, p in answers.items():
        spec = QUESTIONS.get(qid)
        if not spec:
            continue
        kind, text, cat = spec
        if qid == "q_lender":
            cat = "LOAN_EMI" if direction == "D" else "LOAN_DISBURSAL"
        if qid == "q_cash":
            cat = "CASH_WITHDRAWAL" if direction == "D" else "CASH_DEPOSIT"
        prob = p / 10 if kind == "score" else p
        prob = min(max(prob, 0.01), 0.99)
        lo = math.log(prob / (1 - prob))
        if lo > 0 and cat:
            out.append((f"jev:{qid}", cat, WEIGHT * lo, f"{text} p={prob:.2f}"))
    return out
