"""The problem statement's own worked examples, run through the real pipeline with assertions.

  salaried    ₹60,000/60,000/60,000/62,000 salary with changing descriptions, rent, EMI, electricity, card, Swiggy,
              a ₹50,000 own-account transfer, an Amazon order and its refund, ₹5 lakh cash just before applying
  freelancer  ₹30,000/70,000/45,000/20,000 from a client: no single best month, a sustainable and a conservative figure
  stressed    falling salary, rising spending, several large unexplained credits, a returned EMI
"""
import os
import sys
import tempfile

os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_brief_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import analysis  # noqa: E402
from app.classify import semantic  # noqa: E402
from app.db import connect  # noqa: E402
from app.ingest import service as ingest  # noqa: E402
from app.metrics import effective  # noqa: E402

connect()
semantic.seed()


def statement(rows, opening, holder, acct):
    lines = ["Brief Bank - Account Statement", f"Account Name:,{holder}", f"Account Number:,{acct}",
             "Statement Period:,01-07-2026 to 31-12-2026" if any(r[0][3:5] == "12" for r in rows) else "Statement Period:,01-07-2026 to 31-10-2026",
             f"Opening Balance:,{opening:.2f}", "", "Date,Description,Debit,Credit,Balance"]
    bal = opening
    for d, desc, dr, cr in sorted(rows, key=lambda r: (r[0][3:5], r[0][:2])):
        bal += cr - dr
        lines.append(f"{d},{desc},{dr or ''},{cr or ''},{bal:.2f}")
    return "\n".join(lines).encode()


def run(case_id, name, data):
    connect().execute("INSERT INTO silver.cases VALUES (?, ?, DATE '2026-12-31', 'UNKNOWN', FALSE, NULL, now())", [case_id, name])
    ingest.upload(case_id, f"{case_id}.csv", data, actor="t", role="analyst")
    a = analysis.run(case_id, "t")
    cats = {}
    for t in effective.transactions(case_id):
        cats.setdefault(t["description"], (t["category"], t["status"]))
    return a, cats, {f["code"] for f in a["flags"]}


# ---------------------------------------------------------------- salaried
rows = []
for m, amt, desc in [(7, 60000, "NEFT/ABC TECHNOLOGIES SALARY"), (8, 60000, "NEFT/ABC TECHNOLOGIES SALARY"),
                     (9, 60000, "NEFT/ABC TECH PVT LTD SAL SEP"), (10, 62000, "NEFT/ABC TECHNOLOGIES LTD SALARY OCT")]:
    rows += [(f"01-{m:02d}-2026", desc, 0, amt), (f"03-{m:02d}-2026", "IMPS/RAMESH LANDLORD/HOUSE RENT", 12000, 0),
             (f"05-{m:02d}-2026", "UPI/BIGBAZAAR/GROCERY", 3000, 0), (f"10-{m:02d}-2026", "NACH/HDFC PERSONAL LOAN EMI", 8000, 0),
             (f"12-{m:02d}-2026", "BILLPAY/ELECTRICITY BILL", 1500, 0), (f"14-{m:02d}-2026", "UPI/SWIGGY", 500, 0),
             (f"20-{m:02d}-2026", "CREDIT CARD PAYMENT", 5000, 0), (f"22-{m:02d}-2026", "TRANSFER FROM OWN ACCOUNT/SAVINGS", 0, 50000),
             (f"23-{m:02d}-2026", "UPI/DMART/SHOPPING", 10000, 0)]
rows += [("18-09-2026", "UPI/AMAZON/ORDER", 2000, 0), ("21-09-2026", "UPI/AMAZON REFUND", 0, 2000), ("25-10-2026", "CASH DEPOSIT BRANCH", 0, 500000)]
a, cats, flags = run("c_sal", "Brief: salaried", statement(rows, 20000, "ASHA RAO", "11112222333"))
expect = {"NEFT/ABC TECHNOLOGIES SALARY": "SALARY", "NEFT/ABC TECH PVT LTD SAL SEP": "SALARY", "IMPS/RAMESH LANDLORD/HOUSE RENT": "RENT",
          "NACH/HDFC PERSONAL LOAN EMI": "LOAN_EMI", "BILLPAY/ELECTRICITY BILL": "UTILITIES", "UPI/SWIGGY": "FOOD_DINING",
          "CREDIT CARD PAYMENT": "CARD_PAYMENT", "TRANSFER FROM OWN ACCOUNT/SAVINGS": "INTERNAL_TRANSFER", "UPI/AMAZON REFUND": "REFUND_REVERSAL",
          "UPI/AMAZON/ORDER": "REFUND_REVERSAL", "CASH DEPOSIT BRANCH": "CASH_DEPOSIT"}
for desc, cat in expect.items():
    assert cats[desc][0] == cat, f"{desc}: got {cats[desc]}, want {cat}"
inc = a["metrics"]["estimated_income"]
assert inc["value"] == 60000_00 and inc["stats"]["mean"] == 60500_00, inc            # ₹50,000 transfers are not income
assert "missed_salary" not in flags, "September's differently worded salary must not count as missed"
assert "large_cash_deposit" in flags
sur = a["metrics"]["monthly_surplus"]
assert sur["outflows"] == 40000_00 and sur["value"] == 20000_00, (sur["outflows"], sur["value"])  # refund pair is not spending
print("salaried ok: income ₹60,000 (mean ₹60,500), outflows ₹40,000, surplus ₹20,000, flags", sorted(flags))

# ---------------------------------------------------------------- freelancer
rows = []
for m, amts in [(7, [30000]), (8, [45000, 25000]), (9, [45000]), (10, [20000])]:
    rows += [(f"{8 + i * 9:02d}-{m:02d}-2026", f"NEFT/CLIENT ABC PAYMENT/INV{m}{i}", 0, x) for i, x in enumerate(amts)]
    rows += [(f"05-{m:02d}-2026", "IMPS/HOUSE RENT", 9000, 0), (f"15-{m:02d}-2026", "UPI/SWIGGY", 800, 0)]
a, cats, flags = run("c_free", "Brief: freelancer", statement(rows, 15000, "VIVEK SEN", "44445555666"))
assert all(c == ("BUSINESS_RECEIPT", "auto") for d, c in cats.items() if "CLIENT" in d), cats
inc = a["metrics"]["estimated_income"]
assert inc["profile"] == "SELF_EMPLOYED" and inc["stats"]["highest"] == 70000_00
assert inc["value"] == 37500_00 and inc["stats"]["mean"] == 41250_00 and inc["stats"]["conservative"] == 27500_00, inc["stats"]
print("freelancer ok: sustainable (median) ₹37,500, average ₹41,250, conservative ₹27,500, never the ₹70,000 month")

# ---------------------------------------------------------------- stressed
rows = []
for i, m in enumerate(range(7, 13)):
    rows += [(f"01-{m:02d}-2026", "NEFT/XYZ LTD SALARY", 0, [60000, 60000, 55000, 48000, 42000, 40000][i]),
             (f"05-{m:02d}-2026", "IMPS/LANDLORD/HOUSE RENT", 12000, 0),
             (f"10-{m:02d}-2026", "NACH/BAJAJ FINANCE EMI", 9000, 0),
             (f"18-{m:02d}-2026", "UPI/DMART/SHOPPING", [8000, 9000, 15000, 22000, 28000, 34000][i], 0)]
rows += [("10-11-2026", "NACH RTN BAJAJ FINANCE EMI INSUFFICIENT FUNDS", 0, 9000), ("11-11-2026", "NACH RTN CHARGES", 590, 0),
         ("12-12-2026", "NEFT/UNKNOWN PARTY", 0, 150000), ("20-12-2026", "IMPS/SOMEONE", 0, 120000)]
a, cats, flags = run("c_stress", "Brief: stressed", statement(rows, 30000, "RAVI KUMAR", "77778888999"))
for code in ("income_decline", "rising_expenses", "multiple_large_credits", "returned_payment", "behaviour_change"):
    assert code in flags, f"missing flag {code}; got {sorted(flags)}"
print("stressed ok: flags", sorted(flags))
print("ALL BRIEF EXAMPLES PASSED")
