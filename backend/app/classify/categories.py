"""Category list with direction and metric treatment. A category without a treatment cannot be used."""

# treatment: income | obligation | expense | excluded | other_credit | review_credit
CATEGORIES = {
    "SALARY":            {"label": "Salary",              "dir": "C", "treatment": "income"},
    "BUSINESS_RECEIPT":  {"label": "Business receipt",    "dir": "C", "treatment": "income"},
    "INTERNAL_TRANSFER": {"label": "Internal transfer",   "dir": "B", "treatment": "excluded"},
    "REFUND_REVERSAL":   {"label": "Refund / reversal",   "dir": "B", "treatment": "excluded"},
    "LOAN_DISBURSAL":    {"label": "Loan disbursal",      "dir": "C", "treatment": "excluded"},
    "BOUNCE_RETURN":     {"label": "Bounced / returned",  "dir": "B", "treatment": "excluded"},
    "LOAN_EMI":          {"label": "Loan EMI",            "dir": "D", "treatment": "obligation"},
    "RENT":              {"label": "Rent",                "dir": "D", "treatment": "obligation"},
    "UTILITIES":         {"label": "Utilities",           "dir": "D", "treatment": "expense"},
    "CARD_PAYMENT":      {"label": "Credit card payment", "dir": "D", "treatment": "expense"},
    "INSURANCE":         {"label": "Insurance",           "dir": "D", "treatment": "expense"},
    "INVESTMENT":        {"label": "Investment / SIP",    "dir": "D", "treatment": "expense"},
    "TAX":               {"label": "Tax / GST",           "dir": "D", "treatment": "expense"},
    "SUPPLIER_PAYMENT":  {"label": "Supplier payment",    "dir": "D", "treatment": "expense"},
    "PAYROLL_PAYMENT":   {"label": "Staff salary paid",   "dir": "D", "treatment": "expense"},
    "CASH_WITHDRAWAL":   {"label": "Cash withdrawal",     "dir": "D", "treatment": "expense"},
    "BANK_CHARGES":      {"label": "Bank charges",        "dir": "D", "treatment": "expense"},
    "FOOD_DINING":       {"label": "Food & dining",       "dir": "D", "treatment": "expense"},
    "GENERAL_EXPENSE":   {"label": "General spending",    "dir": "D", "treatment": "expense"},
    "CASH_DEPOSIT":      {"label": "Cash deposit",        "dir": "C", "treatment": "review_credit"},
    "INTEREST":          {"label": "Interest",            "dir": "C", "treatment": "other_credit"},
    "OTHER_CREDIT":      {"label": "Other credit",        "dir": "C", "treatment": "other_credit"},
    "UNCLASSIFIED":      {"label": "Unclassified",        "dir": "B", "treatment": "other_credit"},
}

INCOME = {k for k, v in CATEGORIES.items() if v["treatment"] == "income"}
EXCLUDED = {k for k, v in CATEGORIES.items() if v["treatment"] == "excluded"}
OBLIGATIONS = {k for k, v in CATEGORIES.items() if v["treatment"] == "obligation"}
BASELINE = {"C": "OTHER_CREDIT", "D": "GENERAL_EXPENSE"}


def valid_for(direction: str) -> list[str]:
    return [k for k, v in CATEGORIES.items() if k != "UNCLASSIFIED" and v["dir"] in (direction, "B")]
