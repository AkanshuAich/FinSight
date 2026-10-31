"""Multilingual synthetic bank statements with category labels: English, Hindi (Devanagari and romanised
Hinglish), Gujarati and Tamil.

Indian statements keep payment-rail codes in English (UPI/NEFT/IMPS/NACH) while remarks, payee names and
some bank-printed narrations (cash withdrawal, interest) appear in the customer's language. This generator
mirrors that. Every transaction carries its true category, narration language and scenario tags.

Split discipline: 8 'dev' statements and 8 'test' statements. Test statements draw from different
phrasings (odd-indexed variants), payees and merchants than dev (even-indexed), so tuning on dev and
measuring on test is an honest held-out check.

  python datagen/multilingual.py            -> datasets/multilingual_v1/
"""
from __future__ import annotations

import csv
import json
import random
import shutil
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "datasets" / "multilingual_v1"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN"]
LANGS = ["en", "hi", "hi-Latn", "gu", "ta"]

# ---------------------------------------------------------------- lexicon: remark variants by category and language
LEX: dict[str, dict[str, list[str]]] = {
    "SALARY": {"en": ["SALARY {MON}", "SAL CREDIT {MON}", "PAYROLL {MON}", "MONTHLY SALARY"],
               "hi": ["वेतन {MON}", "माह का वेतन", "वेतन जमा", "मासिक वेतन"],
               "hi-Latn": ["SALARY {MON}", "PAGAR {MON}", "VETAN {MON}", "MAHINE KA PAGAR"],
               "gu": ["પગાર {MON}", "માસિક પગાર", "પગાર જમા", "મહિનાનો પગાર"],
               "ta": ["சம்பளம் {MON}", "மாத சம்பளம்", "சம்பள வரவு", "ஊதியம் {MON}"]},
    "PENSION": {"en": ["PENSION {MON}", "PENSION CREDIT"], "hi": ["पेंशन {MON}", "मासिक पेंशन"],
                "hi-Latn": ["PENSION {MON}", "PENSION JAMA"], "gu": ["પેન્શન {MON}", "માસિક પેન્શન"],
                "ta": ["ஓய்வூதியம் {MON}", "மாத ஓய்வூதியம்"]},
    "RENT": {"en": ["HOUSE RENT", "RENT {MON}", "FLAT RENT", "SHOP RENT"],
             "hi": ["मकान किराया", "किराया {MON}", "घर का किराया", "दुकान किराया"],
             "hi-Latn": ["MAKAN KIRAYA", "GHAR KIRAYA {MON}", "KIRAYA", "DUKAN BHADA"],
             "gu": ["ઘર ભાડું", "ભાડું {MON}", "મકાન ભાડું", "દુકાન ભાડું"],
             "ta": ["வீட்டு வாடகை", "வாடகை {MON}", "மாத வாடகை", "கடை வாடகை"]},
    "LOAN_EMI": {"en": ["EMI {MON}", "LOAN EMI", "INSTALMENT", "LOAN REPAYMENT"],
                 "hi": ["ऋण किस्त", "ईएमआई {MON}", "लोन की किस्त", "कर्ज़ किस्त"],
                 "hi-Latn": ["LOAN KISHT", "EMI {MON}", "KIST", "KARZ KI KIST"],
                 "gu": ["લોન હપ્તો", "ઈએમઆઈ {MON}", "હપ્તો", "લોન ચુકવણી"],
                 "ta": ["கடன் தவணை", "இஎம்ஐ {MON}", "மாத தவணை", "கடன் திருப்பம்"]},
    "UTILITIES": {"en": ["ELECTRICITY BILL", "MOBILE RECHARGE", "BROADBAND BILL", "WATER BILL"],
                  "hi": ["बिजली बिल", "मोबाइल रिचार्ज", "पानी का बिल", "गैस बिल"],
                  "hi-Latn": ["BIJLI BILL", "MOBILE RECHARGE", "PAANI BILL", "GAS CYLINDER"],
                  "gu": ["વીજળી બિલ", "મોબાઇલ રિચાર્જ", "ગેસ બિલ", "પાણી વેરો"],
                  "ta": ["மின் கட்டணம்", "மொபைல் ரீசார்ஜ்", "தண்ணீர் வரி", "எரிவாயு சிலிண்டர்"]},
    "CARD_PAYMENT": {"en": ["CC PAYMENT", "CREDIT CARD BILL"], "hi": ["क्रेडिट कार्ड भुगतान", "कार्ड बिल"],
                     "hi-Latn": ["CREDIT CARD BILL", "CARD KA BILL"], "gu": ["ક્રેડિટ કાર્ડ ચુકવણી", "કાર્ડ બિલ"],
                     "ta": ["கிரெடிட் கார்டு கட்டணம்", "அட்டை பில்"]},
    "INSURANCE": {"en": ["INSURANCE PREMIUM", "LIC PREMIUM"], "hi": ["बीमा प्रीमियम", "एलआईसी किस्त"],
                  "hi-Latn": ["BIMA PREMIUM", "LIC KIST"], "gu": ["વીમા પ્રીમિયમ", "એલઆઈસી પ્રીમિયમ"],
                  "ta": ["காப்பீட்டு பிரீமியம்", "எல்ஐசி பிரீமியம்"]},
    "INVESTMENT": {"en": ["MUTUAL FUND SIP", "SIP INVESTMENT"], "hi": ["म्यूचुअल फंड एसआईपी", "निवेश"],
                   "hi-Latn": ["SIP NIVESH", "MUTUAL FUND"], "gu": ["મ્યુચ્યુઅલ ફંડ એસઆઈપી", "રોકાણ"],
                   "ta": ["பரஸ்பர நிதி எஸ்ஐபி", "முதலீடு"]},
    "TAX": {"en": ["GST PAYMENT", "ADVANCE TAX"], "hi": ["जीएसटी भुगतान", "आयकर भुगतान"], "hi-Latn": ["GST BHUGTAN", "TAX BHARNA"],
            "gu": ["જીએસટી ચુકવણી", "આવકવેરો"], "ta": ["ஜிஎஸ்டி செலுத்துதல்", "வருமான வரி"]},
    "SUPPLIER_PAYMENT": {"en": ["STOCK PURCHASE", "PURCHASE ORDER", "RAW MATERIAL"], "hi": ["माल खरीद", "थोक माल भुगतान", "कच्चा माल"],
                         "hi-Latn": ["MAAL KHARID", "STOCK PAYMENT", "KACHCHA MAAL"], "gu": ["માલ ખરીદી", "જથ્થાબંધ માલ", "કાચો માલ"],
                         "ta": ["சரக்கு கொள்முதல்", "மொத்த சரக்கு", "மூலப்பொருள்"]},
    "PAYROLL_PAYMENT": {"en": ["STAFF SALARY", "WAGES"], "hi": ["कर्मचारी वेतन", "मज़दूरी"], "hi-Latn": ["STAFF PAGAR", "MAZDOORI"],
                        "gu": ["સ્ટાફ પગાર", "મજૂરી"], "ta": ["ஊழியர் சம்பளம்", "கூலி"]},
    "BUSINESS_RECEIPT": {"en": ["SALES", "INVOICE PAYMENT", "PAYMENT RECEIVED", "ORDER PAYMENT"],
                         "hi": ["बिक्री भुगतान", "माल बिक्री", "ग्राहक भुगतान", "बकाया भुगतान"],
                         "hi-Latn": ["BIKRI", "GRAHAK PAYMENT", "MAAL BIKRI", "BAKAYA"],
                         "gu": ["વેચાણ", "ગ્રાહક ચુકવણી", "માલ વેચાણ", "બાકી ચુકવણી"],
                         "ta": ["விற்பனை", "வாடிக்கையாளர் பணம்", "சரக்கு விற்பனை", "நிலுவை தொகை"]},
    "CASH_DEPOSIT": {"en": ["CASH DEPOSIT", "CASH DEP BY SELF"], "hi": ["नकद जमा", "नकदी जमा"], "hi-Latn": ["CASH JAMA", "NAKAD JAMA"],
                     "gu": ["રોકડ જમા", "રોકડ ભરણું"], "ta": ["ரொக்க வைப்பு", "பணம் செலுத்துதல்"]},
    "CASH_WITHDRAWAL": {"en": ["ATM WDL", "CASH WITHDRAWAL"], "hi": ["नकद आहरण", "एटीएम निकासी"], "hi-Latn": ["ATM NIKASI", "NAKAD NIKASI"],
                        "gu": ["રોકડ ઉપાડ", "એટીએમ ઉપાડ"], "ta": ["பணம் எடுத்தல்", "ஏடிஎம் பணம்"]},
    "INTEREST": {"en": ["SB INTEREST", "INT.PD"], "hi": ["ब्याज जमा", "बचत ब्याज"], "hi-Latn": ["BYAJ JAMA", "INTEREST JAMA"],
                 "gu": ["વ્યાજ જમા", "બચત વ્યાજ"], "ta": ["வட்டி வரவு", "சேமிப்பு வட்டி"]},
    "BANK_CHARGES": {"en": ["SMS CHGS", "MIN BAL CHGS"], "hi": ["एसएमएस शुल्क", "न्यूनतम शेष शुल्क"], "hi-Latn": ["SMS CHARGE", "MIN BALANCE CHARGE"],
                     "gu": ["એસએમએસ ચાર્જ", "ન્યૂનતમ બેલેન્સ ચાર્જ"], "ta": ["எஸ்எம்எஸ் கட்டணம்", "குறைந்தபட்ச இருப்பு கட்டணம்"]},
    "GENERAL_EXPENSE": {"en": ["GROCERY", "MEDICINE", "SCHOOL FEES", "VEGETABLES", "FUEL", "CLOTHES"],
                        "hi": ["किराना", "दवाई", "स्कूल फीस", "सब्ज़ी", "पेट्रोल", "कपड़े"],
                        "hi-Latn": ["KIRANA", "DAWAI", "SCHOOL FEES", "SABZI", "PETROL", "KAPDE"],
                        "gu": ["કરિયાણું", "દવા", "શાળા ફી", "શાકભાજી", "પેટ્રોલ", "કપડાં"],
                        "ta": ["மளிகை", "மருந்து", "பள்ளி கட்டணம்", "காய்கறி", "பெட்ரோல்", "துணிகள்"]},
    "INTERNAL_TRANSFER": {"en": ["SELF TRANSFER", "OWN ACCOUNT"], "hi": ["स्वयं खाते में", "अपने खाते में"], "hi-Latn": ["APNE KHATE ME", "SELF TRANSFER"],
                          "gu": ["પોતાના ખાતામાં", "સ્વ ટ્રાન્સફર"], "ta": ["சொந்த கணக்கிற்கு", "சுய பரிமாற்றம்"]},
    "REFUND": {"en": ["REFUND", "ORDER REFUND"], "hi": ["धनवापसी", "रिफंड"], "hi-Latn": ["REFUND", "PAISA WAPAS"],
               "gu": ["રિફંડ", "પૈસા પરત"], "ta": ["பணம் திரும்ப", "ரீஃபண்ட்"]},
    "LOAN_DISBURSAL": {"en": ["LOAN DISB"], "hi": ["ऋण वितरण"], "hi-Latn": ["LOAN DISBURSAL"], "gu": ["લોન વિતરણ"], "ta": ["கடன் வழங்கல்"]},
    "BOUNCE": {"en": ["RTN INSUFFICIENT FUNDS"], "hi": ["अपर्याप्त शेष वापसी"], "hi-Latn": ["RETURN BALANCE KAM"],
               "gu": ["અપૂરતું બેલેન્સ પરત"], "ta": ["போதிய இருப்பு இல்லை திருப்பம்"]},
    "BOUNCE_CHARGE": {"en": ["RTN CHGS"], "hi": ["वापसी शुल्क"], "hi-Latn": ["RETURN CHARGE"], "gu": ["પરત ચાર્જ"], "ta": ["திருப்ப கட்டணம்"]},
    "OTHER_CREDIT": {"en": ["DIVIDEND", "FD MATURITY"], "hi": ["लाभांश", "एफडी परिपक्वता"], "hi-Latn": ["DIVIDEND", "FD MATURITY"],
                     "gu": ["ડિવિડન્ડ", "એફડી પાકતી રકમ"], "ta": ["ஈவுத்தொகை", "வைப்பு முதிர்வு"]},
}

PEOPLE = {"en": ["RAHUL MEHTA", "PRIYA NAIR", "ANKIT JAIN", "NEHA KAPOOR", "VIKRAM SINGH", "SNEHA IYER"],
          "hi": ["सुरेश यादव", "अनीता शर्मा", "राज कुमार", "पूजा वर्मा", "मनोज तिवारी", "सीमा गुप्ता"],
          "hi-Latn": ["SURESH YADAV", "ANITA SHARMA", "RAJ KUMAR", "POOJA VERMA", "MANOJ TIWARI", "SEEMA GUPTA"],
          "gu": ["રમેશ પટેલ", "નીતા શાહ", "કિરણ દેસાઈ", "હેતલ મહેતા", "જયેશ પંડ્યા", "ભાવના જોષી"],
          "ta": ["முருகன் செல்வம்", "லக்ஷ்மி ராமன்", "கார்த்திக் சுப்பிரமணியன்", "மீனா சுந்தரம்", "ராஜேஷ் கண்ணன்", "பிரியா வேலு"]}
SHOPS = {"en": ["SAI GENERAL STORE", "CITY MEDICALS", "FRESH MART", "HP PETROL PUMP", "STAR TRADERS", "OM ENTERPRISES"],
         "hi": ["शर्मा किराना स्टोर", "गुप्ता मेडिकल", "जय माता दी स्टोर", "राम ट्रेडर्स", "श्री गणेश एजेंसी", "बालाजी किराना"],
         "hi-Latn": ["SHARMA KIRANA", "GUPTA MEDICAL", "JAI MATA DI STORE", "RAM TRADERS", "SHRI GANESH AGENCY", "BALAJI KIRANA"],
         "gu": ["પટેલ કરિયાણા", "શ્રીજી મેડિકલ", "અંબિકા સ્ટોર્સ", "જલારામ ટ્રેડર્સ", "ખોડિયાર એજન્સી", "ઉમિયા સ્ટોર"],
         "ta": ["முருகன் மளிகை", "சக்தி மருந்தகம்", "அண்ணாமலை ஸ்டோர்ஸ்", "வேல் டிரேடர்ஸ்", "ஸ்ரீ லட்சுமி ஏஜென்சி", "செல்வி ஸ்டோர்"]}
BILLERS = {"hi": "BSES", "hi-Latn": "BSES", "gu": "UGVCL", "ta": "TNEB", "en": "TATA POWER"}
LENDERS = [("BAJAJ FINANCE", {"hi": "बजाज फाइनेंस", "gu": "બજાજ ફાઇનાન્સ", "ta": "பஜாஜ் ஃபைனான்ஸ்"}),
           ("TATA CAPITAL", {"hi": "टाटा कैपिटल", "gu": "ટાટા કેપિટલ", "ta": "டாடா கேப்பிடல்"}),
           ("MUTHOOT FINANCE", {"hi": "मुथूट फाइनेंस", "gu": "મુથૂટ ફાઇનાન્સ", "ta": "முத்தூட் ஃபைனான்ஸ்"})]
CITIES = {"en": "MUMBAI", "hi": "लखनऊ", "hi-Latn": "LUCKNOW", "gu": "અમદાવાદ", "ta": "சென்னை"}
BANKS = ["NORTHWIND BANK", "MERIDIAN BANK", "DECCAN CO-OPERATIVE BANK", "COASTAL UNION BANK", "INDUS VALLEY BANK", "SAPTAGIRI GRAMIN BANK"]


@dataclass
class T:
    d: date
    desc: str
    debit: int
    credit: int
    category: str
    lang: str
    tags: list = field(default_factory=list)
    balance: int = 0
    seq: int = 0


class Gen:
    def __init__(self, seed: int, split: str, mix: dict[str, float]):
        self.r = random.Random(seed)
        self.split = split
        self.mix = mix
        self.txns: dict[str, list[T]] = {}

    def lang(self) -> str:
        x, acc = self.r.random(), 0.0
        for k, p in self.mix.items():
            acc += p
            if x <= acc:
                return k
        return list(self.mix)[-1]

    def pick(self, items: list[str]) -> str:
        """Dev draws even-indexed variants, test odd-indexed (when there is more than one)."""
        if len(items) == 1:
            return items[0]
        pool = items[0::2] if self.split == "dev" else items[1::2]
        return self.r.choice(pool)

    def remark(self, cat: str, lang: str, m: int) -> str:
        return self.pick(LEX[cat][lang]).replace("{MON}", f"{MONTHS[m]}26")

    def person(self, lang: str) -> str:
        return self.pick(PEOPLE[lang])

    def shop(self, lang: str) -> str:
        return self.pick(SHOPS[lang])

    def ref(self, n=12) -> str:
        return "".join(self.r.choice("0123456789") for _ in range(n))

    def add(self, acct: str, d: date, desc: str, *, dr=0.0, cr=0.0, cat: str, lang: str, tags=()):
        lst = self.txns.setdefault(acct, [])
        lst.append(T(d, desc, int(round(dr * 100)), int(round(cr * 100)), cat, lang, list(tags), seq=len(lst)))


def day(m: int, d: int) -> date:
    first = date(2026, m + 1, 1)
    nxt = date(2026, m + 2, 1)
    return first + timedelta(days=min(d, (nxt - first).days) - 1)


# ---------------------------------------------------------------- persona builders

def salaried(g: Gen, acct: str, *, employer: str, employer2: str | None, amount: float, payday: int, rent: float | None,
             emis: list, sip: float | None, card: bool, insurance: float | None, spends: int, salary_lang: str | None = None,
             pension=False, decline_from: int | None = None, missed: list[int] = (), bounce_month: int | None = None):
    for m in range(6):
        lang = salary_lang or g.lang()
        emp = employer2 if (employer2 and m >= 3) else employer
        amt = amount * (0.8 if decline_from is not None and m >= decline_from else 1.0) * (1 + g.r.uniform(-0.01, 0.01))
        cat_word = "PENSION" if pension else "SALARY"
        if m not in missed:
            ch = g.r.choice(["NEFT/CR", "NEFT"])
            g.add(acct, day(m, payday), f"{ch}/{g.ref(10)}/{emp}/{g.remark(cat_word, lang, m)}", cr=amt, cat="SALARY", lang=lang,
                  tags=["recurring"] + (["renamed_employer"] if employer2 and m >= 3 else []))
        if rent:
            lang = g.lang()
            g.add(acct, day(m, 5), f"IMPS/{g.ref()}/{g.person(lang)}/{g.remark('RENT', lang, m)}", dr=rent, cat="RENT", lang=lang, tags=["recurring"])
        for i, (lender_idx, emi, eday) in enumerate(emis):
            lang = g.lang()
            name, scripts = LENDERS[lender_idx]
            lname = scripts.get(lang, name) if g.r.random() < 0.35 else name
            desc = f"NACH/DR/{lname}/LN{4400 + lender_idx}{i}/{g.remark('LOAN_EMI', lang, m)}"
            if bounce_month is not None and m == bounce_month and i == 0:
                g.add(acct, day(m, eday), desc, dr=emi, cat="BOUNCE_RETURN", lang=lang, tags=["bounce"])
                g.add(acct, day(m, eday), f"NACH/{lname}/LN{4400 + lender_idx}{i}/{g.remark('BOUNCE', lang, m)}", cr=emi, cat="BOUNCE_RETURN",
                      lang=lang, tags=["bounce"])
                g.add(acct, day(m, eday + 1), f"{g.remark('BOUNCE_CHARGE', lang, m)}/NACH", dr=590, cat="BANK_CHARGES", lang=lang, tags=["bounce_charge"])
            else:
                g.add(acct, day(m, eday), desc, dr=emi, cat="LOAN_EMI", lang=lang, tags=["recurring"])
        if sip:
            lang = g.lang()
            g.add(acct, day(m, 10), f"ACH/DR/BSE STAR MF/{g.remark('INVESTMENT', lang, m)}", dr=sip, cat="INVESTMENT", lang=lang, tags=["recurring"])
        if insurance and m in (1, 4):
            lang = g.lang()
            g.add(acct, day(m, 18), f"UPI/DR/{g.ref()}/LIC/{g.remark('INSURANCE', lang, m)}", dr=insurance, cat="INSURANCE", lang=lang)
        if card:
            lang = g.lang()
            g.add(acct, day(m, 21), f"UPI/DR/{g.ref()}/CRED/{g.remark('CARD_PAYMENT', lang, m)}", dr=g.r.randint(6000, 24000), cat="CARD_PAYMENT", lang=lang)
        utility_bills(g, acct, m)
        daily_spends(g, acct, m, spends)
        atm(g, acct, m)
    interest(g, acct)


def utility_bills(g: Gen, acct: str, m: int):
    lang = g.lang()
    g.add(acct, day(m, 12), f"BILLPAY/{BILLERS[lang]}/{g.remark('UTILITIES', lang, m)}", dr=g.r.randint(600, 3200), cat="UTILITIES", lang=lang)
    lang = g.lang()
    g.add(acct, day(m, 16), f"UPI/DR/{g.ref()}/JIO/{g.remark('UTILITIES', lang, m)}", dr=g.r.choice([239, 299, 399, 666]), cat="UTILITIES", lang=lang)


def daily_spends(g: Gen, acct: str, m: int, n: int):
    for _ in range(n):
        lang = g.lang()
        payee = g.shop(lang) if g.r.random() < 0.6 else g.person(lang)
        g.add(acct, day(m, g.r.randint(1, 28)), f"UPI/DR/{g.ref()}/{payee}/{g.remark('GENERAL_EXPENSE', lang, m)}",
              dr=g.r.randint(120, 4800), cat="GENERAL_EXPENSE", lang=lang)


def atm(g: Gen, acct: str, m: int):
    lang = g.lang()
    g.add(acct, day(m, g.r.randint(6, 26)), f"{g.remark('CASH_WITHDRAWAL', lang, m)}/ATM {CITIES[lang]}", dr=g.r.choice([2000, 3000, 5000, 10000]),
          cat="CASH_WITHDRAWAL", lang=lang)


def interest(g: Gen, acct: str):
    for m in (2, 5):
        lang = g.lang()
        g.add(acct, day(m, 31), f"{g.remark('INTEREST', lang, m)}/Q{m // 3 + 1}", cr=g.r.randint(300, 2600), cat="INTEREST", lang=lang)
        lang = g.lang()
        g.add(acct, day(m, 31), f"{g.remark('BANK_CHARGES', lang, m)}/Q{m // 3 + 1}", dr=59, cat="BANK_CHARGES", lang=lang)


def business(g: Gen, acct: str, *, receipts: list[int], per_month: tuple[int, int], suppliers_share: float, rent: float | None,
             staff: int, gst: bool, cash_deps: int, emis: list, disb: tuple[int, float] | None = None, bounce_month: int | None = None,
             big_cash: tuple[int, float] | None = None):
    for m in range(6):
        remaining, k = receipts[m], 0
        lo, hi = per_month
        n = g.r.randint(lo, hi)
        for i in range(n):
            amt = remaining / (n - i) * g.r.uniform(0.6, 1.4) if i < n - 1 else remaining
            amt = max(200, min(amt, remaining))
            remaining -= amt
            lang = g.lang()
            payer = g.shop(lang) if g.r.random() < 0.7 else g.person(lang)
            rail = g.r.choice(["UPI/CR", "NEFT/CR", "IMPS"])
            g.add(acct, day(m, g.r.randint(1, 28)), f"{rail}/{g.ref()}/{payer}/{g.remark('BUSINESS_RECEIPT', lang, m)}", cr=amt,
                  cat="BUSINESS_RECEIPT", lang=lang)
            if remaining <= 1:
                break
        spend = receipts[m] * suppliers_share
        for j in range(3):
            lang = g.lang()
            g.add(acct, day(m, 6 + 7 * j), f"NEFT/DR/{g.ref(10)}/{g.shop(lang)}/{g.remark('SUPPLIER_PAYMENT', lang, m)}", dr=spend / 3,
                  cat="SUPPLIER_PAYMENT", lang=lang)
        for s in range(staff):
            lang = g.lang()
            g.add(acct, day(m, 2), f"IMPS/{g.ref()}/{g.person(lang)}/{g.remark('PAYROLL_PAYMENT', lang, m)}", dr=g.r.randint(9000, 16000),
                  cat="PAYROLL_PAYMENT", lang=lang)
        if rent:
            lang = g.lang()
            g.add(acct, day(m, 5), f"IMPS/{g.ref()}/{g.person(lang)}/{g.remark('RENT', lang, m)}", dr=rent, cat="RENT", lang=lang, tags=["recurring"])
        if gst:
            lang = g.lang()
            g.add(acct, day(m, 20), f"NEFT/DR/GSTN/CBIC/{g.remark('TAX', lang, m)}", dr=round(receipts[max(m - 1, 0)] * 0.03), cat="TAX", lang=lang)
        for _ in range(cash_deps):
            lang = g.lang()
            g.add(acct, day(m, g.r.randint(2, 27)), f"{g.remark('CASH_DEPOSIT', lang, m)}/BR {CITIES[lang]}", cr=g.r.randint(8000, 45000),
                  cat="CASH_DEPOSIT", lang=lang)
        for i, (lender_idx, emi, eday) in enumerate(emis):
            if disb and m <= disb[0]:
                continue
            lang = g.lang()
            name, scripts = LENDERS[lender_idx]
            lname = scripts.get(lang, name) if g.r.random() < 0.35 else name
            desc = f"NACH/DR/{lname}/BL{7700 + lender_idx}/{g.remark('LOAN_EMI', lang, m)}"
            if bounce_month == m:
                g.add(acct, day(m, eday), desc, dr=emi, cat="BOUNCE_RETURN", lang=lang, tags=["bounce"])
                g.add(acct, day(m, eday), f"NACH/{lname}/BL{7700 + lender_idx}/{g.remark('BOUNCE', lang, m)}", cr=emi, cat="BOUNCE_RETURN",
                      lang=lang, tags=["bounce"])
                g.add(acct, day(m, eday + 1), f"{g.remark('BOUNCE_CHARGE', lang, m)}/NACH", dr=590, cat="BANK_CHARGES", lang=lang, tags=["bounce_charge"])
            else:
                g.add(acct, day(m, eday), desc, dr=emi, cat="LOAN_EMI", lang=lang, tags=["recurring"])
        utility_bills(g, acct, m)
        daily_spends(g, acct, m, 4)
    if disb:
        lang = g.lang()
        name, scripts = LENDERS[1]
        g.add(acct, day(disb[0], 8), f"NEFT/CR/{g.ref(10)}/{name}/{g.remark('LOAN_DISBURSAL', lang, disb[0])}", cr=disb[1], cat="LOAN_DISBURSAL", lang=lang)
    if big_cash:
        lang = g.lang()
        g.add(acct, day(big_cash[0], 22), f"{g.remark('CASH_DEPOSIT', lang, big_cash[0])}/BR {CITIES[lang]}", cr=big_cash[1], cat="CASH_DEPOSIT",
              lang=lang, tags=["large_cash"])
    interest(g, acct)


def transfers(g: Gen, a: str, b: str, holder_by_lang: dict[str, str], amount: float, dday: int):
    """Own-account transfers: holder name in the narration's script, which may differ from the header's script."""
    for m in range(6):
        lang = g.lang()
        ref = g.ref()
        who = holder_by_lang.get(lang, holder_by_lang["en"])
        g.add(a, day(m, dday), f"IMPS/{ref}/{who}/{g.remark('INTERNAL_TRANSFER', lang, m)}", dr=amount, cat="INTERNAL_TRANSFER", lang=lang, tags=["transfer_pair"])
        g.add(b, day(m, dday), f"IMPS/{ref}/{who}/{g.remark('INTERNAL_TRANSFER', lang, m)}", cr=amount, cat="INTERNAL_TRANSFER", lang=lang, tags=["transfer_pair"])


def refunds(g: Gen, acct: str, n: int):
    for _ in range(n):
        m = g.r.randint(0, 5)
        lang = g.lang()
        amt = g.r.randint(500, 6000)
        ref = g.ref()
        merchant = g.r.choice(["AMAZON", "FLIPKART", "MYNTRA", "SWIGGY"])
        g.add(acct, day(m, 9), f"UPI/DR/{ref}/{merchant}/{g.remark('GENERAL_EXPENSE', lang, m)}", dr=amt, cat="REFUND_REVERSAL", lang=lang, tags=["reversal_pair"])
        g.add(acct, day(m, 13), f"UPI/CR/{ref}/{merchant}/{g.remark('REFUND', lang, m)}", cr=amt, cat="REFUND_REVERSAL", lang=lang, tags=["reversal_pair"])


def other_credit(g: Gen, acct: str):
    lang = g.lang()
    g.add(acct, day(g.r.randint(0, 5), 15), f"NEFT/CR/{g.ref(10)}/INFOSYS LTD/{g.remark('OTHER_CREDIT', lang, 0)}", cr=g.r.randint(800, 4000),
          cat="OTHER_CREDIT", lang=lang)


# ---------------------------------------------------------------- personas (16)
PERSONAS = [
    # id, split, name, holder scripts, profile, language mix, builder
    ("ml01", "dev", "Arjun Rao: IT engineer, Bengaluru", {"en": "ARJUN RAO", "hi-Latn": "ARJUN RAO"}, "SALARIED",
     {"en": 0.6, "hi-Latn": 0.25, "hi": 0.15}, "salaried_it"),
    ("ml02", "dev", "Hetal Shah: teacher, Ahmedabad", {"en": "HETAL SHAH", "gu": "હેતલ શાહ"}, "SALARIED", {"gu": 0.65, "en": 0.35}, "salaried_teacher"),
    ("ml03", "dev", "Ram Prasad Mishra: clerk, Lucknow", {"en": "RAM PRASAD MISHRA", "hi": "राम प्रसाद मिश्रा"}, "SALARIED",
     {"hi": 0.6, "hi-Latn": 0.2, "en": 0.2}, "salaried_clerk"),
    ("ml04", "dev", "Kavitha Raman: nurse, Chennai", {"en": "KAVITHA RAMAN", "ta": "கவிதா ராமன்"}, "SALARIED", {"ta": 0.65, "en": 0.35}, "salaried_nurse"),
    ("ml05", "dev", "Bhavesh Patel: kirana shop, Surat", {"en": "BHAVESH PATEL", "gu": "ભાવેશ પટેલ"}, "SELF_EMPLOYED", {"gu": 0.7, "en": 0.3}, "kirana"),
    ("ml06", "dev", "Selvam Textiles: trader, Coimbatore", {"en": "SELVAM TEXTILES", "ta": "செல்வம் டெக்ஸ்டைல்ஸ்"}, "SELF_EMPLOYED",
     {"ta": 0.55, "en": 0.45}, "textile_sme"),
    ("ml07", "dev", "Imran Khan: cab driver, Delhi", {"en": "IMRAN KHAN", "hi-Latn": "IMRAN KHAN", "hi": "इमरान खान"}, "SELF_EMPLOYED",
     {"hi-Latn": 0.45, "hi": 0.35, "en": 0.2}, "gig_driver"),
    ("ml08", "dev", "Mixed-script household, Mumbai", {"en": "NIKHIL DESAI", "gu": "નિખિલ દેસાઈ", "hi": "निखिल देसाई"}, "SALARIED",
     {"en": 0.25, "hi": 0.2, "hi-Latn": 0.2, "gu": 0.2, "ta": 0.15}, "mixed_household"),
    ("ml09", "test", "Pooja Iyer: analyst, Pune", {"en": "POOJA IYER"}, "SALARIED", {"en": 0.55, "hi-Latn": 0.3, "hi": 0.15}, "salaried_it"),
    ("ml10", "test", "Jignesh Mehta: bank officer, Rajkot", {"en": "JIGNESH MEHTA", "gu": "જીજ્ઞેશ મહેતા"}, "SALARIED",
     {"gu": 0.7, "en": 0.3}, "salaried_teacher"),
    ("ml11", "test", "Sunita Devi: pensioner, Varanasi", {"en": "SUNITA DEVI", "hi": "सुनीता देवी"}, "SALARIED", {"hi": 0.75, "en": 0.25}, "pensioner"),
    ("ml12", "test", "Dr. Senthil Kumar: clinic, Madurai", {"en": "SENTHIL KUMAR", "ta": "செந்தில் குமார்"}, "SELF_EMPLOYED",
     {"ta": 0.6, "en": 0.4}, "clinic"),
    ("ml13", "test", "Ambika Industries: manufacturer, Rajkot", {"en": "AMBIKA INDUSTRIES", "gu": "અંબિકા ઇન્ડસ્ટ્રીઝ"}, "SELF_EMPLOYED",
     {"gu": 0.6, "en": 0.4}, "manufacturer"),
    ("ml14", "test", "Murugan Agro: farm trader, Thanjavur", {"en": "MURUGAN AGRO", "ta": "முருகன் அக்ரோ"}, "SELF_EMPLOYED",
     {"ta": 0.75, "en": 0.25}, "agri"),
    ("ml15", "test", "Deepak Saini: stressed borrower, Jaipur", {"en": "DEEPAK SAINI", "hi": "दीपक सैनी", "hi-Latn": "DEEPAK SAINI"}, "SALARIED",
     {"hi": 0.4, "hi-Latn": 0.35, "en": 0.25}, "stressed"),
    ("ml16", "test", "Freelance designer, Indore", {"en": "AYESHA QURESHI", "hi": "आयशा कुरैशी"}, "SELF_EMPLOYED",
     {"hi": 0.35, "hi-Latn": 0.35, "en": 0.3}, "freelancer"),
]


def build(pid: str, split: str, holder: dict[str, str], kind: str, mix: dict[str, float], seed: int) -> tuple[Gen, list[str]]:
    g = Gen(seed, split, mix)
    A, B = f"{pid}-A", f"{pid}-B"
    accts = [A]
    if kind == "salaried_it":
        salaried(g, A, employer="INFOWAVE SYSTEMS PVT LTD", employer2="INFOWAVE TECH VIA RAZORPAYX", amount=128000, payday=1, rent=32000,
                 emis=[(0, 14200, 5)], sip=15000, card=True, insurance=9800, spends=9)
        refunds(g, A, 2)
        transfers(g, A, B, holder, 40000, 3)
        other_credit(g, B)
        interest(g, B)
        accts.append(B)
    elif kind == "salaried_teacher":
        salaried(g, A, employer="GSEB SCHOOL TRUST" if split == "dev" else "SAURASHTRA GRAMIN BANK", employer2=None, amount=48500, payday=1,
                 rent=11000, emis=[(2, 6100, 7)], sip=3000, card=False, insurance=5200, spends=8, salary_lang="gu")
        refunds(g, A, 1)
    elif kind == "salaried_clerk":
        salaried(g, A, employer="UP SECRETARIAT", employer2=None, amount=42000, payday=1, rent=9000, emis=[(0, 5400, 10)], sip=None, card=False,
                 insurance=4100, spends=8, salary_lang="hi")
    elif kind == "salaried_nurse":
        salaried(g, A, employer="APOLLO HOSPITALS", employer2="APOLLO HEALTH ENTERPRISE", amount=46500, payday=2, rent=12500, emis=[], sip=2000,
                 card=True, insurance=None, spends=8, salary_lang="ta")
        refunds(g, A, 1)
    elif kind == "pensioner":
        salaried(g, A, employer="SBI PENSION CPPC", employer2=None, amount=31000, payday=1, rent=None, emis=[], sip=None, card=False,
                 insurance=3800, spends=6, salary_lang="hi", pension=True)
        other_credit(g, A)
    elif kind == "stressed":
        salaried(g, A, employer="ROYAL MARBLES PVT LTD", employer2=None, amount=52000, payday=7, rent=14000, emis=[(0, 9800, 5), (2, 6200, 9)],
                 sip=None, card=True, insurance=None, spends=10, decline_from=3, missed=[5], bounce_month=4)
    elif kind == "mixed_household":
        salaried(g, A, employer="BLUE DART EXPRESS", employer2=None, amount=72000, payday=1, rent=26000, emis=[(1, 11800, 5)], sip=6000, card=True,
                 insurance=7200, spends=10)
        refunds(g, A, 2)
        transfers(g, A, B, holder, 25000, 4)
        interest(g, B)
        accts.append(B)
    elif kind == "kirana":
        business(g, A, receipts=[310000, 295000, 330000, 300000, 285000, 315000], per_month=(28, 40), suppliers_share=0.78, rent=18000, staff=1,
                 gst=False, cash_deps=6, emis=[(0, 8600, 10)])
    elif kind == "textile_sme":
        business(g, A, receipts=[820000, 760000, 840000, 610000, 520000, 470000], per_month=(18, 26), suppliers_share=0.74, rent=42000, staff=4,
                 gst=True, cash_deps=2, emis=[(1, 21500, 10)], disb=(1, 600000), bounce_month=4, big_cash=(4, 380000))
        transfers(g, A, B, holder, 50000, 3)
        interest(g, B)
        accts.append(B)
    elif kind == "gig_driver":
        business(g, A, receipts=[52000, 48000, 55000, 39000, 36000, 34000], per_month=(22, 30), suppliers_share=0.25, rent=7000, staff=0, gst=False,
                 cash_deps=1, emis=[(2, 4200, 12)])
    elif kind == "clinic":
        business(g, A, receipts=[420000, 455000, 410000, 470000, 440000, 460000], per_month=(30, 42), suppliers_share=0.30, rent=35000, staff=3,
                 gst=False, cash_deps=3, emis=[(0, 18400, 6)])
    elif kind == "manufacturer":
        business(g, A, receipts=[1450000, 1380000, 1520000, 1490000, 1300000, 1410000], per_month=(14, 22), suppliers_share=0.72, rent=None, staff=8,
                 gst=True, cash_deps=1, emis=[(1, 46000, 10)], big_cash=(5, 450000))
    elif kind == "agri":
        business(g, A, receipts=[680000, 120000, 90000, 610000, 140000, 80000], per_month=(6, 12), suppliers_share=0.55, rent=None, staff=2, gst=False,
                 cash_deps=4, emis=[(2, 12500, 15)], disb=(1, 250000))
    elif kind == "freelancer":
        business(g, A, receipts=[95000, 30000, 140000, 60000, 0, 120000], per_month=(1, 4), suppliers_share=0.05, rent=16000, staff=0, gst=False,
                 cash_deps=0, emis=[])
        refunds(g, A, 1)
    return g, accts


def finalize(lst: list[T], opening: int) -> None:
    lst.sort(key=lambda t: (t.d, t.seq))
    bal = opening
    for t in lst:
        bal += t.credit - t.debit
        t.balance = bal


def write_statement(path: Path, fmt: str, bank: str, holder: str, acct_no: str, lst: list[T], opening: int) -> None:
    start, end = date(2026, 1, 1), date(2026, 6, 30)
    closing = lst[-1].balance if lst else opening
    if fmt == "json":
        path.write_text(json.dumps({
            "bank_name": bank, "account_holder": holder, "account_number": acct_no, "account_type": "SAVINGS",
            "statement_period": {"from": start.isoformat(), "to": end.isoformat()}, "opening_balance": opening / 100, "closing_balance": closing / 100,
            "transactions": [{"date": t.d.isoformat(), "description": t.desc, "debit": t.debit / 100 or None, "credit": t.credit / 100 or None,
                              "balance": t.balance / 100} for t in lst]}, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    head = [[f"{bank} - Account Statement"], ["Account Name:", holder], ["Account Number:", acct_no], ["Account Type:", "SAVINGS"],
            ["Statement Period:", f"{start:%d-%m-%Y} to {end:%d-%m-%Y}"], ["Opening Balance:", f"{opening / 100:.2f}"],
            ["Closing Balance:", f"{closing / 100:.2f}"], [], ["Txn Date", "Narration", "Withdrawal", "Deposit", "Balance"]]
    body = [[f"{t.d:%d/%m/%Y}", t.desc, f"{t.debit / 100:.2f}" if t.debit else "", f"{t.credit / 100:.2f}" if t.credit else "", f"{t.balance / 100:.2f}"]
            for t in lst]
    if fmt == "csv":
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(head + body)
    else:
        wb = Workbook()
        ws = wb.active
        for r in head + body:
            ws.append(r)
        ws.column_dimensions["B"].width = 70
        wb.save(path)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    manifest, truth = [], []
    fmts = ["csv", "xlsx", "json"]
    for i, (pid, split, name, holder, profile, mix, kind) in enumerate(PERSONAS):
        g, accts = build(pid, split, holder, kind, mix, seed=1000 + i)
        files = []
        for j, acct in enumerate(accts):
            lst = g.txns.get(acct, [])
            opening = int(g.r.randint(60000, 400000) * 100) if kind not in ("stressed", "gig_driver") else int(g.r.randint(8000, 20000) * 100)
            finalize(lst, opening)
            acct_no = f"{3100000000 + i * 1000 + j * 7:d}{g.r.randint(10, 99)}"
            bank = BANKS[(i + j) % len(BANKS)]
            fmt = fmts[(i + j) % 3]
            fname = f"{pid}_{'primary' if j == 0 else 'second'}.{fmt}"
            write_statement(OUT / fname, fmt, bank, holder["en"], acct_no, lst, opening)
            files.append(fname)
            for t in lst:
                truth.append({"dataset": pid, "split": split, "file": fname, "account_number": acct_no, "date": t.d.isoformat(), "description": t.desc,
                              "debit": t.debit, "credit": t.credit, "category": t.category, "lang": t.lang, "tags": t.tags})
        income_cats = {"SALARY"} if profile == "SALARIED" else {"SALARY", "BUSINESS_RECEIPT"}
        monthly = [sum(t.credit for a in accts for t in g.txns.get(a, []) if t.category in income_cats and t.d.month == m + 1) for m in range(6)]
        tags = {tag for a in accts for t in g.txns.get(a, []) for tag in t.tags}
        expected_flags = sorted({"returned_payment" if "bounce" in tags else None, "large_cash_deposit" if "large_cash" in tags else None,
                                 "missed_salary" if kind == "stressed" else None,
                                 "income_decline" if kind in ("stressed", "textile_sme", "gig_driver") else None} - {None})
        manifest.append({"id": pid, "split": split, "name": name, "profile": profile, "languages": mix, "files": files,
                         "n_transactions": sum(len(g.txns.get(a, [])) for a in accts), "true_monthly_income": monthly,
                         "true_income_median": int(statistics.median(monthly)), "expected_flags": expected_flags})
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    with (OUT / "ground_truth.jsonl").open("w", encoding="utf-8") as f:
        for r in truth:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_lang, by_split = {}, {}
    for r in truth:
        by_lang[r["lang"]] = by_lang.get(r["lang"], 0) + 1
        by_split[r["split"]] = by_split.get(r["split"], 0) + 1
    print(f"{len(manifest)} datasets, {sum(len(m['files']) for m in manifest)} files, {len(truth)} labelled transactions -> {OUT}")
    print("by language:", by_lang, "| by split:", by_split)


if __name__ == "__main__":
    main()
