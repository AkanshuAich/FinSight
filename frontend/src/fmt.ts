const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** paise -> "₹1,23,456" */
export const money = (paise: number | null | undefined, exact = false) =>
  paise === null || paise === undefined ? "—" : (exact ? inr2 : inr0).format(paise / 100);

/** paise -> "₹4.2L", "₹1.1Cr", "₹850" for chart axes and dense UI */
export function compact(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  const r = paise / 100;
  const a = Math.abs(r);
  const sign = r < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e6 ? 1 : 2)}L`;
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(1)}k`;
  return `${sign}₹${a.toFixed(0)}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthLabel = (m: string) => {
  const [y, mm] = m.split("-");
  return `${MONTHS[Number(mm) - 1]} ${y.slice(2)}`;
};
export const dateLabel = (d: string) => {
  const [y, m, dd] = d.slice(0, 10).split("-");
  return `${dd} ${MONTHS[Number(m) - 1]} ${y}`;
};
export const shortDate = (d: string) => {
  const [, m, dd] = d.slice(0, 10).split("-");
  return `${dd} ${MONTHS[Number(m) - 1]}`;
};
export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`);
export const bytes = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
