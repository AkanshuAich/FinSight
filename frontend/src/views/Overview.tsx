import { useMemo } from "react";
import { ArrowUpRight, ChevronRight, Repeat, ShieldCheck } from "lucide-react";
import { Bar, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Analysis, Metric, Txn } from "../types";
import { compact, money, monthLabel, pct, shortDate } from "../fmt";
import { CategoryChip, SevPill, useCats } from "../components/ui";

interface Props {
  a: Analysis;
  txns: Txn[];
  onMetric: (key: string) => void;
  onFlags: () => void;
  onTxns: (ids: string[], label: string) => void;
  onStatements: () => void;
}

const ACCT_COLORS = ["var(--accent)", "var(--t-obligation)", "var(--t-other)", "var(--t-review)"];

function Tip({ active, payload, label, rows }: { active?: boolean; payload?: { payload: Record<string, number | string> }[]; label?: string; rows: [string, string][] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="tt">
      <div className="tt-h"><span>{label}</span>{p.coverage && p.coverage !== "full" ? <span className="pill warn">{String(p.coverage)} coverage</span> : null}</div>
      {rows.map(([k, l]) => p[k] !== undefined && p[k] !== null ? <div className="tt-r" key={k}><span>{l}</span><span>{money(Number(p[k]))}</span></div> : null)}
    </div>
  );
}

function Kpi({ m, lead, foot, onClick, children }: { m?: Metric; lead?: boolean; foot?: React.ReactNode; onClick: () => void; children?: React.ReactNode }) {
  return (
    <button className={`kpi ${lead ? "lead" : ""}`} onClick={onClick} aria-label={`Open breakdown for ${m?.label}`}>
      <ArrowUpRight size={15} className="kpi-open" />
      <div className="kpi-label"><span>{m?.label}</span></div>
      {children ?? <div className="kpi-value">{m?.value === null || m?.value === undefined ? "—" : compact(m.value)}</div>}
      <div className="kpi-foot">{foot}</div>
    </button>
  );
}

export default function Overview({ a, txns, onMetric, onFlags, onTxns, onStatements }: Props) {
  const cats = useCats();
  const byId = useMemo(() => Object.fromEntries(txns.map((t) => [t.txn_id, t])), [txns]);
  const m = a.metrics;
  const inc = m.estimated_income;
  const foir = m.foir?.value ?? null;
  const months = a.monthly.map((r) => ({
    month: monthLabel(r.month), coverage: r.coverage, credits: r.credits_adjusted, debits: r.debits_adjusted, net: r.net, income: r.income,
  }));
  const incomeBars = (inc?.monthly ?? []).map((x) => ({ month: monthLabel(x.month), value: x.value }));
  const balanceData = useMemo(() => {
    const byDate: Record<string, Record<string, number | string>> = {};
    Object.entries(a.account_balance_series).forEach(([acct, ser]) => ser.forEach((p) => {
      byDate[p.date] = byDate[p.date] ?? { date: p.date };
      byDate[p.date][acct] = p.balance;
    }));
    return Object.values(byDate).sort((x, y) => String(x.date).localeCompare(String(y.date)));
  }, [a]);
  const sev = { high: 0, medium: 0, low: 0, info: 0 } as Record<string, number>;
  a.flags.forEach((f) => { sev[f.severity] += 1; });
  const riskFlags = a.flags.filter((f) => f.severity === "high" || f.severity === "medium").slice(0, 6);
  const reconciled = a.statements.filter((s) => s.recon_status === "reconciled").length;
  const acctName = (id: string) => { const ac = a.accounts.find((x) => x.account_id === id); return ac ? `${ac.bank_name} ${ac.acct_masked.slice(-4)}` : id; };

  const patterns = a.patterns
    .map((p) => {
      const members = p.txn_ids.map((i) => byId[i]).filter(Boolean);
      const counts: Record<string, number> = {};
      members.forEach((t) => { counts[t.category] = (counts[t.category] ?? 0) + 1; });
      const cat = Object.entries(counts).sort((x, y) => y[1] - x[1])[0]?.[0] ?? "";
      return { ...p, cat };
    })
    .filter((p) => ["SALARY", "LOAN_EMI", "RENT", "INSURANCE", "INVESTMENT", "UTILITIES", "CARD_PAYMENT", "INTERNAL_TRANSFER", "BUSINESS_RECEIPT"].includes(p.cat))
    .sort((x, y) => {
      const order = ["SALARY", "BUSINESS_RECEIPT", "LOAN_EMI", "RENT"];
      const ox = order.indexOf(x.cat), oy = order.indexOf(y.cat);
      return (ox < 0 ? 9 : ox) - (oy < 0 ? 9 : oy) || y.median_amount - x.median_amount;
    })
    .slice(0, 7);

  const foirColor = foir === null ? "var(--muted)" : foir < 0.4 ? "var(--pos)" : foir < 0.55 ? "var(--warn)" : "var(--crit)";
  const trend = inc?.stats?.trend_3m;

  return (
    <div className="content-inner">
      <div className="kpis">
        <Kpi m={inc} lead onClick={() => onMetric("estimated_income")}
             foot={<>{inc?.profile === "SALARIED" ? "Salaried" : "Self-employed"} · {inc?.method}
               {inc?.profile !== "SALARIED" && inc?.stats?.conservative !== undefined && (inc?.stats?.cv ?? 0) > 0.25 &&
                 <><br /><b>Conservative {compact(inc.stats.conservative)}</b> (reached in 3 of 4 months)</>}
               {inc?.stats?.provisional !== undefined && inc.stats.provisional > (inc.value ?? 0) &&
                 <><br /><b className="warn-text">Provisional {compact(inc.stats.provisional)}</b> incl. credits awaiting review</>}</>} />
        <Kpi m={m.recurring_obligations} onClick={() => onMetric("recurring_obligations")}
             foot={<>{m.recurring_obligations?.items?.filter((i) => i.active).length ?? 0} active commitments: EMI and rent</>} />
        <Kpi m={m.foir} onClick={() => onMetric("foir")} foot={<>Obligations ÷ income. Typical lender comfort below 40–55%.</>}>
          <div className="kpi-value" style={{ color: foirColor }}>{pct(foir, 1)}</div>
          <div className="gauge" aria-hidden><span style={{ width: `${Math.min(100, (foir ?? 0) * 100 / 0.8)}%`, background: foirColor }} /></div>
          <div className="gauge-ticks"><span>0</span><span>40%</span><span>55%</span><span>80%</span></div>
        </Kpi>
        <Kpi m={m.monthly_surplus} onClick={() => onMetric("monthly_surplus")}
             foot={<>Income minus typical monthly outflows of {compact(m.monthly_surplus?.outflows)}</>}>
          <div className={`kpi-value ${(m.monthly_surplus?.value ?? 0) < 0 ? "neg" : ""}`}>{compact(m.monthly_surplus?.value)}</div>
        </Kpi>
        <Kpi m={m.net_cash_flow} onClick={() => onMetric("net_cash_flow")}
             foot={<>{(m.net_cash_flow?.monthly ?? []).filter((x) => x.value < 0).length} of {m.net_cash_flow?.months_used.length} covered months negative</>}>
          <div className={`kpi-value ${(m.net_cash_flow?.value ?? 0) < 0 ? "neg" : ""}`}>{compact(m.net_cash_flow?.value)}</div>
        </Kpi>
        <Kpi m={m.average_balance} onClick={() => onMetric("average_balance")}
             foot={<>{m.average_balance?.trend !== null && m.average_balance?.trend !== undefined ? `${m.average_balance.trend >= 0 ? "Up" : "Down"} ${pct(Math.abs(m.average_balance.trend))} first to last month` : "Across all accounts"}</>} />
      </div>

      <div className="card strip">
        <div className="row" style={{ gap: 10 }}>
          <ShieldCheck size={18} className="pos" />
          <div>
            <div className="label">Data completeness</div>
            <div className="small">{a.statements.length} statements · {reconciled} fully reconciled · {a.n_transactions} unique transactions</div>
          </div>
        </div>
        <div className="cov" aria-label="Month coverage">
          {a.months.map((mm) => <span key={mm} className={`cov-cell ${a.coverage[mm]}`} title={`${monthLabel(mm)}: ${a.coverage[mm]} coverage`}>{monthLabel(mm)}</span>)}
        </div>
        <button className="btn ghost sm" onClick={onStatements}>Statements <ChevronRight size={14} /></button>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-h">
            <div><h3>Monthly cash flow</h3><div className="hint">Adjusted: own-account transfers, reversals, loan proceeds and bounces removed</div></div>
            <div className="legend"><span><i style={{ background: "var(--c-credit)" }} />Credits</span><span><i style={{ background: "var(--c-debit)" }} />Debits</span><span><i style={{ background: "var(--c-net)", height: 2 }} />Net</span></div>
          </div>
          <div className="card-b chart">
            <ResponsiveContainer>
              <ComposedChart data={months} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--line-2)" />
                <XAxis dataKey="month" tickLine={false} axisLine={{ stroke: "var(--line)" }} />
                <YAxis tickFormatter={(v) => compact(v)} tickLine={false} axisLine={false} width={64} />
                <Tooltip cursor={{ fill: "var(--surface-3)" }} content={<Tip rows={[["credits", "Credits"], ["debits", "Debits"], ["net", "Net"], ["income", "Income"]]} />} />
                <ReferenceLine y={0} stroke="var(--line)" />
                <Bar dataKey="credits" fill="var(--c-credit)" radius={[3, 3, 0, 0]} maxBarSize={26} />
                <Bar dataKey="debits" fill="var(--c-debit)" radius={[3, 3, 0, 0]} maxBarSize={26} />
                <Line dataKey="net" stroke="var(--c-net)" strokeWidth={2} dot={{ r: 3, fill: "var(--surface)", strokeWidth: 2 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <div className="card-h">
            <div><h3>Income by month</h3><div className="hint">{inc?.profile === "SALARIED" ? "Salary credits" : "Business receipts"} in fully covered months</div></div>
            {trend !== undefined && <span className={`pill ${trend < -0.15 ? "crit" : trend < 0 ? "warn" : "ok"}`}>{trend >= 0 ? "+" : ""}{pct(trend)} last 3 mo</span>}
          </div>
          <div className="card-b chart">
            <ResponsiveContainer>
              <ComposedChart data={incomeBars} margin={{ top: 18, right: 8, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--line-2)" />
                <XAxis dataKey="month" tickLine={false} axisLine={{ stroke: "var(--line)" }} />
                <YAxis tickFormatter={(v) => compact(v)} tickLine={false} axisLine={false} width={64} />
                <Tooltip cursor={{ fill: "var(--surface-3)" }} content={<Tip rows={[["value", "Income"]]} />} />
                <Bar dataKey="value" fill="var(--t-income)" radius={[3, 3, 0, 0]} maxBarSize={34} fillOpacity={0.85} />
                {inc?.value ? <ReferenceLine y={inc.value} stroke="var(--ink)" strokeDasharray="5 4"
                  label={{ value: `Estimate ${compact(inc.value)}`, position: "insideTopRight", fill: "var(--ink)", fontSize: 11, fontFamily: "IBM Plex Mono" }} /> : null}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-h">
            <div><h3>Balance trend</h3><div className="hint">End-of-day balance per account on covered days</div></div>
            <div className="legend">{a.accounts.map((ac, i) => <span key={ac.account_id}><i style={{ background: ACCT_COLORS[i % 4] }} />{acctName(ac.account_id)}</span>)}</div>
          </div>
          <div className="card-b chart">
            <ResponsiveContainer>
              <LineChart data={balanceData} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--line-2)" />
                <XAxis dataKey="date" tickFormatter={(d) => shortDate(d)} minTickGap={40} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
                <YAxis tickFormatter={(v) => compact(v)} tickLine={false} axisLine={false} width={64} />
                <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                  <div className="tt"><div className="tt-h">{shortDate(String(label))}</div>
                    {payload.map((p) => <div className="tt-r" key={String(p.dataKey)}><span>{acctName(String(p.dataKey))}</span><span>{money(Number(p.value))}</span></div>)}</div>) : null} />
                <ReferenceLine y={500000} stroke="var(--crit)" strokeDasharray="3 3" label={{ value: "₹5k low", position: "insideBottomRight", fill: "var(--crit)", fontSize: 10 }} />
                {a.accounts.map((ac, i) => <Line key={ac.account_id} type="stepAfter" dataKey={ac.account_id} stroke={ACCT_COLORS[i % 4]} dot={false} strokeWidth={1.8} connectNulls={false} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <div className="card-h">
            <div><h3>Review recommended</h3><div className="hint">Indicators for an analyst, not verdicts</div></div>
            <div className="sev-counts">
              {sev.high > 0 && <SevPill sev="high">{sev.high} high</SevPill>}
              {sev.medium > 0 && <SevPill sev="medium">{sev.medium} medium</SevPill>}
            </div>
          </div>
          <div>
            {riskFlags.length === 0 && <div className="card-b muted">No high or medium indicators.</div>}
            {riskFlags.map((f, i) => (
              <div className="flag" key={i}>
                <span className={`bar ${f.severity}`} />
                <div style={{ minWidth: 0 }}>
                  <div className="flag-title">{f.title}</div>
                  <div className="flag-detail">{f.detail}</div>
                </div>
                {f.txn_ids.length > 0 && <button className="btn sm" onClick={() => onTxns(f.txn_ids, f.title)}>{f.txn_ids.length} txn</button>}
              </div>
            ))}
            <div className="card-b" style={{ paddingTop: 10 }}><button className="btn ghost sm" onClick={onFlags}>All {a.flags.length} indicators <ChevronRight size={14} /></button></div>
          </div>
        </div>
      </div>

      <div className="grid-2e">
        <div className="card">
          <div className="card-h"><div><h3>Recurring patterns</h3><div className="hint">Periodic memory: monthly series, including renamed counterparties</div></div><Repeat size={16} className="muted" /></div>
          <div>
            {patterns.map((p) => (
              <button key={p.pattern_id} className="pattern" style={{ width: "100%", textAlign: "left", background: "none", border: "none", borderBottom: "1px solid var(--line-2)" }}
                      onClick={() => onTxns(p.txn_ids, `${cats[p.cat]?.label ?? p.cat} series`)}>
                <div style={{ minWidth: 0 }}>
                  <div className="row wrap" style={{ gap: 8 }}>
                    <CategoryChip cat={p.cat} />
                    <span className="small" style={{ fontWeight: 500 }}>{p.counterparties.map((c) => c === "<HOLDER>" ? "[Holder]" : c).join(" → ")}</span>
                    {p.counterparties.length > 1 && <span className="pill info">renamed</span>}
                  </div>
                  <div className="small muted" style={{ marginTop: 4 }}>{acctName(p.account_id)} · day ~{p.typical_day} · variation {pct(p.amount_cv, 1)}
                    {p.missed_months.length > 0 && <span className="neg"> · missed {p.missed_months.map(monthLabel).join(", ")}</span>}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="num" style={{ fontWeight: 500 }}>{money(p.median_amount)}</div>
                  <div className="months-dots" style={{ marginTop: 6, justifyContent: "flex-end" }}>
                    {a.months.map((mm) => <span key={mm} className={p.months.includes(mm) ? "on" : p.missed_months.includes(mm) ? "miss" : ""} title={monthLabel(mm)} />)}
                  </div>
                </div>
              </button>
            ))}
            {patterns.length === 0 && <div className="card-b muted">No monthly series detected yet.</div>}
          </div>
        </div>
        <div className="card">
          <div className="card-h"><div><h3>Regular outflows</h3><div className="hint">Median monthly amount by category</div></div></div>
          <table className="tbl">
            <thead><tr><th>Category</th><th className="r">Monthly median</th><th className="r">Months</th></tr></thead>
            <tbody>
              {(m.recurring_obligations?.items ?? []).filter((i) => i.active).map((i) => (
                <tr key={i.counterparty + i.category} className="click" onClick={() => onTxns(i.txn_ids, `${i.label}: ${i.counterparty}`)}>
                  <td><div className="row"><CategoryChip cat={i.category} /><span className="small muted">{i.counterparty}</span></div></td>
                  <td className="r num">{money(i.monthly_amount)}</td><td className="r num">{i.months.length}</td>
                </tr>
              ))}
              {a.regular_outflows.map((r) => (
                <tr key={r.category} className="click" onClick={() => onTxns(r.txn_ids, r.label)}>
                  <td><CategoryChip cat={r.category} /></td><td className="r num">{money(r.monthly_median)}</td><td className="r num">{r.months}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
