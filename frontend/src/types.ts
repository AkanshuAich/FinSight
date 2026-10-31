export type Status = "auto" | "review" | "unclassified" | "confirmed";
export type Severity = "high" | "medium" | "low" | "info";

export interface CategoryMeta {
  label: string;
  dir: "C" | "D" | "B";
  treatment: "income" | "obligation" | "expense" | "excluded" | "other_credit" | "review_credit";
}

export interface Meta {
  categories: Record<string, CategoryMeta>;
  roles: string[];
  versions: Record<string, string>;
  policy: { auto_min_p: number; auto_min_margin: number; review_min_p: number };
  jev_enabled: boolean;
  external_models_allowed: boolean;
}

export interface CaseSummary {
  case_id: string;
  name: string;
  application_date: string;
  profile: string;
  is_demo: boolean;
  n_transactions?: number;
  income?: number | null;
  profile_detected?: string;
  flags_high?: number;
  n_accounts?: number;
  n_files: number;
  months?: string[];
}

export interface Excluded { txn_id: string; reason: string }

export interface Metric {
  key: string;
  label: string;
  unit: "paise" | "ratio";
  value: number | null;
  method: string;
  profile?: string;
  monthly?: { month: string; value: number }[];
  stats?: Record<string, number>;
  items?: { category: string; label: string; counterparty: string; monthly_amount: number; months: string[]; active: boolean; txn_ids: string[] }[];
  trend?: number | null;
  outflows?: number;
  included: string[];
  excluded: Excluded[];
  months_used: string[];
  months_missing: string[];
  notes: string[];
}

export interface MonthRow {
  month: string;
  coverage: "full" | "partial" | "missing";
  coverage_by_account: Record<string, string>;
  credits: number;
  debits: number;
  credits_adjusted: number;
  debits_adjusted: number;
  income: number;
  obligations: number;
  net: number;
  n_txns: number;
  avg_balance: number | null;
  balances: Record<string, { avg: number; min: number; low_days: number; days: number }>;
}

export interface Flag {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  txn_ids: string[];
  months: string[];
  category: "risk" | "data" | "review";
}

export interface Account { account_id: string; acct_masked: string; bank_name: string; holder_masked: string; account_type: string | null }

export interface Statement {
  statement_id: string;
  file_id: string;
  account_id: string;
  acct_masked: string;
  bank_name: string;
  layout: string;
  period_start: string;
  period_end: string;
  opening_paise: number | null;
  opening_source: string;
  closing_stated: number | null;
  computed_closing: number | null;
  total_debits: number;
  total_credits: number;
  recon_status: string;
  recon_diff: number | null;
  n_rows: number;
  n_breaks: number;
}

export interface Pattern {
  pattern_id: string;
  account_id: string;
  direction: "C" | "D";
  label: string;
  counterparties: string[];
  median_amount: number;
  amount_cv: number;
  typical_day: number;
  months: string[];
  missed_months: string[];
  expected_next: string;
  txn_ids: string[];
}

export interface Analysis {
  snapshot_id: string;
  seq: number;
  trigger: string;
  created_at: string;
  versions: Record<string, string>;
  months: string[];
  coverage: Record<string, string>;
  monthly: MonthRow[];
  metrics: Record<string, Metric>;
  regular_outflows: { category: string; label: string; monthly_median: number; months: number; txn_ids: string[] }[];
  balance_series: { date: string; total: number }[];
  account_balance_series: Record<string, { date: string; balance: number }[]>;
  profile: string;
  flags: Flag[];
  accounts: Account[];
  statements: Statement[];
  cross_checks: { account_id: string; kind: string; detail: string }[];
  patterns: Pattern[];
  status_counts: Record<string, number>;
  n_transactions: number;
}

export interface Txn {
  txn_id: string;
  account_id: string;
  txn_date: string;
  description: string;
  debit: number;
  credit: number;
  balance: number | null;
  channel: string;
  counterparty: string;
  recon_status: string;
  recon_note: string;
  acct_masked: string;
  bank_name: string;
  category: string;
  status: Status;
  model_category: string;
  model_status: string;
  tier: string;
  source: string;
  probability: number | null;
  margin: number | null;
  explanation: string;
  attributes: string[];
  override_category: string | null;
  override_reason: string | null;
  override_actor: string | null;
  override_at: string | null;
  direction: "C" | "D";
  amount: number;
  flags: string[];
}

export interface Contribution { signal: string; category: string; value: number; detail: string; weight_share?: number }

export interface TxnDetail {
  txn: Txn;
  classification: {
    category: string;
    status: string;
    probability: number;
    margin: number;
    explanation: string;
    contributions: Contribution[];
    candidates: { category: string; p: number }[];
    attributes: string[];
    source: string;
    tier: string;
  };
  history: { run_id: string; seq: number; created_at: string; category: string; status: string; probability: number; source: string }[];
  sources: { statement_id: string; file_id: string; page_no: number; row_no: number; filename: string; period_start: string; period_end: string }[];
  links: { kind: string; reason: string; txn: Txn }[];
  overrides: { event_id: string; from_category: string; to_category: string; reason: string; actor: string; role: string; created_at: string }[];
  patterns: Pattern[];
}

export interface FileReport {
  file_id: string;
  filename: string;
  kind: string;
  size_bytes: number;
  status: string;
  reason: string | null;
  uploaded_at: string;
  sha256: string;
  pages: { page_no: number; status: string; reason: string; n_rows: number; method: string }[];
  quarantine: { page_no: number | null; row_no: number | null; kind: string; reason: string; detail: string | null }[];
  statements: Statement[];
  duplicate_upload?: boolean;
  edit_check: EditCheck | null;
}

export interface EditSignal { code: string; weight: number; detail: string; evidence: string[] }
export interface EditCheck { score: number; structure_score: number; level: "none" | "low" | "medium" | "high"; signals: EditSignal[] }

export interface Diff {
  metrics: { key: string; label: string; unit: string; before: number | null; after: number | null; method_before?: string; method_after?: string }[];
  transactions: { txn_id: string; before: [string, string]; after: [string, string] }[];
  flags_added: Flag[];
  flags_removed: Flag[];
}

export interface Evaluation {
  available: boolean;
  reason?: string;
  matched: number;
  accuracy: number;
  auto_share: number;
  auto_accuracy: number | null;
  by_status: Record<string, number>;
  per_category: { category: string; label: string; support: number; precision: number | null; recall: number | null }[];
  errors: { txn_id: string; description: string; expected: string; predicted: string; status: string; amount: number; date: string }[];
  reconciliation_pass_rate: number | null;
}

export interface AuditEntry { seq: number; ts: string; actor: string; role: string; action: string; case_id: string | null; target: string | null; details: string; hash: string }
