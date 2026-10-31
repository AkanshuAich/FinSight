import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { api } from "../api";
import type { Diff, Txn } from "../types";
import { dateLabel, money } from "../fmt";
import { CategoryChip, Empty, StatusDot, useCats, useToast } from "../components/ui";

interface Props { caseId: string; txns: Txn[]; canEdit: boolean; onOpen: (id: string) => void; onChanged: (d: Diff | undefined) => void }

export default function Review({ caseId, txns, canEdit, onOpen, onChanged }: Props) {
  const cats = useCats();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [choice, setChoice] = useState<Record<string, string>>({});
  const items = txns.filter((t) => t.status === "review" || t.status === "unclassified").sort((a, b) => b.amount - a.amount);

  async function confirm(t: Txn, cat: string) {
    setBusy(t.txn_id);
    try {
      const r = await api.override(caseId, t.txn_id, cat, "Confirmed from the review queue");
      onChanged(r.diff);
    } catch (e) { toast({ kind: "err", title: "Not saved", body: String((e as Error).message) }); }
    setBusy(null);
  }

  if (!items.length) return <div className="content-inner"><Empty icon={<CheckCircle2 size={34} className="pos" />} title="Review queue is clear">Every transaction has a confident or analyst-confirmed category. Low-confidence items appear here and are excluded from income until confirmed.</Empty></div>;
  return (
    <div className="content-inner">
      <div className="note info">These {items.length} transactions had weak or conflicting evidence. Income excludes them until you confirm a category. Each decision is saved as an event and remembered for similar narrations in this case.</div>
      <div className="card">
        <table className="tbl">
          <thead><tr><th>Date</th><th>Narration</th><th className="r">Amount</th><th>Suggested</th><th>Decision</th></tr></thead>
          <tbody>
            {items.map((t) => {
              const opts = Object.entries(cats).filter(([k, v]) => k !== "UNCLASSIFIED" && (v.dir === t.direction || v.dir === "B")).sort((a, b) => a[1].label.localeCompare(b[1].label));
              const sel = choice[t.txn_id] ?? (t.category !== "UNCLASSIFIED" ? t.category : "");
              return (
                <tr key={t.txn_id}>
                  <td className="num small">{dateLabel(t.txn_date)}</td>
                  <td><button className="btn ghost sm" style={{ padding: 0 }} onClick={() => onOpen(t.txn_id)}><span className="desc mono small" style={{ maxWidth: 340 }}>{t.description}</span></button>
                    <div className="small muted">{t.explanation}</div></td>
                  <td className={`r num ${t.direction === "C" ? "cr" : ""}`}>{t.direction === "C" ? "+" : "−"}{money(t.amount)}</td>
                  <td><div className="row"><StatusDot status={t.status} /><CategoryChip cat={t.category} /></div></td>
                  <td>
                    {canEdit ? (
                      <div className="row">
                        <select className="select" value={sel} onChange={(e) => setChoice({ ...choice, [t.txn_id]: e.target.value })} aria-label="Category decision">
                          <option value="">Choose…</option>
                          {opts.map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                        </select>
                        <button className="btn primary sm" disabled={!sel || busy === t.txn_id} onClick={() => confirm(t, sel)}>
                          {busy === t.txn_id ? <Loader2 size={13} className="spin" /> : "Confirm"}
                        </button>
                      </div>
                    ) : <span className="small muted">View only</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
