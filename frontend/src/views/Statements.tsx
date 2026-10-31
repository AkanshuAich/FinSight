import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, CopyCheck, Loader2, Lock, ShieldAlert, UploadCloud } from "lucide-react";
import { api } from "../api";
import type { Analysis, EditCheck, FileReport } from "../types";
import { bytes, dateLabel, money } from "../fmt";
import { ReconPill, useToast } from "../components/ui";

interface Props { caseId: string; a: Analysis | null; canUpload: boolean; onUploaded: () => void }

const FILE_STATUS: Record<string, [string, string]> = {
  processed: ["ok", "Processed"], partial: ["warn", "Partly processed"], failed: ["crit", "Not processed"],
  needs_password: ["warn", "Password needed"], processing: ["info", "Processing"],
};

const EDIT_LEVEL: Record<string, [string, string]> = {
  none: ["ok", "No signs of editing"], low: ["info", "Low edit risk"], medium: ["warn", "Medium edit risk"], high: ["crit", "High edit risk"],
};

function EditRisk({ check }: { check: EditCheck }) {
  const [open, setOpen] = useState(check.level === "medium" || check.level === "high");
  const [cls, label] = EDIT_LEVEL[check.level] ?? ["", check.level];
  const scored = check.signals.filter((s) => s.weight > 0);
  const info = check.signals.filter((s) => s.weight === 0);
  return (
    <div className="edit-risk">
      <button className="row" onClick={() => setOpen((o) => !o)} style={{ background: "none", border: "none", padding: 0, width: "100%", textAlign: "left" }}
              aria-expanded={open}>
        <ShieldAlert size={15} style={{ color: `var(--${cls === "ok" ? "pos" : cls === "info" ? "info" : cls})` }} />
        <span className={`pill ${cls}`}><span className="d" />{label}</span>
        <span className="num small">{check.score}/100</span>
        <div className="gauge" style={{ flex: "0 1 140px" }}><span style={{ width: `${check.score}%`, background: `var(--${cls === "ok" ? "pos" : cls === "info" ? "info" : cls})` }} /></div>
        <span className="small muted">{scored.length ? `${scored.length} signal${scored.length > 1 ? "s" : ""}` : "producer, revisions, dates, fonts and overlapping text checked"}</span>
        <span className="spacer" />
        {(scored.length > 0 || info.length > 0) && (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
      </button>
      {open && (scored.length > 0 || info.length > 0) && (
        <div className="stack" style={{ gap: 8, marginTop: 10 }}>
          {[...scored, ...info].map((s) => (
            <div key={s.code} className="edit-signal">
              <span className="num small" style={{ color: s.weight ? "var(--warn)" : "var(--muted)" }}>{s.weight ? `+${s.weight}` : "info"}</span>
              <div style={{ minWidth: 0 }}>
                <div className="small">{s.detail}</div>
                {s.evidence.map((e, i) => <div key={i} className="mono small muted" style={{ overflowWrap: "anywhere" }}>{e}</div>)}
              </div>
            </div>
          ))}
          <div className="small muted">Signals are reasons to verify the file against a copy from the bank, not proof of fraud.</div>
        </div>
      )}
    </div>
  );
}

export default function Statements({ caseId, a, canUpload, onUploaded }: Props) {
  const toast = useToast();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.files>> | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [pwFor, setPwFor] = useState<File | null>(null);
  const [pw, setPw] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const load = () => api.files(caseId).then(setData);
  useEffect(() => { setData(null); load(); }, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send(files: File[], password?: string) {
    for (const f of files) {
      setBusy(f.name);
      try {
        const r = await api.upload(caseId, f, password);
        if (r.file.status === "needs_password") { setPwFor(f); setPw(""); }
        else toast({ title: r.file.duplicate_upload ? "Duplicate ignored" : `${f.name}: ${FILE_STATUS[r.file.status]?.[1] ?? r.file.status}`, body: r.file.duplicate_upload ? "This exact file is already in the case; it was not counted again." : r.file.reason ?? undefined });
      } catch (e) { toast({ kind: "err", title: `${f.name} rejected`, body: String((e as Error).message) }); }
    }
    setBusy(null);
    await load();
    onUploaded();
  }

  const accts = Object.fromEntries((a?.accounts ?? []).map((x) => [x.account_id, `${x.bank_name} ${x.acct_masked}`]));
  const dupes = (data?.upload_events ?? []).filter((e) => e.duplicate);

  return (
    <div className="content-inner">
      {canUpload && (
        <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); send([...e.dataTransfer.files]); }}>
          {busy ? <Loader2 size={26} className="spin" style={{ color: "var(--accent)" }} /> : <UploadCloud size={26} style={{ color: "var(--accent)" }} />}
          <div style={{ fontWeight: 600 }}>{busy ? `Processing ${busy}…` : "Drop bank statements here"}</div>
          <div className="small muted">PDF (any layout with a text layer), CSV, Excel or JSON, up to 15 MB. Files are encrypted at rest; the same file is never counted twice.</div>
          <button className="btn primary sm" style={{ marginTop: 6 }} onClick={() => input.current?.click()} disabled={!!busy}>Choose files</button>
          <input ref={input} type="file" multiple hidden accept=".pdf,.csv,.xlsx,.json" onChange={(e) => e.target.files && send([...e.target.files])} />
        </div>
      )}

      {pwFor && (
        <>
          <div className="scrim" onClick={() => setPwFor(null)} />
          <div className="modal" role="dialog" aria-modal="true">
            <div className="row"><Lock size={18} /><h3 style={{ fontSize: 18 }}>{pwFor.name} is password protected</h3></div>
            <div className="small muted">Bank statements are often protected with a password such as part of the PAN or date of birth. It is used once to open the file and is never stored or logged.</div>
            <input className="input" type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Statement password" />
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setPwFor(null)}>Cancel</button>
              <button className="btn primary" disabled={!pw} onClick={() => { const f = pwFor; setPwFor(null); send([f], pw); }}>Open statement</button>
            </div>
          </div>
        </>
      )}

      {(a?.cross_checks ?? []).length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Continuity between statements</h3><span className="hint">Gaps are flagged, never treated as zero activity</span></div>
          {a!.cross_checks.map((c, i) => (
            <div className="flag" key={i}>
              <span className={`bar ${c.kind === "gap" || c.kind === "balance_mismatch" ? "medium" : "info"}`} />
              <div><div className="flag-title">{accts[c.account_id]} · {c.kind === "gap" ? "Missing period" : c.kind === "overlap" ? "Overlap, deduplicated" : c.kind === "balance_mismatch" ? "Balance does not carry over" : "Continuous"}</div>
                <div className="flag-detail">{c.detail}</div></div>
              <span />
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="card-h"><h3>Files</h3><span className="hint">{data?.files.length ?? 0} files{dupes.length ? ` · ${dupes.length} duplicate upload(s) ignored` : ""}</span></div>
        {!data && <div className="card-b"><div className="skeleton" style={{ height: 80 }} /></div>}
        {data?.files.length === 0 && <div className="card-b muted">No statements uploaded yet.</div>}
        {data?.files.map((f: FileReport) => {
          const [cls, label] = FILE_STATUS[f.status] ?? ["", f.status];
          const dupCount = data.upload_events.filter((e) => e.duplicate && (e as { file_id?: string }).file_id === f.file_id).length;
          return (
            <div className="file" key={f.file_id}>
              <div className="file-h">
                <div className="file-ic">{f.kind.toUpperCase()}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row wrap"><b style={{ overflowWrap: "anywhere" }}>{f.filename}</b><span className={`pill ${cls}`}><span className="d" />{label}</span>{dupCount > 0 && <span className="pill info" title="The identical file was uploaded again and ignored"><CopyCheck size={12} />uploaded {dupCount + 1}×, counted once</span>}</div>
                  <div className="small muted">{bytes(f.size_bytes)} · SHA-256 <span className="hash">{f.sha256.slice(0, 16)}…</span> · {f.reason}</div>
                </div>
              </div>
              {f.edit_check && <EditRisk check={f.edit_check} />}
              {f.pages.length > 0 && <div className="pages">{f.pages.map((p) => <span key={p.page_no} className={`page-chip ${p.status}`} title={p.reason}>{f.kind === "pdf" ? "Page" : "Sheet"} {p.page_no} · {p.status === "parsed" ? `${p.n_rows} rows` : p.status.replace("_", " ")}</span>)}</div>}
              {[["crit", "Not used", f.quarantine.filter((q) => q.kind !== "balance_break")],
                ["warn", "Kept but flagged: running balance breaks", f.quarantine.filter((q) => q.kind === "balance_break")]].map(([tone, head, qs]) => (
                (qs as FileReport["quarantine"]).length > 0 && (
                  <div key={head as string} className={`note ${tone}`} style={{ display: "grid", gap: 4 }}>
                    <b>{head as string} ({(qs as FileReport["quarantine"]).length}):</b>
                    {(qs as FileReport["quarantine"]).slice(0, 6).map((q, i) => <div key={i} className="small">{q.page_no ? `Page ${q.page_no}${q.row_no ? `, row ${q.row_no}` : ""}: ` : ""}{q.reason}</div>)}
                  </div>
                )
              ))}
              {f.statements.map((s) => (
                <div key={s.statement_id} className="stack" style={{ gap: 8 }}>
                  <div className="row wrap small"><b>{s.bank_name} {s.acct_masked}</b><span className="muted">{dateLabel(s.period_start)} – {dateLabel(s.period_end)} · {s.n_rows} rows · layout {s.layout}</span><span className="spacer" /><ReconPill status={s.recon_status} /></div>
                  <div className="recon">
                    <div><div className="label">Opening {s.opening_source === "derived" ? "(derived)" : ""}</div><div className="v">{money(s.opening_paise, true)}</div></div>
                    <div><div className="label">+ Credits</div><div className="v cr">{money(s.total_credits, true)}</div></div>
                    <div><div className="label">− Debits</div><div className="v">{money(s.total_debits, true)}</div></div>
                    <div><div className="label">= Computed closing</div><div className="v">{money(s.computed_closing, true)}</div></div>
                    <div><div className="label">Stated closing</div><div className={`v ${s.recon_diff ? "neg" : "pos"}`}>{money(s.closing_stated, true)}{s.recon_diff ? ` (Δ ${money(s.recon_diff, true)})` : " ✓"}</div></div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
