import type { Flag } from "../types";
import { monthLabel } from "../fmt";
import { SevPill } from "../components/ui";

interface Props { flags: Flag[]; onTxns: (ids: string[], label: string) => void }

const GROUPS: [Flag["category"], string, string][] = [
  ["risk", "Financial behaviour", "Indicators from the customer's cash flow. Each needs analyst judgement; none is a finding of fraud."],
  ["data", "Data quality", "Problems with the statements themselves: unread pages, gaps, reconciliation breaks."],
  ["review", "Classification review", "Transactions the system could not place with confidence."],
];

export default function Flags({ flags, onTxns }: Props) {
  return (
    <div className="content-inner">
      {GROUPS.map(([key, title, hint]) => {
        const fs = flags.filter((f) => f.category === key);
        if (!fs.length) return null;
        return (
          <div className="card" key={key}>
            <div className="card-h"><div><h3>{title}</h3><div className="hint">{hint}</div></div><span className="pill">{fs.length}</span></div>
            {fs.map((f, i) => (
              <div className="flag" key={i}>
                <span className={`bar ${f.severity}`} />
                <div style={{ minWidth: 0 }}>
                  <div className="row wrap"><span className="flag-title">{f.title}</span><SevPill sev={f.severity} /></div>
                  <div className="flag-detail">{f.detail}</div>
                  {f.months.length > 0 && <div className="row wrap" style={{ marginTop: 6, gap: 4 }}>{f.months.map((m) => <span key={m} className="pill">{monthLabel(m)}</span>)}</div>}
                </div>
                {f.txn_ids.length > 0 ? <button className="btn sm" onClick={() => onTxns(f.txn_ids, f.title)}>View {f.txn_ids.length}</button> : <span />}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
