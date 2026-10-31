"""Semantic memory: approved example narrations, matched by character n-gram similarity.

Global examples are seeded below (generic narrations, no customer data). Analyst corrections are
written as case-scoped examples. Promotion to global needs a senior reviewer.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..db import connect, q

SEED = {
    "SALARY": ["NEFT/INFOSYS LTD/SALARY", "SAL CREDIT/TCS LIMITED", "NEFT/WIPRO LTD/PAYROLL", "SALARY FOR THE MONTH OF"],
    "BUSINESS_RECEIPT": ["UPI/KIRANA STORE/PAYMENT RECEIVED", "NEFT/ABC TRADING CO/INVOICE", "IMPS/SHARMA ENTERPRISES/PAYMENT",
                         "UPI SETTLEMENT/PHONEPE/QR", "PAYU SETTLEMENT/MERCHANT"],
    "LOAN_EMI": ["NACH DR/HDFC BANK/LOAN EMI", "ECS/ICICI BANK/EMI", "ACH D/BAJAJ FINSERV/EMI"],
    "RENT": ["IMPS/LANDLORD/HOUSE RENT", "UPI/RENT PAYMENT/FLAT"],
    "UTILITIES": ["BILLPAY/TATA POWER/ELECTRICITY", "UPI/JIO RECHARGE", "BBPS/ELECTRICITY BILL", "BILLPAY/BROADBAND"],
    "CARD_PAYMENT": ["CC PAYMENT/SBI CARD", "CRED/AXIS BANK CREDIT CARD", "CREDIT CARD BILL PAYMENT"],
    "INSURANCE": ["LIC PREMIUM", "HDFC ERGO/POLICY PREMIUM", "STAR HEALTH/RENEWAL"],
    "INVESTMENT": ["SIP/HDFC MUTUAL FUND", "INDIAN CLEARING CORP/SIP", "ZERODHA/MF PURCHASE"],
    "TAX": ["GST PAYMENT/CBIC", "ADVANCE TAX/ITNS 280", "TDS PAYMENT"],
    "SUPPLIER_PAYMENT": ["NEFT/WHOLESALE DEPOT/PURCHASE ORDER", "RTGS/STEEL SUPPLIERS/PO"],
    "PAYROLL_PAYMENT": ["SALARY PAYMENT TO EMPLOYEES", "NEFT/STAFF WAGES"],
    "CASH_DEPOSIT": ["CASH DEPOSIT/BRANCH", "BY CASH/CDM DEPOSIT"],
    "CASH_WITHDRAWAL": ["ATM WDL/CASH", "NFS CASH WDL"],
    "INTEREST": ["INTEREST CREDIT", "SB INT PD"],
    "BANK_CHARGES": ["SMS CHARGES", "MIN BAL CHARGES", "DEBIT CARD ANNUAL FEE"],
    "FOOD_DINING": ["UPI/SWIGGY/FOOD", "UPI/ZOMATO/ORDER", "POS/RESTAURANT", "UPI/CAFE COFFEE DAY"],
    "GENERAL_EXPENSE": ["POS/RELIANCE SMART", "UPI/UBER/RIDE", "UPI/BIGBASKET/GROCERY", "UPI/AMAZON/SHOPPING", "UPI/PHARMACY"],
    "OTHER_CREDIT": ["DIVIDEND/ITC LTD", "FD MATURITY PROCEEDS", "MF REDEMPTION"],
    "INTERNAL_TRANSFER": ["IMPS/OWN ACCOUNT TRANSFER", "SELF TRANSFER TO SAVINGS"],
}


_BOILERPLATE = re.compile(r"\b(NEFT|IMPS|UPI|RTGS|P2A|P2M|NACH|ACH|ECS|DR|CR|MB|INB|TRF|TO|BY)\b")


def knn_text(norm: str) -> str:
    """Placeholders, digits and payment-rail words carry no category meaning; matching on them would let
    one remembered IMPS narration pull every other IMPS payment towards its category."""
    text = re.sub(r"<[A-Z_]+>|\d+", " ", norm or "")
    return re.sub(r"[\s/]+", " ", _BOILERPLATE.sub(" ", text)).strip()


def seed() -> None:
    """Idempotent: inserts the current seed examples and removes seed rows no longer in the list."""
    con = connect()
    ids = []
    for cat, texts in SEED.items():
        for t in texts:
            ex_id = "g_" + hashlib.sha256(f"{cat}|{t}".encode()).hexdigest()[:16]
            ids.append(ex_id)
            con.execute("INSERT OR IGNORE INTO knowledge.semantic_examples VALUES (?, 'global', NULL, ?, ?, 'seed', 'system', ?)",
                        [ex_id, t, cat, datetime(2026, 1, 1)])
    con.execute(f"DELETE FROM knowledge.semantic_examples WHERE source = 'seed' AND example_id NOT IN ({','.join('?' * len(ids))})", ids)


def add_case_example(con, case_id: str, norm: str, category: str, actor: str) -> None:
    text = knn_text(norm)
    if not text:
        return
    ex_id = "c_" + hashlib.sha256(f"{case_id}|{text}".encode()).hexdigest()[:16]
    con.execute("DELETE FROM knowledge.semantic_examples WHERE example_id = ?", [ex_id])
    con.execute("INSERT INTO knowledge.semantic_examples VALUES (?, 'case', ?, ?, ?, 'analyst_correction', ?, ?)",
                [ex_id, case_id, text, category, actor, datetime.utcnow()])


class Memory:
    def __init__(self, case_id: str):
        rows = q("""SELECT example_id, text_norm, category, scope FROM knowledge.semantic_examples
                    WHERE scope = 'global' OR case_id = ? ORDER BY example_id""", [case_id])
        rows = [dict(r, text_norm=knn_text(r["text_norm"])) for r in rows]
        self.rows = rows
        self.version = hashlib.sha256("|".join(f"{r['example_id']}:{r['category']}" for r in rows).encode()).hexdigest()[:12]
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=False)
        self.matrix = self.vec.fit_transform([r["text_norm"] for r in rows]) if rows else None

    def neighbours(self, texts: list[str], k: int = 5) -> list[list[tuple[dict, float]]]:
        if self.matrix is None or not texts:
            return [[] for _ in texts]
        sims = cosine_similarity(self.vec.transform(texts), self.matrix)
        out = []
        for row in sims:
            idx = row.argsort()[::-1][:k]
            out.append([(self.rows[i], float(row[i])) for i in idx if row[i] > 0])
        return out
