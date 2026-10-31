import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import type { CategoryMeta, Severity, Status } from "../types";

export const CatCtx = createContext<Record<string, CategoryMeta>>({});
export const useCats = () => useContext(CatCtx);

export function CategoryChip({ cat }: { cat: string }) {
  const cats = useCats();
  const m = cats[cat];
  if (cat === "UNCLASSIFIED") return <span className="chip unclassified">Unclassified</span>;
  return <span className={`chip t-${m?.treatment ?? "expense"}`}>{m?.label ?? cat}</span>;
}

const STATUS_LABEL: Record<Status, string> = { auto: "Automatic", confirmed: "Analyst confirmed", review: "Needs review", unclassified: "Unclassified" };
export function StatusDot({ status }: { status: Status }) {
  return <span className={`status-dot ${status}`} title={STATUS_LABEL[status]} aria-label={STATUS_LABEL[status]} />;
}
export const statusLabel = (s: Status) => STATUS_LABEL[s] ?? s;

export function SevPill({ sev, children }: { sev: Severity; children?: ReactNode }) {
  const cls = sev === "high" ? "crit" : sev === "medium" ? "warn" : sev === "low" ? "info" : "";
  return <span className={`pill ${cls}`}><span className="d" />{children ?? sev}</span>;
}

export function ReconPill({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    reconciled: ["ok", "Reconciled"],
    reconciled_with_row_breaks: ["warn", "Totals match · row break"],
    reconciled_no_closing: ["info", "No closing balance stated"],
    unreconciled: ["crit", "Does not reconcile"],
    breaks: ["warn", "Row breaks"],
    unverified: ["info", "Cannot verify"],
  };
  const [cls, label] = map[status] ?? ["", status];
  return <span className={`pill ${cls}`}><span className="d" />{label}</span>;
}

export function Drawer({ title, sub, onClose, children, actions }: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <div className="drawer-h">
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">{sub}</div>
            <h2 style={{ fontSize: 20, marginTop: 2 }}>{title}</h2>
          </div>
          <div className="row">{actions}<button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button></div>
        </div>
        <div className="drawer-b">{children}</div>
      </aside>
    </>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return <div className="empty">{icon}<h2>{title}</h2><div style={{ maxWidth: 520 }}>{children}</div></div>;
}

// ---------------------------------------------------------------- toasts
export interface Toast { id: number; kind?: "ok" | "err"; title: string; body?: ReactNode }
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.kind === "err" ? 7000 : 9000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "err" ? "err" : ""}`}>
            <b>{t.title}</b>
            {t.body}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
