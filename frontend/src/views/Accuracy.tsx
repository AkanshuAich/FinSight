import { useEffect, useState } from "react";
import { FlaskConical } from "lucide-react";
import { api } from "../api";
import type { Evaluation } from "../types";
import { money, pct } from "../fmt";
import { Empty, useCats } from "../components/ui";

export default function Accuracy({ caseId, version, onOpen }: { caseId: string; version: string; onOpen: (id: string) => void }) {
  const cats = useCats();
  const [e, setE] = useState<Evaluation | null>(null);
  useEffect(() => { setE(null); api.evaluation(caseId).then(setE); }, [caseId, version]);
  if (!e) return <div className="content-inner"><div className="skeleton" style={{ height: 160 }} /></div>;
  if (!e.available) return <div className="content-inner"><Empty icon={<FlaskConical size={32} />} title="No ground truth for this case">Accuracy is measured on the sample cases, whose true categories are known. Load the sample cases to see it.</Empty></div>;
  return (
    <div className="content-inner">
      <div className="note info">Measured against the labelled synthetic statements. The rules were developed with this data, so treat these figures as a regression check, not a real-world benchmark.</div>
      <div className="stat-grid">
        <div className="card card-b"><div className="label">Category accuracy</div><div className="big-stat">{pct(e.accuracy, 1)}</div><div className="small muted">{e.matched} transactions matched to labels</div></div>
        <div className="card card-b"><div className="label">Decided automatically</div><div className="big-stat">{pct(e.auto_share, 1)}</div><div className="small muted">the rest went to analyst review</div></div>
        <div className="card card-b"><div className="label">Accuracy of automatic decisions</div><div className="big-stat">{pct(e.auto_accuracy, 1)}</div><div className="small muted">includes analyst-confirmed items</div></div>
        <div className="card card-b"><div className="label">Statements fully reconciled</div><div className="big-stat">{pct(e.reconciliation_pass_rate, 0)}</div><div className="small muted">opening + credits − debits = closing, no row breaks</div></div>
      </div>
      <div className="grid-2">
        <div className="card">
          <div className="card-h"><h3>Per category</h3><span className="hint">precision · recall</span></div>
          <div className="card-b">
            {e.per_category.map((c) => (
              <div className="meter" key={c.category}>
                <span className="small">{c.label} <span className="conf">({c.support})</span></span>
                <div className="bar"><span style={{ width: `${(c.recall ?? 0) * 100}%` }} /></div>
                <span className="num small">{pct(c.precision)}</span><span className="num small">{pct(c.recall)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="card-h"><h3>Disagreements</h3><span className="hint">{e.errors.length} rows</span></div>
          <table className="tbl">
            <tbody>
              {e.errors.map((x) => (
                <tr key={x.txn_id} className="click" onClick={() => onOpen(x.txn_id)}>
                  <td><div className="mono small">{x.description}</div><div className="small muted">expected <b>{cats[x.expected]?.label ?? x.expected}</b>, got <b>{cats[x.predicted]?.label ?? x.predicted}</b> ({x.status})</div></td>
                  <td className="r num">{money(x.amount)}</td>
                </tr>
              ))}
              {e.errors.length === 0 && <tr><td className="muted">No disagreements.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
