"""Upload pipeline: bronze -> silver.

  hash -> store encrypted -> extract (bronze pages, raw rows, quarantine)
       -> accounts + statement -> row reconciliation -> deterministic txn IDs (dedup) -> coverage

Every stage is idempotent: the same file in the same case returns the existing result, stage outputs
for a file are replaced inside one transaction, and transaction IDs are a function of their content.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from ..config import ALLOWED_EXTENSIONS, FILES_DIR, MAX_UPLOAD_BYTES, PIPELINE_VERSION
from ..db import connect, q, q1, tx
from ..dedup import coverage
from ..security import audit
from ..security.crypto import decrypt, encrypt, sha256, stable_id, vault_get, vault_put
from ..security.pii import mask, mask_account, mask_name
from ..money import fmt_inr
from ..validate import tamper
from ..validate.reconcile import reconcile_rows, statement_status
from . import extract as ex
from .normalize import channel, counterparty, ref_tokens


class UploadRejected(Exception):
    pass


def _case_context(con, case_id: str) -> tuple[set[str], list[str]]:
    """Clear account numbers and holder names for this case, read from the vault for masking."""
    accts, holders = set(), []
    for acct_tok, holder_tok in con.execute("SELECT acct_token, holder_token FROM silver.accounts WHERE case_id = ?", [case_id]).fetchall():
        v = vault_get(con, acct_tok) if acct_tok else None
        if v:
            accts.add(v)
        for h_tok in json.loads(holder_tok or "[]"):
            h = vault_get(con, h_tok)
            if h and h not in holders:
                holders.append(h)
    return accts, holders


def file_report(file_id: str) -> dict:
    f = q1("SELECT * FROM bronze.files WHERE file_id = ?", [file_id])
    if not f:
        return {}
    f["pages"] = q("SELECT page_no, status, reason, n_rows, method FROM bronze.pages WHERE file_id = ? ORDER BY page_no", [file_id])
    f["quarantine"] = q("SELECT page_no, row_no, kind, reason, detail FROM bronze.quarantine WHERE file_id = ? ORDER BY page_no, row_no", [file_id])
    f["statements"] = q("""SELECT s.*, a.acct_masked, a.bank_name FROM silver.statements s JOIN silver.accounts a USING (account_id)
                           WHERE s.file_id = ?""", [file_id])
    dc = q1("SELECT score, structure_score, level, signals FROM silver.document_checks WHERE file_id = ?", [file_id])
    f["edit_check"] = dict(dc, signals=json.loads(dc["signals"])) if dc else None
    return f


def upload(case_id: str, filename: str, data: bytes, *, actor: str, role: str, password: str | None = None) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"'{ext or 'no extension'}' files are not supported. Upload PDF, CSV, XLSX or JSON.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise UploadRejected("file is empty")
    sha = sha256(data)
    file_id = stable_id("f", case_id, sha)
    con = connect()
    existing = q1("SELECT status FROM bronze.files WHERE file_id = ?", [file_id])
    now = datetime.utcnow()
    if existing and not (existing["status"] == "needs_password" and password):
        con.execute("INSERT INTO bronze.upload_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [uuid.uuid4().hex, case_id, file_id, filename, True, now, actor])
        audit.record("file.duplicate_upload", actor=actor, role=role, case_id=case_id, target=file_id, details={"filename": filename})
        rep = file_report(file_id)
        rep["duplicate_upload"] = True
        return rep

    blob_path = FILES_DIR / f"{sha}.bin"
    if not blob_path.exists():
        blob_path.write_bytes(encrypt(data))
    kind = ex.detect_kind(filename, data)
    with tx() as c:
        c.execute("DELETE FROM bronze.files WHERE file_id = ?", [file_id])
        c.execute("INSERT INTO bronze.files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  [file_id, case_id, sha, filename, kind, len(data), "processing", None, now, None])
        if not existing:
            c.execute("INSERT INTO bronze.upload_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                      [uuid.uuid4().hex, case_id, file_id, filename, False, now, actor])
    audit.record("file.upload", actor=actor, role=role, case_id=case_id, target=file_id,
                 details={"filename": filename, "sha256": sha, "bytes": len(data), "kind": kind})
    process(case_id, file_id, password=password)
    return file_report(file_id)


def _fail(file_id: str, case_id: str, status: str, reason: str) -> None:
    with tx() as c:
        c.execute("UPDATE bronze.files SET status = ?, reason = ?, processed_at = ? WHERE file_id = ?",
                  [status, reason, datetime.utcnow(), file_id])
        c.execute("DELETE FROM bronze.quarantine WHERE file_id = ?", [file_id])
        c.execute("INSERT INTO bronze.quarantine VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  [stable_id("q", file_id, "file"), case_id, file_id, None, None, "file_" + status, reason, None])


def process(case_id: str, file_id: str, password: str | None = None) -> None:
    con = connect()
    f = q1("SELECT * FROM bronze.files WHERE file_id = ?", [file_id])
    data = decrypt((FILES_DIR / f"{f['sha256']}.bin").read_bytes())
    kind = f["kind"]
    try:
        if kind == "pdf":
            result = ex.extract_pdf(data, password)
        elif kind in ex.EXTRACTORS:
            result = ex.EXTRACTORS[kind](data)
        else:
            return _fail(file_id, case_id, "failed", "file content does not match a supported format (PDF, CSV, XLSX, JSON)")
    except ex.NeedsPassword:
        return _fail(file_id, case_id, "needs_password",
                     "PDF is password protected. Upload again with the password; it is used once and never stored.")
    except ex.Unreadable as e:
        return _fail(file_id, case_id, "failed", str(e))

    if kind == "pdf":
        doc_signals = tamper.structure_signals(data, password)
    else:
        doc_signals = [{"code": "structured_source", "weight": 0, "evidence": [f"{kind.upper()} file"],
                        "detail": "Spreadsheet and JSON files carry no bank-issued structure to verify; prefer the bank's PDF or an Account Aggregator feed."}]
    arith_signals: list[dict] = []
    meta = result.meta
    rows = sorted(result.rows, key=lambda r: (r.page_no, r.row_no))
    quarantine = list(result.quarantine)
    if not meta.account_number and rows:
        quarantine.append({"page_no": None, "row_no": None, "kind": "missing_account_number",
                           "reason": "account number not found in the statement header; transactions are kept under an unidentified account",
                           "detail": None})

    with tx() as c:
        # ---- bronze: replace this file's stage output
        for t in ("bronze.pages", "bronze.raw_rows", "bronze.quarantine"):
            c.execute(f"DELETE FROM {t} WHERE file_id = ?", [file_id])
        for p in result.pages:
            c.execute("INSERT INTO bronze.pages VALUES (?, ?, ?, ?, ?, ?)", [file_id, p.page_no, p.status, p.reason, p.n_rows, p.method])
        for r in rows:
            c.execute("INSERT OR IGNORE INTO bronze.raw_rows VALUES (?, ?, ?, ?)",
                      [file_id, r.page_no, r.row_no, encrypt(json.dumps(r.cells, default=str).encode())])
        for qq in quarantine:
            c.execute("INSERT INTO bronze.quarantine VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      [stable_id("q", file_id, qq["page_no"], qq["row_no"], qq["kind"]), case_id, file_id, qq["page_no"],
                       qq["row_no"], qq["kind"], qq["reason"], qq["detail"]])

        # remove this file's earlier statement and sources before re-inserting (re-processing is idempotent)
        old = [s[0] for s in c.execute("SELECT statement_id FROM silver.statements WHERE file_id = ?", [file_id]).fetchall()]
        for sid in old:
            c.execute("DELETE FROM silver.txn_sources WHERE statement_id = ?", [sid])
            c.execute("DELETE FROM silver.statements WHERE statement_id = ?", [sid])
        c.execute("""DELETE FROM silver.transactions WHERE case_id = ? AND txn_id NOT IN (SELECT txn_id FROM silver.txn_sources)""", [case_id])

        if rows:
            # ---- silver: account (only for files that yielded transactions)
            acct_clear = meta.account_number or f"UNIDENTIFIED-{file_id[-6:]}"
            acct_tok = vault_put(c, acct_clear, "acct")
            account_id = stable_id("a", case_id, acct_tok)
            holder_toks = [vault_put(c, h, "name") for h in meta.holders]
            row = c.execute("SELECT holder_token FROM silver.accounts WHERE account_id = ?", [account_id]).fetchone()
            if row:
                merged = sorted(set(json.loads(row[0] or "[]")) | set(holder_toks))
                c.execute("UPDATE silver.accounts SET holder_token = ?, bank_name = COALESCE(bank_name, ?) WHERE account_id = ?",
                          [json.dumps(merged), meta.bank_name, account_id])
            else:
                c.execute("INSERT INTO silver.accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          [account_id, case_id, acct_tok, mask_account(acct_clear) if meta.account_number else "unidentified",
                           meta.bank_name or "Unknown bank", json.dumps(sorted(holder_toks)), ", ".join(mask_name(h) for h in meta.holders),
                           meta.account_type])

            dates = [r.date for r in rows]
            p_start, p_end = meta.period_start or min(dates), meta.period_end or max(dates)
            opening, opening_src = meta.opening, "stated"
            if opening is None and rows[0].balance is not None:
                opening, opening_src = rows[0].balance - rows[0].credit + rows[0].debit, "derived"
            row_status, summ = reconcile_rows(rows, opening)
            status, computed, diff = statement_status(opening, meta.closing, summ["total_credits"], summ["total_debits"], summ["breaks"])
            arith_signals = tamper.arithmetic_signals(status, diff, summ["breaks"], fmt_inr)
            statement_id = stable_id("s", file_id, acct_tok, p_start, p_end)
            c.execute("INSERT INTO silver.statements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      [statement_id, case_id, file_id, account_id, result.layout, p_start, p_end, opening, opening_src, meta.closing,
                       computed, summ["total_debits"], summ["total_credits"], status, diff, len(rows), summ["breaks"]])
            for (rs, note), r in zip(row_status, rows):
                if rs == "break":
                    c.execute("INSERT OR IGNORE INTO bronze.quarantine VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              [stable_id("q", file_id, r.page_no, r.row_no, "balance_break"), case_id, file_id, r.page_no, r.row_no,
                               "balance_break", note, None])

            # ---- dedup: deterministic IDs; an overlapping statement adds a source, not a transaction
            ordinals: dict[tuple, int] = {}
            for (rs, note), r in zip(row_status, rows):
                desc_tok = vault_put(c, r.description, "desc")
                fp = (account_id, r.date.isoformat(), r.debit, r.credit, desc_tok, r.balance)
                ordinals[fp] = ordinals.get(fp, 0) + 1
                txn_id = stable_id("t", *fp, ordinals[fp])
                if not c.execute("SELECT 1 FROM silver.transactions WHERE txn_id = ?", [txn_id]).fetchone():
                    c.execute("""INSERT INTO silver.transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                              [txn_id, case_id, account_id, r.date, "", "", desc_tok, r.debit, r.credit, r.balance, "", "",
                               json.dumps(ref_tokens(r.description)), rs, note, statement_id, r.page_no * 10000 + r.row_no])
                c.execute("INSERT OR IGNORE INTO silver.txn_sources VALUES (?, ?, ?, ?, ?)", [txn_id, statement_id, file_id, r.page_no, r.row_no])

        check = tamper.summarise(doc_signals + arith_signals)
        c.execute("DELETE FROM silver.document_checks WHERE file_id = ?", [file_id])
        c.execute("INSERT INTO silver.document_checks VALUES (?, ?, ?, ?, ?, ?)",
                  [file_id, case_id, check["score"], check["structure_score"], check["level"], json.dumps(check["signals"])])
        c.execute("DELETE FROM silver.accounts WHERE case_id = ? AND account_id NOT IN (SELECT account_id FROM silver.statements)", [case_id])
        renormalize(c, case_id)
        coverage.rebuild(c, case_id)
        bad_pages = [p for p in result.pages if p.status not in ("parsed", "no_transactions")]
        if not rows:
            fstatus, reason = "failed", "no transactions could be extracted; see page report"
        elif bad_pages or quarantine:
            fstatus, reason = "partial", f"{len(bad_pages)} page(s) not fully parsed, {len(quarantine)} item(s) quarantined"
        else:
            fstatus, reason = "processed", f"{len(rows)} transactions extracted"
        c.execute("UPDATE bronze.files SET status = ?, reason = ?, processed_at = ? WHERE file_id = ?", [fstatus, reason, datetime.utcnow(), file_id])
        c.execute("INSERT OR REPLACE INTO review.stage_runs VALUES (?, ?, ?, ?, ?)", [f["sha256"], case_id, "ingest", PIPELINE_VERSION, datetime.utcnow()])


def renormalize(con, case_id: str) -> None:
    """Re-mask every narration with the full case context (all own accounts and holder names known so far)."""
    accts, holders = _case_context(con, case_id)
    for txn_id, desc_tok in con.execute("SELECT txn_id, desc_token FROM silver.transactions WHERE case_id = ?", [case_id]).fetchall():
        raw = vault_get(con, desc_tok) or ""
        display, norm, _ = mask(raw, accts, holders)
        con.execute("UPDATE silver.transactions SET description = ?, description_norm = ?, channel = ?, counterparty = ? WHERE txn_id = ?",
                    [display, norm, channel(norm), counterparty(norm), txn_id])
