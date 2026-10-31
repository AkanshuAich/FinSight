# Multilingual test datasets (`multilingual_v1`)

Synthetic, fictional bank statements for testing classification across languages. Regenerate with
`python datagen/multilingual.py`.

## Languages

| Code | Language | Example narration |
|---|---|---|
| `en` | English | `IMPS/…/RAHUL MEHTA/HOUSE RENT` |
| `hi` | Hindi, Devanagari | `IMPS/…/सुरेश यादव/मकान किराया` |
| `hi-Latn` | Hindi, romanised (Hinglish) | `IMPS/…/SURESH YADAV/MAKAN KIRAYA` |
| `gu` | Gujarati | `IMPS/…/રમેશ પટેલ/ઘર ભાડું` |
| `ta` | Tamil | `IMPS/…/முருகன் செல்வம்/வீட்டு வாடகை` |

Payment-rail codes (UPI, NEFT, IMPS, NACH) stay in English, as Indian banks print them. Remarks, payee names
and some bank-printed lines (cash withdrawal, interest, charges) are in the customer's language.

## The 16 statements

| ID | Split | Persona | Profile | Main languages | Scenarios |
|---|---|---|---|---|---|
| ml01 | dev | IT engineer, Bengaluru | Salaried | en, Hinglish, hi | Employer renamed, own-account transfers (2 accounts), refunds, EMI |
| ml02 | dev | Teacher, Ahmedabad | Salaried | gu, en | Gujarati salary, rent, EMI, refund |
| ml03 | dev | Clerk, Lucknow | Salaried | hi, Hinglish, en | Hindi salary, rent, EMI |
| ml04 | dev | Nurse, Chennai | Salaried | ta, en | Tamil salary, employer renamed, refund |
| ml05 | dev | Kirana shop, Surat | Self-employed | gu, en | Many small receipts, cash deposits, supplier payments |
| ml06 | dev | Textile trader, Coimbatore | Self-employed | ta, en | Loan disbursal, EMI bounce, large cash deposit, declining sales, 2 accounts |
| ml07 | dev | Cab driver, Delhi | Self-employed | Hinglish, hi, en | Daily receipts, declining income |
| ml08 | dev | Household, Mumbai | Salaried | all five | Mixed scripts in one statement, 2 accounts |
| ml09 | test | Analyst, Pune | Salaried | en, Hinglish, hi | As ml01 with different wording and payees |
| ml10 | test | Bank officer, Rajkot | Salaried | gu, en | Gujarati salary |
| ml11 | test | Pensioner, Varanasi | Salaried (pension) | hi, en | Pension labelled as SALARY (regular income) |
| ml12 | test | Clinic, Madurai | Self-employed | ta, en | Consultation receipts, staff wages |
| ml13 | test | Manufacturer, Rajkot | Self-employed | gu, en | Large supplier flows, GST, payroll, large cash deposit |
| ml14 | test | Farm trader, Thanjavur | Self-employed | ta, en | Seasonal income, crop loan disbursal |
| ml15 | test | Stressed borrower, Jaipur | Salaried | hi, Hinglish, en | Two EMIs, bounce, salary cut, missed salary |
| ml16 | test | Freelancer, Indore | Self-employed | hi, Hinglish, en | Irregular income with a zero month |

## Files

- `mlNN_primary.{csv,xlsx,json}` and `mlNN_second.*`: statements in the app's upload formats.
- `ground_truth.jsonl`: one row per transaction with `category`, `lang`, `split` and scenario `tags`.
- `manifest.json`: per statement, the profile, language mix, true monthly income and the flags that should fire.

## Held-out split

Dev statements use even-indexed phrasings from the generator's lexicon; test statements use odd-indexed ones,
with different payees, shops and employers. Tune rules or models on **dev** only and report accuracy on **test**.

## Known simplifications

- No PDFs: ReportLab cannot shape Indic scripts, so multilingual statements are CSV, Excel and JSON.
- Payee and remark come from one language per transaction; real narrations can mix more freely.
- Some deliberate ambiguity is realistic: Tamil கட்டணம் means both "fee" and "bill"; supplier payees can be shop names.
