import type { Analysis, AuditEntry, CaseSummary, Diff, Evaluation, FileReport, Meta, Txn, TxnDetail } from "./types";

export interface Identity { user: string; role: string }

let identity: Identity = { user: "analyst.demo", role: "analyst" };
export const setIdentity = (i: Identity) => { identity = i; };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-User", identity.user);
  headers.set("X-Role", identity.role);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* not json */ }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

export const api = {
  meta: () => call<Meta>("/api/meta"),
  cases: () => call<CaseSummary[]>("/api/cases"),
  createCase: (body: { name: string; application_date: string; profile: string }) =>
    call<CaseSummary>("/api/cases", { method: "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": newKey() } }),
  loadDemo: () => call<{ cases: string[] }>("/api/demo/load", { method: "POST" }),
  analysis: (id: string) => call<Analysis>(`/api/cases/${id}/analysis`),
  transactions: (id: string) => call<Txn[]>(`/api/cases/${id}/transactions`),
  transaction: (id: string, txn: string) => call<TxnDetail>(`/api/cases/${id}/transactions/${txn}`),
  override: (id: string, txn: string, category: string, reason: string) => {
    const key = newKey();
    return call<{ noop: boolean; reason?: string; diff?: Diff; snapshot_id?: string }>(`/api/cases/${id}/transactions/${txn}/override`, {
      method: "POST", body: JSON.stringify({ category, reason, event_id: key }), headers: { "Idempotency-Key": key },
    });
  },
  reveal: (id: string, txn: string, reason: string) =>
    call<{ description: string }>(`/api/cases/${id}/transactions/${txn}/reveal`, { method: "POST", body: JSON.stringify({ reason }) }),
  files: (id: string) => call<{ files: FileReport[]; upload_events: { filename: string; duplicate: boolean; uploaded_at: string; actor: string }[] }>(`/api/cases/${id}/files`),
  upload: (id: string, file: File, password?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (password) fd.append("password", password);
    return call<{ file: FileReport; snapshot_id: string }>(`/api/cases/${id}/files`, { method: "POST", body: fd });
  },
  evaluation: (id: string) => call<Evaluation>(`/api/cases/${id}/evaluation`),
  audit: (id?: string) => call<{ entries: AuditEntry[]; verification: { ok: boolean; entries: number; head?: string; broken_at?: number } }>(
    `/api/audit${id ? `?case_id=${id}` : ""}`),
};
