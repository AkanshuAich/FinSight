import { useMemo, useState } from "react";
import { AlertTriangle, Flag, Search, X } from "lucide-react";
import type { Account, Txn } from "../types";
import { dateLabel, money } from "../fmt";
import { CategoryChip, StatusDot, useCats } from "../components/ui";

interface Props {
  txns: Txn[];
  accounts: Account[];
  preset: { ids: string[]; label: string } | null;
  onClearPreset: () => void;
  onOpen: (id: string) => void;
  selected: string | null;
}

type StatusF = "all" | "auto" | "review" | "unclassified" | "confirmed";

export default function Transactions({ txns, accounts, preset, onClearPreset, onOpen, selected }: Props) {
  const cats = useCats();
  const [qtext, setQ] = useState("");
  const [acct, setAcct] = useState("all");
  const [cat, setCat] = useState("all");
  const [status, setStatus] = useState<StatusF>("all");
  const [dir, setDir] = useState<"all" | "C" | "D">("all");
  const [flagged, setFlagged] = useState(false);

  const presetSet = useMemo(() => (preset ? new Set(preset.ids) : null), [preset]);
  const rows = useMemo(() => {
    const ql = qtext.trim().toLowerCase();
    return txns.filter((t) =>
      (!presetSet || presetSet.has(t.txn_id)) &&
      (acct === "all" || t.account_id === acct) &&
      (cat === "all" || t.category === cat) &&
      (status === "all" || t.status === status) &&
      (dir === "all" || t.direction === dir) &&
      (!flagged || t.flags.length > 0 || t.recon_status === "break") &&
      (!ql || t.description.toLowerCase().includes(ql) || (cats[t.category]?.label ?? "").toLowerCase().includes(ql) || String(t.amount / 100).includes(ql)));
  }, [txns, presetSet, acct, cat, status, dir, flagged, qtext, cats]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: txns.length };
    txns.forEach((t) => { c[t.status] = (c[t.status] ?? 0) + 1; });
    return c;
  }, [txns]);
  const usedCats = useMemo(() => [...new Set(txns.map((t) => t.category))].sort((a, b) => (cats[a]?.label ?? a).localeCompare(cats[b]?.label ?? b)), [txns, cats]);
  const cr = rows.reduce((s, t) => s + t.credit, 0);
  const dr = rows.reduce((s, t) => s + t.debit, 0);

  return (
    <div className="content-inner">
      <div className="card">
        {preset && (
          <div className="toolbar" style={{ background: "var(--accent-soft)" }}>
            <span className="small"><b>Showing:</b> {preset.label} ({preset.ids.length})</span>
            <span className="spacer" />
            <button className="btn sm" onClick={onClearPreset}><X size={13} /> Clear</button>
          </div>
        )}
        <div className="toolbar">
          <div className="search"><Search size={15} /><input className="input" placeholder="Search narration, category or amount" value={qtext} onChange={(e) => setQ(e.target.value)} aria-label="Search transactions" /></div>
          <select className="select" value={acct} onChange={(e) => setAcct(e.target.value)} aria-label="Account">
            <option value="all">All accounts</option>
            {accounts.map((a) => <option key={a.account_id} value={a.account_id}>{a.bank_name} {a.acct_masked}</option>)}
          </select>
          <select className="select" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
            <option value="all">All categories</option>
            {usedCats.map((c) => <option key={c} value={c}>{cats[c]?.label ?? c}</option>)}
          </select>
          <div className="seg" role="group" aria-label="Direction">
            {(["all", "C", "D"] as const).map((d) => <button key={d} className={dir === d ? "on" : ""} onClick={() => setDir(d)}>{d === "all" ? "All" : d === "C" ? "Credits" : "Debits"}</button>)}
          </div>
          <button className={`btn sm ${flagged ? "primary" : ""}`} onClick={() => setFlagged((f) => !f)}><Flag size={13} /> Flagged</button>
        </div>
        <div className="toolbar">
          <div className="seg" role="group" aria-label="Status">
            {(["all", "auto", "confirmed", "review", "unclassified"] as StatusF[]).map((s) => (
              <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>
                {s !== "all" && <StatusDot status={s} />}{s === "all" ? "All" : s === "auto" ? "Automatic" : s === "confirmed" ? "Confirmed" : s === "review" ? "Review" : "Unclassified"}
                <span className="conf">{counts[s] ?? 0}</span>
              </button>
            ))}
          </div>
          <span className="spacer" />
          <span className="small muted">{rows.length} shown · in <span className="num cr">{money(cr)}</span> · out <span className="num">{money(dr)}</span></span>
        </div>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr><th>Date</th><th>Account</th><th>Narration</th><th>Category</th><th className="r">Debit</th><th className="r">Credit</th><th className="r">Balance</th></tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.txn_id} className={`click ${selected === t.txn_id ? "sel" : ""}`} onClick={() => onOpen(t.txn_id)}>
                  <td className="num small" style={{ whiteSpace: "nowrap" }}>{dateLabel(t.txn_date)}</td>
                  <td className="small" style={{ whiteSpace: "nowrap" }}><span className="muted">{t.bank_name.split(" ")[0]}</span> <span className="num">{t.acct_masked.slice(-4)}</span></td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      {(t.flags.length > 0 || t.recon_status === "break") && <span title={[...t.flags, t.recon_status === "break" ? "Balance chain break" : ""].filter(Boolean).join(" · ")}><AlertTriangle size={14} style={{ color: "var(--warn)" }} /></span>}
                      <span className="desc mono small" title={t.description}>{t.description}</span>
                    </div>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <StatusDot status={t.status} />
                      <CategoryChip cat={t.category} />
                      {t.status !== "confirmed" && t.tier === "fusion" && t.probability !== null && <span className="conf">{Math.round(t.probability * 100)}%</span>}
                      {t.tier === "gate" && t.status !== "confirmed" && <span className="conf">rule</span>}
                    </div>
                  </td>
                  <td className="r num">{t.debit ? money(t.debit, true) : ""}</td>
                  <td className="r num cr">{t.credit ? money(t.credit, true) : ""}</td>
                  <td className="r num muted">{money(t.balance, true)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={7} className="muted" style={{ padding: 30, textAlign: "center" }}>No transactions match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
