import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import type { Metric, Txn } from "../types";
import { compact, dateLabel, money, monthLabel, pct } from "../fmt";
import { CategoryChip, Drawer } from "../components/ui";

interface Props { metric: Metric; txns: Txn[]; onClose: () => void; onOpen: (id: string) => void }

function TxnList({ ids, byId, onOpen, limit = 50 }: { ids: string[]; byId: Record<string, Txn>; onOpen: (id: string) => void; limit?: number }) {
  const [all, setAll] = useState(false);
  const rows = ids.map((i) => byId[i]).filter(Boolean).sort((a, b) => a.txn_date.localeCompare(b.txn_date));
  const shown = all ? rows : rows.slice(0, limit);
  return (
    <div style={{ border: "1px solid var(--line-2)", borderRadius: 8, overflow: "hidden" }}>
      <table className="tbl">
        <tbody>
          {shown.map((t) => (
            <tr key={t.txn_id} className="click" onClick={() => onOpen(t.txn_id)}>
              <td className="num small" style={{ whiteSpace: "nowrap" }}>{dateLabel(t.txn_date)}</td>
              <td><span className="desc mono small" style={{ maxWidth: 250 }}>{t.description}</span></td>
              <td><CategoryChip cat={t.category} /></td>
              <td className={`r num ${t.direction === "C" ? "cr" : ""}`}>{money(t.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > limit && <button className="btn ghost sm" style={{ margin: 6 }} onClick={() => setAll((a) => !a)}>{all ? "Show fewer" : `Show all ${rows.length}`}</button>}
    </div>
  );
}

export default function MetricDrawer({ metric: m, txns, onClose, onOpen }: Props) {
  const byId = useMemo(() => Object.fromEntries(txns.map((t) => [t.txn_id, t])), [txns]);
  const [open, setOpen] = useState<string | null>(null);
  const groups = useMemo(() => {
    const g: Record<string, string[]> = {};
    m.excluded.forEach((e) => { (g[e.reason] = g[e.reason] ?? []).push(e.txn_id); });
    return Object.entries(g).sort((a, b) => b[1].length - a[1].length);
  }, [m]);
  const sum = (ids: string[]) => ids.reduce((s, i) => s + (byId[i]?.amount ?? 0), 0);
  const value = m.unit === "ratio" ? pct(m.value, 1) : money(m.value);

  return (
    <Drawer onClose={onClose} sub="Calculation breakdown" title={m.label}>
      <section>
        <div className="big-amt">{value}</div>
        <div className="note"><b>Method.</b> {m.method}</div>
        {m.notes.map((n, i) => <div key={i} className="note warn"><Info size={13} style={{ verticalAlign: -2 }} /> {n}</div>)}
      </section>

      {m.stats && Object.keys(m.stats).length > 0 && (
        <section>
          <h4>Supporting statistics</h4>
          <div className="recon">
            {Object.entries(m.stats).map(([k, v]) => (
              <div key={k}><div className="label">{k.replace(/_/g, " ")}</div>
                <div className="v">{k === "cv" ? v.toFixed(2) : k === "trend_3m" ? pct(v) : compact(v)}</div></div>
            ))}
          </div>
        </section>
      )}

      {m.monthly && m.monthly.length > 0 && (
        <section>
          <h4>By month</h4>
          <table className="tbl">
            <tbody>{m.monthly.map((x) => <tr key={x.month}><td>{monthLabel(x.month)}</td><td className={`r num ${x.value < 0 ? "neg" : ""}`}>{money(x.value)}</td></tr>)}</tbody>
          </table>
          {m.months_missing.length > 0 && <div className="small muted">Not used (incomplete coverage): {m.months_missing.map(monthLabel).join(", ")}</div>}
        </section>
      )}

      {m.items && (
        <section>
          <h4>{m.key === "recurring_obligations" ? "Commitments" : "Typical monthly outflows by category"}</h4>
          {m.items.map((i) => (
            <div className="linked" key={i.category + i.counterparty}>
              <div className="row"><CategoryChip cat={i.category} /><span className="small">{i.counterparty}</span><span className="spacer" />
                <span className="num">{money(i.monthly_amount)}/mo</span></div>
              <div className="small muted">{m.key === "recurring_obligations"
                ? `${i.months.length} months · ${i.active ? "active, counted" : "inactive, not counted"}`
                : `seen in ${i.months.length} month${i.months.length > 1 ? "s" : ""}, averaged over all covered months`}</div>
            </div>
          ))}
          {m.outflows !== undefined && <div className="row small"><b>Total typical outflows</b><span className="spacer" /><span className="num">{money(m.outflows)}/mo</span></div>}
        </section>
      )}

      {m.included.length > 0 && (
        <section>
          <h4>Included <span className="pill ok">{m.included.length} · {money(sum(m.included))}</span></h4>
          <TxnList ids={m.included} byId={byId} onOpen={onOpen} limit={m.included.length > 40 ? 12 : 40} />
        </section>
      )}

      {groups.length > 0 && (
        <section>
          <h4>Excluded, with reasons <span className="pill warn">{m.excluded.length}</span></h4>
          {groups.map(([reason, ids]) => (
            <div key={reason} style={{ border: "1px solid var(--line-2)", borderRadius: 8 }}>
              <button className="row" style={{ width: "100%", background: "none", border: "none", padding: "10px 12px", textAlign: "left" }} onClick={() => setOpen(open === reason ? null : reason)}>
                {open === reason ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span style={{ flex: 1 }}>{reason}</span>
                <span className="conf">{ids.length} · {compact(sum(ids))}</span>
              </button>
              {open === reason && <div style={{ padding: "0 8px 8px" }}><TxnList ids={ids} byId={byId} onOpen={onOpen} limit={20} /></div>}
            </div>
          ))}
        </section>
      )}
    </Drawer>
  );
}
