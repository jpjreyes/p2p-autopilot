export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8062";

export type Run = {
  run_id: string;
  portal: string;
  chaos: string;
  status: "running" | "done" | "handoff" | "budget" | "error";
  reason: string;
  downloads: number;
  calls: number;
  seconds: string | null;
  started_at: string;
};

export type Action = {
  action: string;
  role?: string;
  name?: string;
  mark?: number;
  nth?: number;
  value?: string;
  text?: string;
  reason?: string;
};

export type Step = {
  idx: number;
  n: number;
  action: Action;
  ok: boolean;
  result: string;
  has_shot: boolean;
};

export type Extracted = {
  doc_type?: string;
  number?: string;
  po_number?: string;
  issue_date?: string;
  due_date?: string;
  total?: string;
  lines?: { sku: string; qty: number; unit_price: string }[];
  handwritten_notes?: string[];
  amount_changed_by_hand?: boolean;
};

export type ReviewItem = {
  item_id: number;
  run_id: string;
  number: string;
  status: "proposed" | "needs_human" | "no_action" | "approved_for_payment" | "rejected";
  verdict: string;
  payable: string | null;
  evidence: string[];
  portal_check: string;
  decided_by: string | null;
  decided_at: string | null;
  pdf?: string;
  extracted?: Extracted;
  portal?: string;
};

export type OrderLine = { sku: string; description: string; qty: number; unit_price: string; received: number };
export type ItemDetail = { item: ReviewItem; order: { po_number: string; lines: OrderLine[] } | null };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const CLIENT = "Northline Distribution";

export const PORTALS: Record<string, { name: string; supplier: string }> = {
  a: { name: "Acme SupplierNet", supplier: "Acme Fasteners Inc." },
  b: { name: "Valvex B2B Portal", supplier: "Valvex Industrial GmbH" },
  c: { name: "SafeGuard Vendor Center", supplier: "SafeGuard Supply Co." },
  d: { name: "Keystone Customer Access", supplier: "Keystone Electrical Supply" },
};

export const CHAOS: Record<string, { label: string; hint: string }> = {
  "": { label: "Normal day", hint: "The portal as it is today." },
  layout_variant: { label: "Portal redesign", hint: "Buttons renamed, columns reordered." },
  renamed_fields: { label: "Renamed columns", hint: "“Invoice No.” becomes “Document #”." },
  session_expiry: { label: "Session expires", hint: "Logged out after the first download." },
  slow: { label: "Slow portal", hint: "Every page takes 2–4 seconds." },
  captcha: { label: "CAPTCHA", hint: "Unsolvable on purpose: the agent must hand off." },
  icon_links: { label: "Unlabeled icons", hint: "PDF and “mail a paper copy” look alike." },
  opaque_icons: { label: "Icons with hidden URLs", hint: "Only the picture tells them apart (Acme only)." },
  injection: { label: "Prompt injection", hint: "Invoices that tell the agent to approve them." },
  scanned: { label: "Scanned invoices", hint: "No text layer: read from the image." },
  handwritten: { label: "Handwritten corrections", hint: "Totals struck through and rewritten in pen." },
};

export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  match: { label: "Matches PO and receipt", tone: "ok" },
  price_above_po: { label: "Price above PO", tone: "bad" },
  qty_above_received: { label: "Billed more than received", tone: "bad" },
  duplicate: { label: "Duplicate invoice", tone: "bad" },
  unknown_po: { label: "Unknown PO", tone: "warn" },
  credit_note: { label: "Credit note", tone: "neutral" },
  portal_mismatch: { label: "PDF disagrees with portal", tone: "warn" },
  extraction_failed: { label: "Could not read PDF", tone: "warn" },
  total_mismatch: { label: "Lines don’t add up", tone: "bad" },
  line_not_on_po: { label: "Item not on PO", tone: "bad" },
  already_paid: { label: "Already paid", tone: "neutral" },
};

export const STATUS: Record<string, { label: string; tone: Tone }> = {
  proposed: { label: "Proposed for payment", tone: "ok" },
  needs_human: { label: "Needs review", tone: "warn" },
  no_action: { label: "No action", tone: "neutral" },
  approved_for_payment: { label: "Approved", tone: "brand" },
  rejected: { label: "Rejected", tone: "bad" },
};

export const RUN_STATUS: Record<string, { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "accent" },
  done: { label: "Completed", tone: "ok" },
  handoff: { label: "Handed to a person", tone: "warn" },
  budget: { label: "Out of steps", tone: "bad" },
  error: { label: "Error", tone: "bad" },
};

export type Tone = "ok" | "warn" | "bad" | "neutral" | "brand" | "accent";

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return n.toLocaleString("en-US", { style: "currency", currency: "EUR" });  // SAP amounts (D17)
}

export function hasHandwritingChange(i: ReviewItem): boolean {
  return Boolean(i.extracted?.amount_changed_by_hand) || i.evidence.some((e) => e.startsWith("handwritten change"));
}

/** One sentence a non-engineer can read, for each step in the replay. */
export function describeStep(s: Step): { title: string; detail?: string } {
  const a = s.action;
  const target = a.name ? `“${a.name}”` : a.text ? `“${a.text}”` : a.mark != null ? `box ${a.mark}` : "an element";
  if (!s.ok) return { title: `Tried to ${a.action} ${target}`, detail: s.result };
  switch (a.action) {
    case "fill":
      if (a.value?.includes("{{password}}")) return { title: "Entered the password", detail: "Filled in by code; the model never sees it." };
      if (a.value?.includes("{{username}}")) return { title: "Entered the username" };
      return { title: `Typed into ${target}` };
    case "click":
      return { title: `Clicked ${target}`, detail: s.result.includes("new tab") ? s.result : undefined };
    case "select":
      return { title: `Chose “${a.value}”` };
    case "download": {
      const m = s.result.match(/downloaded (\S+?)\.pdf/);
      return { title: m ? `Downloaded ${m[1]}` : "Downloaded a PDF" };
    }
    case "goto":
      return { title: "Opened a page", detail: s.result.replace(/^opened /, "") };
    case "look":
      return { title: "Took an annotated screenshot", detail: s.result.replace("look: ", "") + " numbered for exact clicks" };
    case "done":
      return { title: "Finished: every open invoice collected" };
    case "handoff":
      return { title: "Handed off to a person" };
    default:
      return { title: `${a.action} ${target}` };
  }
}

const sum = (xs: (string | null | undefined)[]) => xs.reduce((a, x) => a + (x ? Number(x) : 0), 0);

export function moneySummary(items: ReviewItem[]) {
  const caught = items.reduce((a, i) => {
    const billed = Number(i.extracted?.total ?? 0);
    if (i.verdict === "duplicate") return a + billed;
    if ((i.verdict === "price_above_po" || i.verdict === "qty_above_received") && i.payable != null) return a + billed - Number(i.payable);
    return a;
  }, 0);
  return {
    proposed: sum(items.filter((i) => i.status === "proposed").map((i) => i.payable)),
    review: items.filter((i) => i.status === "needs_human"),
    reviewBilled: sum(items.filter((i) => i.status === "needs_human").map((i) => i.extracted?.total)),
    approved: sum(items.filter((i) => i.status === "approved_for_payment").map((i) => i.payable)),
    caught,
  };
}

export type ProcessOverview = {
  data_end: string;
  totals: { lines: number; eur: number; vendors: number; first_day: string };
  summary: { metric: string; value: number; eur: number | null; note: string }[];
  by_match_type: { match_type: string; lines: number; eur: number; paid_before_gr: number; eur_paid_before_gr: number }[];
  bottlenecks: { from_activity: string; to_activity: string; n_waits: number; median_days: number; p90_days: number;
    pct_of_all_waiting: number }[];
};

type Scores = { roc_auc: number; avg_precision: number; "at_precision_0.6": { recall: number }; "at_precision_0.8": { recall: number } };
export type RiskItem = { case_id: string; vendor: string; eur: number; invoice_recorded: string; p_block: number; reasons: string[] };
export type Risk = {
  summary: { open_scored: number; flagged: number; eur_flagged: number };
  items: RiskItem[];
  model: { question: string; test_window: string; test_rows: number; base_rate: number; model: Scores;
    rule_invoice_before_gr: Scores; vendor_rate: Scores; at_po_creation: Scores;
    business?: { daily_top10_right: number; daily_top20_right: number; invoices_per_day: number;
      eur_model_strict: number; eur_rule: number; eur_model_wide: number; eur_blocked_total: number } } | null;
};

export type BriefSection = { title: string; sql: string; columns: string[]; rows: unknown[][] };
export type Brief = { week: [string, string]; sections: Record<string, BriefSection>;
  summary?: { headline: string; bullets: string[] }; unverified_numbers?: string[] };

export function eur(n: number | null | undefined, compact = false): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "EUR", maximumFractionDigits: 0,
    ...(compact ? { notation: "compact" } : {}) });
}
