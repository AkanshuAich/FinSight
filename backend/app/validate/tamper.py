"""Edit risk: how likely it is that a statement file was changed after the bank produced it.

Deterministic, explained signals; the score is their weighted sum, capped at 100. Signals are reasons to
review, never a finding of fraud. A PDF library as producer is neutral: banks generate statements with them.

  structure signals  read from the file itself (producer, revisions, dates, fonts, overlapping text)
  arithmetic signals from reconciliation (statement totals, balance-chain breaks)
"""
from __future__ import annotations

import io
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pdfplumber

from ..ingest.extract import drop_rotated_text

EDITORS = r"ilovepdf|smallpdf|sejda|pdfescape|foxit|nitro|pdf-xchange|pdfelement|wondershare|canva|acrobat pro|acrobat dc|" \
          r"pdf expert|pdffiller|dochub|photoshop|gimp|inkscape|soda pdf|pdf24|pdfcandy|online2pdf"
OFFICE = r"microsoft.*(word|excel)|libreoffice|openoffice|wps office|google docs|pages|numbers"
AMOUNT = re.compile(r"^(rs\.?|inr|₹)?[\d,]+\.\d{2}(cr|dr)?$", re.I)

W = {"editor_producer": 35, "office_producer": 20, "incremental_update": 35, "modified_after_creation": 15,
     "font_mismatch": 30, "overlapping_text": 35, "unreconciled": 25, "balance_break": 10, "structured_source": 0}


def _pdf_date(s) -> datetime | None:
    if not s:
        return None
    s = str(s)
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Z+\-])?(\d{2})?'?(\d{2})?", s)
    if not m:
        return None
    y, mo, d, h, mi, se = (int(m.group(i) or default) for i, default in zip(range(1, 7), (0, 1, 1, 0, 0, 0)))
    tz = timezone.utc
    if m.group(7) in ("+", "-") and m.group(8):
        off = timedelta(hours=int(m.group(8)), minutes=int(m.group(9) or 0))
        tz = timezone(off if m.group(7) == "+" else -off)
    try:
        return datetime(y, mo, d, h, mi, se, tzinfo=tz)
    except ValueError:
        return None


def _signal(code: str, detail: str, evidence: list[str] | None = None, weight: int | None = None) -> dict:
    return {"code": code, "weight": W[code] if weight is None else weight, "detail": detail, "evidence": evidence or []}


def structure_signals(data: bytes, password: str | None = None) -> list[dict]:
    signals: list[dict] = []
    # ---- revisions: each save appends an %%EOF; a linearised file legitimately has two
    eofs = data.count(b"%%EOF")
    linearised = b"/Linearized" in data[:2048]
    revisions = eofs - (1 if linearised and eofs > 1 else 0)
    if revisions > 1:
        signals.append(_signal("incremental_update", f"The file was saved again after it was first produced ({revisions} revisions).",
                               [f"{eofs} end-of-file markers{' (linearised)' if linearised else ''}"]))
    try:
        pdf = pdfplumber.open(io.BytesIO(data), password=password or "")
    except Exception:
        return signals
    with pdf:
        meta = {k: str(v) for k, v in (pdf.metadata or {}).items()}
        prod = " / ".join(v for k, v in meta.items() if k in ("Producer", "Creator") and v and v != "(unspecified)")
        if re.search(EDITORS, prod, re.I):
            signals.append(_signal("editor_producer", "The file was produced or re-saved by PDF editing software.", [f"Producer/Creator: {prod}"]))
        elif re.search(OFFICE, prod, re.I):
            signals.append(_signal("office_producer", "The file was produced by an office application, not a bank's statement system.",
                                   [f"Producer/Creator: {prod}"]))
        created, modified = _pdf_date(meta.get("CreationDate")), _pdf_date(meta.get("ModDate"))
        if created and modified and modified - created > timedelta(minutes=2):
            gap = modified - created
            signals.append(_signal("modified_after_creation", "The file was modified after it was created.",
                                   [f"Created {created:%d %b %Y %H:%M}, modified {modified:%d %b %Y %H:%M} ({gap.days}d {gap.seconds // 3600}h later)"]))

        font_out, overlaps = [], []
        for pno, page in enumerate(pdf.pages[:30], start=1):
            chars = [c for c in page.chars if abs((c.get("matrix") or (1, 0, 0, 1))[1]) < 0.01 and abs((c.get("matrix") or (1, 0, 0, 1))[2]) < 0.01]
            # ---- text drawn over different text at the same spot (overlay edits leave the original underneath)
            grid: dict[tuple, list] = {}
            for c in chars:
                if c["text"].strip():
                    grid.setdefault((round(c["x0"]), round(c["top"])), []).append(c)
            for (x, y), cs in grid.items():
                texts = {c["text"] for c in cs}
                if len(texts) > 1 and len(overlaps) < 6:
                    overlaps.append(f"page {pno}: '{'/'.join(sorted(texts))}' printed on top of each other near x={x}, y={y}")
            # ---- amounts inside tables whose font or size differs from the rest of their column
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            if not tables:
                continue
            words = [w for w in drop_rotated_text(page).extract_words(extra_attrs=["fontname", "size"]) if AMOUNT.match(w["text"])]
            # compare within each table: summary boxes (opening/closing) legitimately use a larger size
            for t in tables:
                x0, top, x1, bottom = t.bbox
                in_table = [w for w in words if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and top - 1 <= w["top"] and w["bottom"] <= bottom + 1]
                if len(in_table) < 6:
                    continue
                dominant = Counter((w["fontname"], round(w["size"], 1)) for w in in_table).most_common(1)[0][0]
                for w in in_table:
                    if (w["fontname"], round(w["size"], 1)) != dominant and len(font_out) < 6:
                        font_out.append(f"page {pno}: {w['text']} in {w['fontname']} {round(w['size'], 1)}pt (rest of the table uses {dominant[0]} {dominant[1]}pt)")
        if font_out:
            signals.append(_signal("font_mismatch", "Some amounts in the transaction table use a different font or size from the rest.", font_out))
        if overlaps:
            signals.append(_signal("overlapping_text", "Text is printed over different text, as happens when a value is covered and retyped.", overlaps))
    return signals


def arithmetic_signals(recon_status: str | None, recon_diff: int | None, n_breaks: int, money) -> list[dict]:
    out = []
    if recon_status == "unreconciled":
        out.append(_signal("unreconciled", "Opening balance plus credits minus debits does not equal the stated closing balance.",
                           [f"difference {money(recon_diff)}"]))
    if n_breaks:
        out.append(_signal("balance_break", "The running balance does not follow from the amounts on some rows.",
                           [f"{n_breaks} row(s) break the balance chain"], weight=min(20, 10 * n_breaks)))
    return out


def summarise(signals: list[dict]) -> dict:
    score = min(100, sum(s["weight"] for s in signals))
    structure = min(100, sum(s["weight"] for s in signals if s["code"] not in ("unreconciled", "balance_break")))
    level = "high" if score >= 60 else "medium" if score >= 30 else "low" if score > 0 else "none"
    return {"score": score, "structure_score": structure, "level": level, "signals": sorted(signals, key=lambda s: -s["weight"])}
