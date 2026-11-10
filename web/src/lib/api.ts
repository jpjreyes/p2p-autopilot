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

export type Step = {
  idx: number;
  n: number;
  action: { action: string; role?: string; name?: string; mark?: number; nth?: number; value?: string; reason?: string };
  ok: boolean;
  result: string;
  has_shot: boolean;
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
};

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

export const PORTALS: Record<string, string> = { a: "Acme SupplierNet", b: "Valvex B2B Portal" };

export const CHAOS: Record<string, string> = {
  "": "No failure",
  layout_variant: "Layout redesign",
  renamed_fields: "Renamed columns",
  session_expiry: "Session expires mid-run",
  slow: "Slow pages",
  captcha: "CAPTCHA (must hand off)",
  icon_links: "Unlabeled icons (needs vision)",
};

export const VERDICT_LABEL: Record<string, string> = {
  match: "Matches PO and receipt",
  price_above_po: "Price above PO",
  qty_above_received: "Billed more than received",
  duplicate: "Duplicate invoice",
  unknown_po: "Unknown PO",
  credit_note: "Credit note",
  portal_mismatch: "PDF disagrees with portal",
  extraction_failed: "Could not read PDF",
  total_mismatch: "Lines don't add up",
  line_not_on_po: "Item not on PO",
  already_paid: "Already paid (AP ledger)",
};
