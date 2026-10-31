"""Synthetic bank statements with ground-truth labels.

Produces two demo cases covering every scenario in the problem statement:

  case_salaried  Rohan Malhotra: two PDF layouts (Northwind, Meridian), employer name change,
                 monthly own-account transfer, EMI, rent, refund and failed-UPI reversal,
                 overlapping statements, duplicate upload, missing month, a misprinted balance,
                 a large cash deposit and a round-figure inflow just before application.
  case_sme       Sri Lakshmi Traders (Kavya Iyer): CSV + XLSX current account (overlapping),
                 JSON savings account, irregular declining business receipts, loan disbursal,
                 EMI bounce, cash deposits, low balances.
  problem_files  A corrupted PDF and a scanned (image-only) PDF.

All names, banks and numbers are fictional. Run:  python datagen/generate.py
"""
from __future__ import annotations

import csv
import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN"]
rng = random.Random(42)


def rupees(x: float) -> int:
    """Rupees to integer paise."""
    return int(round(x * 100))


def inr(paise: int) -> str:
    """Indian digit grouping: 123456789 paise -> 12,34,567.89"""
    neg = paise < 0
    paise = abs(paise)
    r, p = divmod(paise, 100)
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-" if neg else "") + f"{s}.{p:02d}"


def ref(n: int = 12) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


@dataclass
class Txn:
    d: date
    desc: str
    debit: int = 0
    credit: int = 0
    category: str = ""
    ref: str = ""
    balance: int = 0
    seq: int = 0


@dataclass
class Ledger:
    account_number: str
    opening: int
    txns: list[Txn] = field(default_factory=list)

    def add(self, d: date, desc: str, *, dr: float = 0, cr: float = 0, cat: str, r: str = "") -> None:
        self.txns.append(Txn(d, desc, rupees(dr), rupees(cr), cat, r, seq=len(self.txns)))

    def finalize(self, capped: str | None = None) -> None:
        """Compute running balances. Debits in the `capped` category are reduced to what the
        account can afford, leaving a small buffer, the way a cash-tight business pays suppliers."""
        self.txns.sort(key=lambda t: (t.d, t.seq))
        bal = self.opening
        for t in self.txns:
            if capped and t.category == capped and bal - t.debit < rupees(2500):
                t.debit = max(0, bal - rupees(rng.randint(1200, 6000)))
            bal += t.credit - t.debit
            t.balance = bal
        self.txns = [t for t in self.txns if t.debit or t.credit]

    def balance_before(self, d: date) -> int:
        bal = self.opening
        for t in self.txns:
            if t.d >= d:
                break
            bal = t.balance
        return bal

    def between(self, a: date, b: date) -> list[Txn]:
        return [t for t in self.txns if a <= t.d <= b]


def day(m: int, d: int) -> date:
    """Month index 0..5 (Jan..Jun 2026), day clamped to month length."""
    first = date(2026, m + 1, 1)
    nxt = date(2026, m + 2, 1) if m < 11 else date(2027, 1, 1)
    return first + timedelta(days=min(d, (nxt - first).days) - 1)


def month_end(m: int) -> date:
    return day(m, 31)


# --------------------------------------------------------------------------- case 1: salaried

def build_salaried() -> tuple[Ledger, Ledger]:
    nw = Ledger("50100234567812", rupees(185000))
    mr = Ledger("917020045678", rupees(410000))
    merchants = [
        ("SWIGGY", "swiggy@icici", 150, 900), ("ZOMATO", "zomato@hdfcbank", 180, 1100),
        ("BIGBASKET", "bigbasket@axisbank", 800, 3500), ("UBER INDIA", "uber@hdfcbank", 180, 650),
        ("DMART", "dmart@ybl", 900, 4500), ("HPCL FUEL", "hpcl@sbi", 1500, 3000),
        ("AMAZON PAY", "amazon@apl", 300, 6000),
    ]
    for m, mon in enumerate(MONTHS):
        if m < 3:
            nw.add(day(m, 1), f"NEFT/ACME SOFTWARE PVT LTD/SALARY {mon}26/N{ref(10)}", cr=92500, cat="SALARY")
        else:  # employer renamed after payroll provider change: no salary keyword at all
            nw.add(day(m, 1), f"NEFT/ACME TECHNOLOGIES/RAZORPAYX/{mon}26/N{ref(10)}", cr=96200, cat="SALARY")
        t_ref = ref(12)
        nw.add(day(m, 2), f"IMPS/P2A/ROHAN MALHOTRA/MERIDIAN BANK/{t_ref}", cr=50000, cat="INTERNAL_TRANSFER")
        mr.add(day(m, 2), f"IMPS/P2A/TO ROHAN MALHOTRA/NORTHWIND 50100234567812/{t_ref}", dr=50000, cat="INTERNAL_TRANSFER")
        nw.add(day(m, 5), "NACH/DR/BAJAJ FINANCE LTD/LN00045821", dr=12450, cat="LOAN_EMI")
        nw.add(day(m, 7), f"IMPS/P2A/SUNITA KAPOOR/RENT {mon}/{ref(12)}", dr=24000, cat="RENT")
        nw.add(day(m, 10), "BSE STAR MF/SIP/ZERODHA COIN", dr=10000, cat="INVESTMENT")
        nw.add(day(m, 12), f"BILLPAY/BESCOM/ELEC/{ref(9)}", dr=rng.randint(1150, 2300), cat="UTILITIES")
        nw.add(day(m, 15), f"UPI/AIRTEL POSTPAID/airtel@ybl/{ref(12)}", dr=799, cat="UTILITIES")
        nw.add(day(m, 20), "CRED/CREDIT CARD BILL/HDFC XX4417", dr=rng.randint(14000, 29000), cat="CARD_PAYMENT")
        nw.add(day(m, 22), f"ATM WDL/NWB ATM KORAMANGALA/{ref(6)}", dr=rng.choice([5000, 10000]), cat="CASH_WITHDRAWAL")
        friend_phone = "98450" + ref(5)
        nw.add(day(m, rng.randint(8, 26)), f"UPI/ANKIT VERMA/{friend_phone}@ybl/DINNER SPLIT",
               dr=rng.randint(800, 2500), cat="GENERAL_EXPENSE")
        for _ in range(6):
            name, vpa, lo, hi = rng.choice(merchants)
            nw.add(day(m, rng.randint(3, 28)), f"UPI/{name}/{vpa}/{ref(12)}", dr=rng.randint(lo, hi),
                   cat="FOOD_DINING" if name in ("SWIGGY", "ZOMATO") else "GENERAL_EXPENSE")
        mr.add(day(m, 25), f"UPI/LIC OF INDIA/lic@sbi/PREMIUM {mon}", dr=3200, cat="INSURANCE")
    # quarterly interest
    for m in (2, 5):
        nw.add(month_end(m), f"INT.PD:{day(m-2,1):%d-%m-%Y} TO {month_end(m):%d-%m-%Y}", cr=rng.randint(1700, 2100), cat="INTEREST")
        mr.add(month_end(m), "SB INTEREST CREDIT", cr=rng.randint(2600, 3100), cat="INTEREST")
    # refund pair
    amz = ref(12)
    nw.add(date(2026, 2, 10), f"UPI/AMAZON PAY/amazon@apl/{amz}", dr=4599, cat="REFUND_REVERSAL")
    nw.add(date(2026, 2, 16), f"UPI/REFUND/AMAZON PAY/{amz}", cr=4599, cat="REFUND_REVERSAL")
    # failed UPI auto-reversed
    fk = ref(12)
    nw.add(date(2026, 5, 14), f"UPI/FLIPKART/flipkart@axisbank/{fk}", dr=2199, cat="REFUND_REVERSAL")
    nw.add(date(2026, 5, 14), f"REV-UPI/FLIPKART/{fk}/TXN FAILED", cr=2199, cat="REFUND_REVERSAL")
    # items for analyst review
    nw.add(date(2026, 6, 18), "CASH DEPOSIT/BR 0412 KORAMANGALA", cr=240000, cat="CASH_DEPOSIT")
    nw.add(date(2026, 6, 30), f"NEFT/RAKESH K SHARMA/N{ref(10)}", cr=100000, cat="OTHER_CREDIT")
    # meridian extras
    mr.add(date(2026, 1, 20), "NEFT/DIVIDEND/INFOSYS LTD/FY26 INTERIM", cr=1240, cat="OTHER_CREDIT")
    mr.add(date(2026, 4, 15), "FD MATURITY/FD NO 4471200/PROCEEDS", cr=150000, cat="OTHER_CREDIT")
    nw.finalize()
    mr.finalize()
    return nw, mr


# --------------------------------------------------------------------------- case 2: SME

def build_sme() -> tuple[Ledger, Ledger]:
    cur = Ledger("001234500987654", rupees(140000))
    sav = Ledger("3344556677", rupees(85000))
    customers = ["RAJESH GENERAL STORES", "ANAND ENTERPRISES", "GUPTA AGENCIES", "SV SUPERMARKET",
                 "MURUGAN PROVISIONS", "CITY MART", "NEW INDIA STORES", "PRIYA FOODS", "LAKSHMI BAKERY"]
    targets = [620000, 585000, 650000, 470000, 395000, 340000]
    suppliers = ["SHREE BALAJI WHOLESALE", "HINDUSTAN AGRO SUPPLIES", "ITC LTD DISTRIBUTOR", "VIJAY OIL MILLS"]
    staff = ["SURESH K", "MEENA R", "ARUN P"]
    for m, mon in enumerate(MONTHS):
        remaining = targets[m]
        while remaining > 3000:
            amt = min(remaining, rng.randint(4000, 85000))
            remaining -= amt
            cp = rng.choice(customers)
            style = rng.random()
            if style < 0.35:
                desc = f"NEFT/{cp}/INV{rng.randint(2100, 2999)}"
            elif style < 0.7:
                desc = f"UPI/{cp}/{cp.split()[0].lower()}{rng.randint(10,99)}@okaxis/{ref(12)}"
            elif style < 0.85:
                desc = f"IMPS/{cp}/{ref(12)}"
            else:
                desc = f"UPI SETTLEMENT/PAYTM/QR COLLECTION/{ref(8)}"
            cur.add(day(m, rng.randint(1, 28)), desc, cr=amt, cat="BUSINESS_RECEIPT")
        for s in staff:
            cur.add(day(m, 1), f"NEFT/SALARY/STAFF/{s}", dr=rng.randint(14000, 18000), cat="PAYROLL_PAYMENT")
        t_ref = ref(12)
        cur.add(day(m, 3), f"IMPS/KAVYA IYER/OWN SB AC/{t_ref}", dr=40000, cat="INTERNAL_TRANSFER")
        sav.add(day(m, 3), f"IMPS/SRI LAKSHMI TRADERS/OWN AC/{t_ref}", cr=40000, cat="INTERNAL_TRANSFER")
        cur.add(day(m, 5), f"IMPS/MANOJ REDDY/SHOP RENT {mon}/{ref(12)}", dr=35000, cat="RENT")
        cur.add(day(m, 14), f"BILLPAY/TNEB/{ref(10)}", dr=rng.randint(4000, 9000), cat="UTILITIES")
        cur.add(day(m, 20), f"GST PAYMENT/CBIC/CPIN{ref(14)}", dr=round(targets[max(m - 1, 0)] * 0.04), cat="TAX")
        for k in range(4):
            sp = suppliers[k % len(suppliers)]
            cur.add(day(m, 6 + k * 6 + rng.randint(0, 3)), f"NEFT/{sp}/PO{rng.randint(4400, 4999)}",
                    dr=rng.randint(125000, 150000), cat="SUPPLIER_PAYMENT")
        for _ in range(2):
            cur.add(day(m, rng.randint(2, 27)), "CASH DEPOSIT/SELF/BR 112 TNAGAR", cr=rng.randint(20000, 60000), cat="CASH_DEPOSIT")
        if m >= 2:
            cur.add(day(m, 10), "ACH DR/TATA CAPITAL FINANCIAL/BL0098812", dr=17850, cat="LOAN_EMI" if m != 4 else "BOUNCE_RETURN")
        # personal savings outflows
        sav.add(day(m, 6), f"UPI/MORE SUPERMARKET/more@ybl/{ref(12)}", dr=rng.randint(4000, 9000), cat="GENERAL_EXPENSE")
        sav.add(day(m, 12), "BSE STAR MF/SIP/GROWW", dr=5000, cat="INVESTMENT")
        sav.add(day(m, 18), f"UPI/APOLLO PHARMACY/apollo@hdfcbank/{ref(12)}", dr=rng.randint(600, 2400), cat="GENERAL_EXPENSE")
        sav.add(day(m, 24), f"ATM WDL/CUB ATM ADYAR/{ref(6)}", dr=rng.choice([3000, 5000]), cat="CASH_WITHDRAWAL")
    cur.add(date(2026, 2, 8), "NEFT/TATA CAPITAL FINANCIAL/LOAN DISB/BL0098812", cr=500000, cat="LOAN_DISBURSAL")
    cur.add(date(2026, 2, 12), "RTGS/HINDUSTAN AGRO SUPPLIES/BULK STOCK PO4391", dr=320000, cat="SUPPLIER_PAYMENT")
    cur.add(date(2026, 5, 10), "ACH DR RTN/TATA CAPITAL FINANCIAL/BL0098812/INSUFFICIENT FUNDS", cr=17850, cat="BOUNCE_RETURN")
    cur.add(date(2026, 5, 11), "ACH RTN CHARGES INCL GST", dr=590, cat="BANK_CHARGES")
    cur.add(date(2026, 5, 22), "CASH DEPOSIT/SELF/BR 112 TNAGAR", cr=350000, cat="CASH_DEPOSIT")
    for m in (2, 5):
        cur.add(month_end(m), "SMS ALERT CHGS QTR", dr=59, cat="BANK_CHARGES")
        sav.add(month_end(m), "SB INTEREST CREDIT", cr=rng.randint(600, 900), cat="INTEREST")
    sav.add(date(2026, 4, 8), "NEFT/VIDYA MANDIR SCHOOL/TERM FEES", dr=42000, cat="GENERAL_EXPENSE")
    cur.finalize(capped="SUPPLIER_PAYMENT")
    sav.finalize()
    return cur, sav


# --------------------------------------------------------------------------- writers

def pdf_northwind(path: Path, holder: str, acct: str, txns: list[Txn], start: date, end: date, opening: int) -> None:
    """Layout A: Date | Narration | Chq./Ref.No. | Value Dt | Withdrawal | Deposit | Closing Balance."""
    closing = txns[-1].balance if txns else opening
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=7.4, leading=9)
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#0b3d5c"))
    meta = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5, leading=12)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title="Northwind Bank Statement")
    story = [
        Paragraph("NORTHWIND BANK", head),
        Paragraph("Statement of Account", meta),
        Spacer(1, 4 * mm),
        Paragraph(f"Account Holder : {holder}<br/>Account Number : {acct}<br/>IFSC : NWBK0001234 &nbsp;&nbsp; Account Type : SAVINGS<br/>"
                  f"Statement Period : {start:%d/%m/%Y} to {end:%d/%m/%Y}<br/>"
                  f"Opening Balance : {inr(opening)} &nbsp;&nbsp; Closing Balance : {inr(closing)}", meta),
        Spacer(1, 4 * mm),
    ]
    rows = [["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]]
    for t in txns:
        rows.append([f"{t.d:%d/%m/%y}", Paragraph(t.desc, small), t.ref or "", f"{t.d:%d/%m/%y}",
                     inr(t.debit) if t.debit else "", inr(t.credit) if t.credit else "", inr(t.balance)])
    tbl = Table(rows, colWidths=[16 * mm, 66 * mm, 22 * mm, 16 * mm, 22 * mm, 22 * mm, 24 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.6), ("FONT", (0, 1), (-1, -1), "Helvetica", 7.4),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f0")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8aa3b5")),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("This is a computer generated statement and does not require a signature.", meta))

    def footer(c, d):
        c.setFont("Helvetica", 7)
        c.drawString(12 * mm, 8 * mm, f"Northwind Bank  |  A/c {acct[:4]}XXXXXX{acct[-4:]}  |  Page {d.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def pdf_meridian(path: Path, holder: str, acct: str, txns: list[Txn], start: date, end: date, opening: int,
                 misprint_row: int | None = None) -> None:
    """Layout B: Txn Date | Description | Amount (INR) | Dr/Cr | Balance (INR), summary block at the end."""
    small = ParagraphStyle("s", fontName="Times-Roman", fontSize=8, leading=9.5)
    head = ParagraphStyle("h", fontName="Times-Bold", fontSize=17, leading=20, textColor=colors.HexColor("#5a1f3c"))
    meta = ParagraphStyle("m", fontName="Times-Roman", fontSize=9.5, leading=12.5)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="Meridian Bank e-Statement")
    story = [
        Paragraph("Meridian Bank Ltd.", head),
        Paragraph("Consolidated e-Statement", meta), Spacer(1, 3 * mm),
        Paragraph(f"Customer Name: {holder}<br/>A/c No: {acct} &nbsp; | &nbsp; Branch: Indiranagar, Bengaluru<br/>"
                  f"From {start:%d %b %Y} To {end:%d %b %Y}", meta),
        Spacer(1, 4 * mm),
    ]
    rows = [["Txn Date", "Description", "Amount (INR)", "Dr/Cr", "Balance (INR)"]]
    tot_dr = tot_cr = 0
    for i, t in enumerate(txns):
        amt = t.debit or t.credit
        tot_dr += t.debit
        tot_cr += t.credit
        bal = t.balance + (rupees(1000) if misprint_row == i else 0)
        rows.append([f"{t.d:%d %b %Y}", Paragraph(t.desc, small), inr(amt), "Dr" if t.debit else "Cr", inr(bal)])
    tbl = Table(rows, colWidths=[24 * mm, 88 * mm, 26 * mm, 12 * mm, 30 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Times-Bold", 8.6), ("FONT", (0, 1), (-1, -1), "Times-Roman", 8.2),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#5a1f3c")), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8b3bd")),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"), ("ALIGN", (4, 1), (4, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 5 * mm))
    closing = txns[-1].balance if txns else opening
    story.append(Paragraph(f"<b>Account Summary</b><br/>Opening Balance: {inr(opening)}<br/>Total Debits: {inr(tot_dr)}<br/>"
                           f"Total Credits: {inr(tot_cr)}<br/>Closing Balance: {inr(closing)}", meta))
    doc.build(story)


def write_sme_csv(path: Path, led: Ledger, start: date, end: date) -> None:
    txns = led.between(start, end)
    opening = led.balance_before(start)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Deccan Co-operative Bank - Account Statement"])
        w.writerow(["Account Name:", "SRI LAKSHMI TRADERS"])
        w.writerow(["Customer Name:", "KAVYA IYER"])
        w.writerow(["Account Number:", led.account_number])
        w.writerow(["Account Type:", "CURRENT"])
        w.writerow(["Statement Period:", f"{start:%d-%m-%Y} to {end:%d-%m-%Y}"])
        w.writerow(["Opening Balance:", f"{opening / 100:.2f}"])
        w.writerow(["Closing Balance:", f"{txns[-1].balance / 100:.2f}"])
        w.writerow([])
        w.writerow(["Txn Date", "Value Date", "Particulars", "Cheque No", "Debit", "Credit", "Balance"])
        for t in txns:
            w.writerow([f"{t.d:%d-%m-%Y}", f"{t.d:%d-%m-%Y}", t.desc, "",
                        f"{t.debit / 100:.2f}" if t.debit else "", f"{t.credit / 100:.2f}" if t.credit else "", f"{t.balance / 100:.2f}"])


def write_sme_xlsx(path: Path, led: Ledger, start: date, end: date) -> None:
    txns = led.between(start, end)
    opening = led.balance_before(start)
    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    for r in [["Deccan Co-operative Bank - Account Statement"], ["Account Name:", "SRI LAKSHMI TRADERS"],
              ["Customer Name:", "KAVYA IYER"], ["Account Number:", led.account_number], ["Account Type:", "CURRENT"],
              ["Statement Period:", f"{start:%d-%m-%Y} to {end:%d-%m-%Y}"], ["Opening Balance:", opening / 100],
              ["Closing Balance:", txns[-1].balance / 100], [],
              ["Txn Date", "Value Date", "Particulars", "Cheque No", "Debit", "Credit", "Balance"]]:
        ws.append(r)
    for t in txns:
        ws.append([t.d, t.d, t.desc, None, t.debit / 100 if t.debit else None, t.credit / 100 if t.credit else None, t.balance / 100])
    for col in "AB":
        for cell in ws[col][10:]:
            cell.number_format = "DD-MM-YYYY"
    ws.column_dimensions["C"].width = 60
    wb.save(path)


def write_json(path: Path, led: Ledger, holder: str, bank: str, start: date, end: date) -> None:
    txns = led.between(start, end)
    payload = {
        "bank_name": bank, "account_holder": holder, "account_number": led.account_number, "account_type": "SAVINGS",
        "statement_period": {"from": start.isoformat(), "to": end.isoformat()},
        "opening_balance": led.balance_before(start) / 100, "closing_balance": txns[-1].balance / 100,
        "transactions": [{"date": t.d.isoformat(), "description": t.desc, "debit": t.debit / 100 or None,
                          "credit": t.credit / 100 or None, "balance": t.balance / 100} for t in txns],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def scanned_pdf(path: Path) -> None:
    """An image-only page: no text layer, must be reported as needing OCR."""
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFillColor(colors.HexColor("#f2efe6"))
    c.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#3a3a3a"))
    for i in range(40):  # strokes that look like scanned rows of text
        y = A4[1] - 60 - i * 18
        c.rect(40, y, rng.randint(250, 500), 6, fill=1, stroke=0)
    c.save()


def main() -> None:
    s1, s2, pf = OUT / "case_salaried", OUT / "case_sme", OUT / "problem_files"
    for p in (s1, s2, pf):  # only this generator's folders; sample_data/tampered belongs to eval_tamper.py
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
    truth: list[dict] = []

    def record(led: Ledger, a: date, b: date) -> None:
        for t in led.between(a, b):
            truth.append({"account_number": led.account_number, "date": t.d.isoformat(), "debit": t.debit, "credit": t.credit,
                          "description": t.desc, "category": t.category})

    nw, mr = build_salaried()
    q1s, q1e, mar1, jun30 = date(2026, 1, 1), date(2026, 3, 31), date(2026, 3, 1), date(2026, 6, 30)
    pdf_northwind(s1 / "northwind_jan-mar_2026.pdf", "ROHAN MALHOTRA", nw.account_number, nw.between(q1s, q1e), q1s, q1e, nw.opening)
    pdf_northwind(s1 / "northwind_mar-jun_2026.pdf", "ROHAN MALHOTRA", nw.account_number, nw.between(mar1, jun30), mar1, jun30,
                  nw.balance_before(mar1))
    shutil.copy(s1 / "northwind_jan-mar_2026.pdf", s1 / "northwind_jan-mar_2026 (1).pdf")  # duplicate upload
    feb28, apr1 = date(2026, 2, 28), date(2026, 4, 1)
    pdf_meridian(s1 / "meridian_jan-feb_2026.pdf", "Mr. Rohan Malhotra", mr.account_number, mr.between(q1s, feb28), q1s, feb28,
                 mr.opening, misprint_row=2)
    pdf_meridian(s1 / "meridian_apr-jun_2026.pdf", "Mr. Rohan Malhotra", mr.account_number, mr.between(apr1, jun30), apr1, jun30,
                 mr.balance_before(apr1))
    record(nw, q1s, jun30)
    record(mr, q1s, feb28)
    record(mr, apr1, jun30)

    cur, sav = build_sme()
    write_sme_csv(s2 / "deccan_current_jan-mar_2026.csv", cur, q1s, q1e)
    write_sme_xlsx(s2 / "deccan_current_mar-jun_2026.xlsx", cur, date(2026, 3, 16), jun30)
    write_json(s2 / "coastal_savings_jan-jun_2026.json", sav, "KAVYA IYER", "Coastal Union Bank", q1s, jun30)
    record(cur, q1s, jun30)
    record(sav, q1s, jun30)

    (pf / "corrupted_statement.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >>\ngarbage-without-xref\n")
    scanned_pdf(pf / "scanned_statement.pdf")

    meta = {
        "case_salaried": {"applicant": "Rohan Malhotra", "application_date": "2026-07-10", "profile": "SALARIED"},
        "case_sme": {"applicant": "Kavya Iyer (Sri Lakshmi Traders)", "application_date": "2026-07-08", "profile": "SELF_EMPLOYED"},
    }
    (OUT / "cases.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")

    for led, name in ((nw, "northwind"), (mr, "meridian"), (cur, "deccan current"), (sav, "coastal savings")):
        mins, nets = [], []
        for m in range(6):
            ts = [t for t in led.txns if t.d.month == m + 1]
            mins.append(inr(min(t.balance for t in ts)) if ts else "-")
            nets.append(round(sum(t.credit - t.debit for t in ts) / 1e7, 2))
        print(f"{name:16s} txns={len(led.txns):4d} closing={inr(led.txns[-1].balance):>14s}\n   min: {mins}\n   net (lakh): {nets}")
    print(f"ground truth rows: {len(truth)}  ->  {OUT}")


if __name__ == "__main__":
    main()
