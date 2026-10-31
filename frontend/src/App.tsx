import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart3, ClipboardCheck, Database, FileStack, FlaskConical, Flag as FlagIcon, ListChecks, Loader2, Moon, Plus, ScrollText, Sparkles, Sun } from "lucide-react";
import { api, setIdentity } from "./api";
import type { Analysis, CaseSummary, Diff, Meta, Txn } from "./types";
import { compact, dateLabel, money, monthLabel, pct } from "./fmt";
import { CatCtx, Empty, useToast } from "./components/ui";
import Overview from "./views/Overview";
import Transactions from "./views/Transactions";
import TxnDrawer from "./views/TxnDrawer";
import MetricDrawer from "./views/MetricDrawer";
import Statements from "./views/Statements";
import Flags from "./views/Flags";
import Review from "./views/Review";
import Accuracy from "./views/Accuracy";
import Audit from "./views/Audit";

type Tab = "overview" | "transactions" | "statements" | "flags" | "review" | "accuracy" | "audit";
const ROLES: Record<string, string> = { analyst: "Credit analyst", senior: "Senior reviewer", auditor: "Auditor (read only)", admin: "Administrator" };

const store = {
  get: (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

export default function App() {
  const toast = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [a, setA] = useState<Analysis | null>(null);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [txnOpen, setTxnOpen] = useState<string | null>(null);
  const [metricOpen, setMetricOpen] = useState<string | null>(null);
  const [preset, setPreset] = useState<{ ids: string[]; label: string } | null>(null);
  const [role, setRole] = useState(store.get("fs.role", "analyst"));
  const [theme, setTheme] = useState(store.get("fs.theme", window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [newCase, setNewCase] = useState<{ name: string; date: string; profile: string } | null>(null);

  useEffect(() => { document.documentElement.dataset.theme = theme; store.set("fs.theme", theme); }, [theme]);
  useEffect(() => { setIdentity({ user: `${role}.demo`, role }); store.set("fs.role", role); }, [role]);

  const refreshCases = useCallback(() => api.cases().then((cs) => { setCases(cs); return cs; }), []);
  const refreshCase = useCallback(async (id: string) => {
    const [an, tx] = await Promise.all([api.analysis(id), api.transactions(id)]);
    setA(an); setTxns(tx);
  }, []);

  useEffect(() => {
    api.meta().then(setMeta);
    refreshCases().then((cs) => { const saved = store.get("fs.case", ""); setCaseId(cs.find((c) => c.case_id === saved)?.case_id ?? cs[0]?.case_id ?? null); });
  }, [refreshCases]);
  useEffect(() => {
    if (!caseId) return;
    store.set("fs.case", caseId);
    setA(null); setTxns([]); setPreset(null); setTxnOpen(null); setMetricOpen(null);
    refreshCase(caseId).catch((e) => toast({ kind: "err", title: "Could not load case", body: String(e.message) }));
  }, [caseId, refreshCase, toast]);

  const canEdit = role !== "auditor";
  const current = cases?.find((c) => c.case_id === caseId) ?? null;
  const reviewCount = useMemo(() => txns.filter((t) => t.status === "review" || t.status === "unclassified").length, [txns]);
  const flagHigh = a?.flags.filter((f) => f.severity === "high").length ?? 0;

  async function loadDemo() {
    setLoadingDemo(true);
    try {
      const r = await api.loadDemo();
      const cs = await refreshCases();
      setCaseId(r.cases[0] ?? cs[0]?.case_id ?? null);
      toast({ title: "Sample cases loaded", body: "Two applicants: a salaried customer with PDF statements from two banks, and a trader with CSV, Excel and JSON statements." });
    } catch (e) { toast({ kind: "err", title: "Could not load samples", body: String((e as Error).message) }); }
    setLoadingDemo(false);
  }

  async function createCase() {
    if (!newCase) return;
    try {
      const c = await api.createCase({ name: newCase.name, application_date: newCase.date, profile: newCase.profile });
      setNewCase(null);
      await refreshCases();
      setCaseId(c.case_id);
      setTab("statements");
    } catch (e) { toast({ kind: "err", title: "Case not created", body: String((e as Error).message) }); }
  }

  const onChanged = useCallback(async (diff: Diff | undefined) => {
    if (!caseId) return;
    await Promise.all([refreshCase(caseId), refreshCases()]);
    if (!diff) return;
    const fmtV = (unit: string, v: number | null) => (unit === "ratio" ? pct(v, 1) : money(v));
    toast({
      title: "Correction applied and figures recalculated",
      body: (
        <>
          {diff.metrics.length === 0 && <span>No headline figure changed.</span>}
          {diff.metrics.map((m) => <div className="delta" key={m.key}><span>{m.label}</span><span>{fmtV(m.unit, m.before)} → {fmtV(m.unit, m.after)}</span></div>)}
          {diff.transactions.length > 0 && <span>{diff.transactions.length} similar transaction(s) re-evaluated using the new example.</span>}
          {diff.flags_added.map((f) => <span key={f.title}>New indicator: {f.title}</span>)}
          {diff.flags_removed.map((f) => <span key={f.title}>Resolved: {f.title}</span>)}
        </>
      ),
    });
  }, [caseId, refreshCase, refreshCases, toast]);

  const showTxns = (ids: string[], label: string) => { setPreset({ ids, label }); setTab("transactions"); setMetricOpen(null); };
  const tabs: [Tab, string, JSX.Element, number?, string?][] = [
    ["overview", "Overview", <BarChart3 size={15} />],
    ["transactions", "Transactions", <ListChecks size={15} />, txns.length],
    ["statements", "Statements", <FileStack size={15} />, a?.statements.length],
    ["flags", "Indicators", <FlagIcon size={15} />, a?.flags.length, flagHigh ? "crit" : undefined],
    ["review", "Review queue", <ClipboardCheck size={15} />, reviewCount, reviewCount ? "warn" : undefined],
    ["accuracy", "Accuracy", <FlaskConical size={15} />],
    ["audit", "Audit log", <ScrollText size={15} />],
  ];

  return (
    <CatCtx.Provider value={meta?.categories ?? {}}>
      <div className="app">
        <aside className="side">
          <div className="brand">
            <div className="brand-mark"><svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 13V3h9M3 8h6.5" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" /></svg></div>
            <div><div className="brand-name">FinSight</div><div className="brand-sub">Statement analysis</div></div>
          </div>
          <div className="side-section stack" style={{ gap: 8 }}>
            <button className="side-btn primary" onClick={() => setNewCase({ name: "", date: new Date().toISOString().slice(0, 10), profile: "UNKNOWN" })} disabled={!canEdit}><Plus size={15} /> New case</button>
            <button className="side-btn" onClick={loadDemo} disabled={loadingDemo || !canEdit}>{loadingDemo ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Load sample cases</button>
          </div>
          <div className="side-label"><span>Cases</span><span>{cases?.length ?? 0}</span></div>
          <div className="side-list">
            {cases?.map((c) => (
              <button key={c.case_id} className={`case-item ${c.case_id === caseId ? "active" : ""}`} onClick={() => { setCaseId(c.case_id); setTab("overview"); }}>
                <span className="case-name">{c.name}</span>
                <span className="case-meta">
                  <span>{c.income ? `${compact(c.income)}/mo` : "No income yet"}</span>
                  <span>· {c.n_files} files</span>
                  {!!c.flags_high && <span className="row" style={{ gap: 4 }}><span className="dot-crit" />{c.flags_high}</span>}
                </span>
              </button>
            ))}
          </div>
          <div className="side-foot">
            <div className="stack" style={{ gap: 4 }}>
              <label htmlFor="role">Acting as</label>
              <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
                {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="side-row">
              <span title="Versions pinned in every analysis">rules {meta?.versions.rules} · weights {meta?.versions.weights} · Jev {meta?.jev_enabled ? "on" : "off"}</span>
              <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle theme">{theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}</button>
            </div>
          </div>
        </aside>

        <main className="main">
          {!current && cases !== null && (
            <div className="content">
              <div className="hero">
                <div className="eyebrow">Bank statement and financial analysis</div>
                <h1>Every figure traceable to the transactions behind it.</h1>
                <p>Upload statements from any bank. FinSight extracts and reconciles every row, removes own-account transfers, refunds and duplicates, classifies each transaction with the evidence shown, and recalculates income and obligations the moment an analyst corrects something.</p>
                <div className="row wrap">
                  <button className="btn primary" onClick={loadDemo} disabled={loadingDemo}>{loadingDemo ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Load sample cases</button>
                  <button className="btn" onClick={() => setNewCase({ name: "", date: new Date().toISOString().slice(0, 10), profile: "UNKNOWN" })}><Plus size={15} /> Start a new case</button>
                </div>
                <div className="feature-grid">
                  <div className="card feature"><b>Deterministic core</b><span>Rules and arithmetic decide. Models only add evidence. Same inputs, same answer.</span></div>
                  <div className="card feature"><b>Nothing silently skipped</b><span>Every page gets a status; unreadable rows are quarantined with a reason.</span></div>
                  <div className="card feature"><b>PII masked by default</b><span>Account numbers, UPI IDs and phones are tokenised. Unmasking is logged.</span></div>
                </div>
              </div>
            </div>
          )}
          {current && (
            <>
              <header className="topbar">
                <div className="topbar-row">
                  <div style={{ minWidth: 0 }}>
                    <div className="eyebrow">Case {current.case_id.slice(2, 8).toUpperCase()} · applied {dateLabel(current.application_date)}</div>
                    <h1 className="title">{current.name}</h1>
                    <div className="subline">
                      {a?.accounts.map((ac) => <span key={ac.account_id}><b>{ac.bank_name}</b> {ac.acct_masked}{ac.account_type ? ` · ${ac.account_type.toLowerCase()}` : ""}</span>)}
                      {a && a.months.length > 0 && <span>{monthLabel(a.months[0])} – {monthLabel(a.months[a.months.length - 1])}</span>}
                    </div>
                  </div>
                  {a && (
                    <div className="stack" style={{ justifyItems: "end", gap: 6 }}>
                      <span className="pill info">{a.profile === "SALARIED" ? "Salaried profile" : "Self-employed profile"}</span>
                      <span className="small muted mono" title="Content-addressed snapshot: identical inputs give the same id">snapshot {a.snapshot_id.slice(5, 13)} · v{a.seq}</span>
                    </div>
                  )}
                </div>
                <nav className="tabs" aria-label="Case sections">
                  {tabs.map(([k, label, icon, count, tone]) => (
                    <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)} aria-current={tab === k}>
                      {icon}{label}{count !== undefined && count > 0 && <span className={`count ${tone ?? ""}`}>{count}</span>}
                    </button>
                  ))}
                </nav>
              </header>
              <div className="content">
                {!a && <div className="content-inner"><div className="kpis">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 130 }} />)}</div><div className="skeleton" style={{ height: 320 }} /></div>}
                {a && a.n_transactions === 0 && tab === "overview" && (
                  <div className="content-inner"><Empty icon={<Database size={32} />} title="No transactions yet">Upload bank statements in the Statements tab. Results appear here once at least one file is processed.</Empty>
                    <div style={{ textAlign: "center" }}><button className="btn primary" onClick={() => setTab("statements")}>Go to Statements</button></div></div>
                )}
                {a && a.n_transactions > 0 && tab === "overview" && <Overview a={a} txns={txns} onMetric={setMetricOpen} onFlags={() => setTab("flags")} onTxns={showTxns} onStatements={() => setTab("statements")} />}
                {a && tab === "transactions" && <Transactions txns={txns} accounts={a.accounts} preset={preset} onClearPreset={() => setPreset(null)} onOpen={setTxnOpen} selected={txnOpen} />}
                {tab === "statements" && caseId && <Statements caseId={caseId} a={a} canUpload={canEdit} onUploaded={() => { refreshCase(caseId); refreshCases(); }} />}
                {a && tab === "flags" && <Flags flags={a.flags} onTxns={showTxns} />}
                {a && tab === "review" && caseId && <Review caseId={caseId} txns={txns} canEdit={canEdit} onOpen={setTxnOpen} onChanged={onChanged} />}
                {tab === "accuracy" && caseId && <Accuracy caseId={caseId} version={a?.snapshot_id ?? ""} onOpen={setTxnOpen} />}
                {tab === "audit" && caseId && <Audit caseId={caseId} role={role} version={a?.snapshot_id ?? ""} />}
              </div>
            </>
          )}
        </main>
      </div>

      {txnOpen && caseId && <TxnDrawer caseId={caseId} txnId={txnOpen} canEdit={canEdit} onClose={() => setTxnOpen(null)} onOpen={setTxnOpen} onChanged={onChanged} />}
      {metricOpen && a?.metrics[metricOpen] && <MetricDrawer metric={a.metrics[metricOpen]} txns={txns} onClose={() => setMetricOpen(null)} onOpen={(id) => { setMetricOpen(null); setTxnOpen(id); }} />}

      {newCase && (
        <>
          <div className="scrim" onClick={() => setNewCase(null)} />
          <div className="modal" role="dialog" aria-modal="true">
            <h3 style={{ fontSize: 19 }}>New case</h3>
            <div className="form-grid">
              <label className="label" htmlFor="nc-name">Applicant</label>
              <input id="nc-name" className="input" autoFocus value={newCase.name} onChange={(e) => setNewCase({ ...newCase, name: e.target.value })} placeholder="Name or business name" />
              <label className="label" htmlFor="nc-date">Application date</label>
              <input id="nc-date" className="input" type="date" value={newCase.date} onChange={(e) => setNewCase({ ...newCase, date: e.target.value })} />
              <label className="label" htmlFor="nc-prof">Declared profile</label>
              <select id="nc-prof" className="select" value={newCase.profile} onChange={(e) => setNewCase({ ...newCase, profile: e.target.value })}>
                <option value="UNKNOWN">Not stated</option><option value="SALARIED">Salaried</option><option value="SELF_EMPLOYED">Self-employed / business</option>
              </select>
            </div>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setNewCase(null)}>Cancel</button>
              <button className="btn primary" disabled={!newCase.name.trim()} onClick={createCase}>Create and upload statements</button>
            </div>
          </div>
        </>
      )}
    </CatCtx.Provider>
  );
}
