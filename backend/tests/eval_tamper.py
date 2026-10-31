"""Edit-risk evaluation: clean statements vs deliberately edited copies.

Attacks (each applied to every clean PDF):
  A editor_resave     re-saved by a PDF editor: Producer=iLovePDF, ModDate a few days after creation
  B incremental_save  saved again in place: an incremental revision appended to the original file
  C overlay_amount    an amount covered by a white box and retyped in the SAME font and size; metadata restored
  D stream_edit       one digit of an amount changed inside the page content; metadata restored

Flagged = edit-risk level medium or high. Uses the same detector and reconciliation as the upload path.

  python backend/tests/eval_tamper.py [--agami DIR] [--n 25] [--demo-out DIR]
"""
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pdfplumber  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.ingest import extract as ex  # noqa: E402
from app.money import fmt_inr  # noqa: E402
from app.validate import tamper  # noqa: E402
from app.validate.reconcile import reconcile_rows, statement_status  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
arg = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default  # noqa: E731
AGAMI = Path(arg("--agami", "C:/Users/AkanshuAich/Downloads/hf_indian_bank_statements/train"))
N = int(arg("--n", 25))
DEMO = arg("--demo-out", None)


def _orig_info(reader: PdfReader) -> dict:
    return {k: str(v) for k, v in (reader.metadata or {}).items()}


def _target_amount(data: bytes):
    """First amount inside the largest table on page 1: (text, x0, top, x1, bottom, font, size, page_height)."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = ex.drop_rotated_text(pdf.pages[0])
        tables = sorted(page.find_tables(), key=lambda t: (t.bbox[3] - t.bbox[1]) * (t.bbox[2] - t.bbox[0]), reverse=True)
        if not tables:
            return None
        x0, top, x1, bottom = tables[0].bbox
        for w in page.extract_words(extra_attrs=["fontname", "size"]):
            if tamper.AMOUNT.match(w["text"]) and x0 <= w["x0"] and w["x1"] <= x1 and top < w["top"] and w["bottom"] <= bottom:
                return w["text"], w["x0"], w["top"], w["x1"], w["bottom"], w["fontname"], w["size"], float(pdf.pages[0].height)
    return None


def _bump(text: str) -> str:
    """Change the first non-zero digit so the amount grows, keeping the same length."""
    for i, ch in enumerate(text):
        if ch.isdigit() and ch != "0":
            return text[:i] + str(min(9, int(ch) + 1) if ch != "9" else 8) + text[i + 1:]
    return text


def _write(writer: PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def attack_editor_resave(data: bytes) -> bytes:
    r = PdfReader(io.BytesIO(data))
    w = PdfWriter(clone_from=r)
    info = _orig_info(r)
    created = info.get("/CreationDate", "D:20240401100000+05'30'")
    m = re.match(r"D:(\d{8})", created)
    base = datetime.strptime(m.group(1), "%Y%m%d") if m else datetime(2024, 4, 1)
    later = f"D:{base + timedelta(days=3):%Y%m%d}120000+05'30'"
    w.add_metadata({**info, "/Producer": "iLovePDF", "/ModDate": later, "/CreationDate": created})
    return _write(w)


def attack_incremental(data: bytes) -> bytes:
    w = PdfWriter(io.BytesIO(data), incremental=True)
    w.add_metadata({"/Title": "Account Statement"})
    return _write(w)


def attack_overlay(data: bytes):
    tgt = _target_amount(data)
    if not tgt:
        return None
    text, x0, top, x1, bottom, font, size, height = tgt
    base_font = font.split("+")[-1]
    std = {"Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier"}
    base_font = base_font if base_font in std else "Helvetica"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(float(PdfReader(io.BytesIO(data)).pages[0].mediabox.width), height))
    c.setFillColorRGB(1, 1, 1)
    c.rect(x0 - 1, height - bottom - 1, (x1 - x0) + 2, (bottom - top) + 2, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont(base_font, size)
    c.drawString(x0, height - bottom + (bottom - top) * 0.2, _bump(text))
    c.save()
    r = PdfReader(io.BytesIO(data))
    w = PdfWriter(clone_from=r)
    w.pages[0].merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
    w.add_metadata(_orig_info(r))  # careful forger restores the original metadata
    return _write(w)


def attack_stream_edit(data: bytes):
    tgt = _target_amount(data)
    if not tgt:
        return None
    text = tgt[0]
    r = PdfReader(io.BytesIO(data))
    w = PdfWriter(clone_from=r)
    page = w.pages[0]
    contents = page.get_contents()
    raw = contents.get_data()
    needle = text.encode("latin-1")
    if needle not in raw:
        return None
    contents.set_data(raw.replace(needle, _bump(text).encode("latin-1"), 1))
    page.replace_contents(contents)
    w.add_metadata(_orig_info(r))
    return _write(w)


ATTACKS = {"A_editor_resave": attack_editor_resave, "B_incremental_save": attack_incremental,
           "C_overlay_amount": attack_overlay, "D_stream_edit": attack_stream_edit}


def assess(data: bytes) -> dict:
    signals = tamper.structure_signals(data)
    try:
        res = ex.extract_pdf(data)
        rows = sorted(res.rows, key=lambda x: (x.page_no, x.row_no))
        if rows:
            opening = res.meta.opening if res.meta.opening is not None else (rows[0].balance - rows[0].credit + rows[0].debit if rows[0].balance is not None else None)
            rs, summ = reconcile_rows(rows, opening)
            status, _, diff = statement_status(opening, res.meta.closing, summ["total_credits"], summ["total_debits"], summ["breaks"])
            signals += tamper.arithmetic_signals(status, diff, summ["breaks"], fmt_inr)
    except Exception as e:  # an unreadable edited file is itself suspicious, but record it separately
        signals.append({"code": "unreadable_after_edit", "weight": 0, "detail": str(e), "evidence": []})
    return tamper.summarise(signals)


sources = [("ours", p) for p in sorted((ROOT / "sample_data" / "case_salaried").glob("*.pdf")) if " (" not in p.name]
for t in ("Digital_Type1", "Digital_Type2"):
    d = AGAMI / f"India_Bank_Statement_{t}"
    if d.exists():
        sources += [("agami", p) for p in sorted(d.glob("*.pdf"))[:N]]

res = defaultdict(lambda: defaultdict(list))
examples = defaultdict(list)
for src, path in sources:
    clean = path.read_bytes()
    variants = {"clean": clean}
    for name, fn in ATTACKS.items():
        try:
            out = fn(clean)
        except Exception as e:
            out = None
            examples[f"{name}:build_error"].append(f"{path.name}: {type(e).__name__}: {e}")
        if out:
            variants[name] = out
        else:
            res[src][name + "_not_applicable"].append(1)
    for name, blob in variants.items():
        a = assess(blob)
        res[src][name].append(a)
        if DEMO and src == "ours" and name != "clean":
            Path(DEMO).mkdir(parents=True, exist_ok=True)
            (Path(DEMO) / f"{path.stem}__{name}.pdf").write_bytes(blob)
        if len(examples[f"{src}:{name}"]) < 2:
            examples[f"{src}:{name}"].append(f"{path.name}: {a['score']} {a['level']} {[s['code'] for s in a['signals']]}")
    print(f"done {src}/{path.name}", flush=True)

summary = {}
for src, by in res.items():
    for name, items in by.items():
        if name.endswith("_not_applicable"):
            summary[f"{src}:{name}"] = len(items)
            continue
        n = len(items)
        flagged = sum(a["level"] in ("medium", "high") for a in items)
        flagged_structure = sum(a["structure_score"] >= 30 for a in items)
        summary[f"{src}:{name}"] = {"n": n, "flagged_rate": round(flagged / n, 3), "flagged_by_structure_only_rate": round(flagged_structure / n, 3),
                                    "mean_score": round(sum(a["score"] for a in items) / n, 1),
                                    "levels": {lv: sum(a["level"] == lv for a in items) for lv in ("none", "low", "medium", "high")}}
summary["_examples"] = examples
out = Path(__file__).with_name("tamper_eval.json")
out.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
for k, v in summary.items():
    if k != "_examples":
        print(k, v)
print("written", out)
