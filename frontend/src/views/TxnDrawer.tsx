import { useEffect, useMemo, useState } from "react";
import { Eye, FileText, Link2, Loader2, Repeat, ShieldAlert } from "lucide-react";
import { api } from "../api";
import type { Diff, TxnDetail } from "../types";
import { dateLabel, money, monthLabel, pct } from "../fmt";
import { CategoryChip, Drawer, StatusDot, statusLabel, useCats, useToast } from "../components/ui";

interface Props {
  caseId: string;
  txnId: string;
  canEdit: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
  onChanged: (diff: Diff | undefined) => void;
}

const SIGNAL_NAMES: Record<string, string> = {
  rule: "Keyword rule", entity: "Entity memory", periodic: "Periodic memory", memory: "Semantic memory", account: "Account pattern", jev: "Jev",
};
const LINK_NAMES: Record<string, string> = { transfer_pair: "Own-account transfer pair", reversal_pair: "Reversal pair", bounce_pair: "Returned payment pair" };

export default function TxnDrawer({ caseId, txnId, canEdit, onClose, onOpen, onChanged }: Props) {
  const cats = useCats();
  const toast = useToast();
  const [d, setD] = useState<TxnDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [newCat, setNewCat] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [revealReason, setRevealReason] = useState("");
  const [clear, setClear] = useState<string | null>(null);

  const load = () => api.transaction(caseId, txnId).then((x) => { setD(x); setNewCat(""); setReason(""); }).catch((e) => setErr(String(e.message)));
  useEffect(() => { setD(null); setClear(null); setRevealing(false); load(); }, [caseId, txnId]); // eslint-disable-line react-hooks/exhaustive-deps

  const t = d?.txn;
  const options = useMemo(() => Object.entries(cats).filter(([k, v]) => k !== "UNCLASSIFIED" && t && (v.dir === t.direction || v.dir === "B"))
    .sort((a, b) => a[1].label.localeCompare(b[1].label)), [cats, t]);
  const contribs = d?.classification.contributions ?? [];
  const maxV = Math.max(1, ...contribs.map((c) => c.value));
  const grouped = useMemo(() => {
    const g: Record<string, typeof contribs> = {};
    contribs.forEach((c) => { (g[c.category] = g[c.category] ?? []).push(c); });
    return Object.entries(g).sort((a, b) => b[1].reduce((s, c) => s + c.value, 0) - a[1].reduce((s, c) => s + c.value, 0));
  }, [contribs]);

  async function save() {
    if (!t) return;
    setSaving(true);
    try {
      const res = await api.override(caseId, t.txn_id, newCat, reason);
      if (res.noop) toast({ title: "No change", body: res.reason });
      onChanged(res.diff);
      await load();
    } catch (e) {
      toast({ kind: "err", title: "Correction not applied", body: String((e as Error).message) });
    } finally { setSaving(false); }
  }
  async function reveal() {
    try {
      const r = await api.reveal(caseId, txnId, revealReason);
      setClear(r.description);
      setRevealing(false);
      toast({ title: "Unmasked narration shown", body: "This view was recorded in the audit log with your reason." });
    } catch (e) { toast({ kind: "err", title: "Not revealed", body: String((e as Error).message) }); }
  }

  return (
    <Drawer onClose={onClose} sub={t ? `${t.bank_name} ${t.acct_masked} · ${dateLabel(t.txn_date)}` : "Transaction"}
            title={t ? <span className={t.direction === "C" ? "pos" : ""}>{t.direction === "C" ? "+" : "−"}{money(t.amount, true)}</span> : "Loading…"}>
      {err && <div className="note crit">{err}</div>}
      {!d && !err && <div className="stack"><div className="skeleton" style={{ height: 60 }} /><div className="skeleton" style={{ height: 160 }} /></div>}
      {d && t && (
        <>
          <section>
            <div className="mono" style={{ fontSize: 13.5, overflowWrap: "anywhere" }}>{clear ?? t.description}</div>
            <div className="row wrap small muted">
              <span>Channel {t.channel}</span>·<span>Balance after {money(t.balance, true)}</span>
              {t.counterparty && <>·<span>Counterparty {t.counterparty}</span></>}
              <span className="spacer" />
              {!clear && canEdit && <button className="btn ghost sm" onClick={() => setRevealing((r) => !r)}><Eye size={13} /> Reveal</button>}
            </div>
            {revealing && (
              <div className="note info form-grid">
                <span>Account numbers, UPI IDs and phone numbers are masked. Unmasking is logged with your reason.</span>
                <div className="row"><input className="input" style={{ flex: 1 }} placeholder="Reason, e.g. verify counterparty with applicant" value={revealReason} onChange={(e) => setRevealReason(e.target.value)} />
                  <button className="btn primary sm" disabled={revealReason.trim().length < 5} onClick={reveal}>Show</button></div>
              </div>
            )}
            {t.recon_status === "break" && <div className="note warn"><b>Balance chain break.</b> {t.recon_note}</div>}
          </section>

          <section>
            <h4>Category</h4>
            <div className="row wrap">
              <CategoryChip cat={t.category} />
              <span className="row small"><StatusDot status={t.status} /> {statusLabel(t.status)}</span>
              {t.status !== "confirmed" && d.classification.tier === "fusion" && <span className="conf">P {pct(d.classification.probability)} · margin {pct(d.classification.margin)}</span>}
              {d.classification.tier === "gate" && <span className="pill info">Hard rule</span>}
            </div>
            <div className="note">{d.classification.explanation}</div>
            {t.override_category && (
              <div className="note info">Corrected by {t.override_actor}: “{t.override_reason}”. The model's own result is <b>{cats[t.model_category]?.label ?? t.model_category}</b>; every model result and correction is kept in the history below.</div>
            )}
          </section>

          {grouped.length > 0 && (
            <section>
              <h4>Why: evidence by signal</h4>
              <div className="stack" style={{ gap: 14 }}>
                {grouped.map(([cat, cs]) => (
                  <div key={cat} className="stack" style={{ gap: 6 }}>
                    <div className="row"><CategoryChip cat={cat} /><span className="conf">score {cs.reduce((s, c) => s + c.value, 0).toFixed(2)}</span></div>
                    {cs.map((c, i) => (
                      <div className="contrib" key={i}>
                        <div style={{ minWidth: 0 }}><div>{c.detail}</div><div className="sig">{SIGNAL_NAMES[c.signal.split(":")[0]] ?? c.signal} · {c.signal}</div></div>
                        <div className="bar"><span style={{ width: `${(c.value / maxV) * 100}%`, background: `var(--t-${cats[cat]?.treatment === "other_credit" ? "other" : cats[cat]?.treatment === "review_credit" ? "review" : cats[cat]?.treatment ?? "expense"})` }} /></div>
                        <div className="num small" style={{ textAlign: "right" }}>+{c.value.toFixed(2)}</div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div className="label" style={{ marginTop: 6 }}>Resulting probabilities</div>
              {d.classification.candidates.map((c) => (
                <div className="cand" key={c.category}><span className="small">{cats[c.category]?.label ?? c.category}</span><div className="bar"><span style={{ width: `${c.p * 100}%` }} /></div><span className="num small">{pct(c.p)}</span></div>
              ))}
            </section>
          )}

          {d.links.length > 0 && (
            <section>
              <h4><Link2 size={15} /> Linked transactions</h4>
              {d.links.map((l) => (
                <button key={l.txn.txn_id} className="linked" style={{ textAlign: "left" }} onClick={() => onOpen(l.txn.txn_id)}>
                  <div className="row"><b className="small">{LINK_NAMES[l.kind] ?? l.kind}</b><span className="spacer" /><span className={`num ${l.txn.direction === "C" ? "pos" : ""}`}>{l.txn.direction === "C" ? "+" : "−"}{money(l.txn.amount, true)}</span></div>
                  <div className="mono small">{l.txn.description}</div>
                  <div className="small muted">{l.txn.bank_name} {l.txn.acct_masked} · {dateLabel(l.txn.txn_date)} · {l.reason}</div>
                </button>
              ))}
            </section>
          )}

          {d.patterns.length > 0 && (
            <section>
              <h4><Repeat size={15} /> Recurring series</h4>
              {d.patterns.map((p) => (
                <div className="linked" key={p.pattern_id}>
                  <div className="small"><b>{p.counterparties.map((c) => c === "<HOLDER>" ? "[Holder]" : c).join(" → ")}</b>{p.counterparties.length > 1 && <span className="pill info" style={{ marginLeft: 6 }}>renamed</span>}</div>
                  <div className="small muted">About {money(p.median_amount)} on day ~{p.typical_day} · {p.months.length} months · variation {pct(p.amount_cv, 1)}
                    {p.missed_months.length > 0 && <span className="neg"> · missed {p.missed_months.map(monthLabel).join(", ")}</span>}</div>
                </div>
              ))}
            </section>
          )}

          <section>
            <h4><FileText size={15} /> Source</h4>
            {d.sources.map((s, i) => (
              <div className="kv" key={i}>
                <dt>File</dt><dd>{s.filename}</dd>
                <dt>Location</dt><dd>Page {s.page_no}, row {s.row_no}</dd>
                <dt>Statement period</dt><dd>{dateLabel(s.period_start)} – {dateLabel(s.period_end)}</dd>
              </div>
            ))}
            {d.sources.length > 1 && <div className="note ok">Appears in {d.sources.length} overlapping statements and is counted once.</div>}
          </section>

          {canEdit ? (
            <section>
              <h4><ShieldAlert size={15} /> Correct the category</h4>
              <div className="form-grid">
                <select className="select" value={newCat} onChange={(e) => setNewCat(e.target.value)} aria-label="New category">
                  <option value="">Choose a category…</option>
                  {options.map(([k, v]) => <option key={k} value={k}>{v.label}{k === t.category ? " (current)" : ""}</option>)}
                </select>
                <textarea className="input" placeholder="Reason (required, kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <div className="row">
                  <span className="small muted">Saved as an event. Dependent figures are recalculated and the narration is remembered for this case.</span>
                  <span className="spacer" />
                  <button className="btn primary" disabled={!newCat || reason.trim().length < 3 || saving} onClick={save}>
                    {saving ? <Loader2 size={14} className="spin" /> : null} Apply correction
                  </button>
                </div>
              </div>
            </section>
          ) : <div className="note">Your role can view but not correct classifications.</div>}

          <section>
            <h4>History</h4>
            <div className="timeline">
              {[...d.history.map((h) => ({ ts: h.created_at, user: false, text: <>Model: <b>{cats[h.category]?.label ?? h.category}</b> ({statusLabel(h.status as never)}{h.probability !== null && h.source !== "default" ? `, P ${pct(h.probability)}` : ""}) · run {h.seq}</> })),
                ...d.overrides.map((o) => ({ ts: o.created_at, user: true, text: <>{o.actor} ({o.role}) changed <b>{cats[o.from_category]?.label ?? o.from_category}</b> → <b>{cats[o.to_category]?.label ?? o.to_category}</b>: “{o.reason}”</> }))]
                .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
                .map((e, i) => (
                  <div className="tl" key={i}><span className={`pt ${e.user ? "user" : ""}`} /><div><div>{e.text}</div><div className="small muted">{String(e.ts).replace("T", " ").slice(0, 19)}</div></div></div>
                ))}
            </div>
          </section>
        </>
      )}
    </Drawer>
  );
}
