"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Check, PenLine, X } from "lucide-react";
import { api, API_URL, hasHandwritingChange, money, PORTALS, STATUS, VERDICT, type ItemDetail } from "@/lib/api";
import { Badge, Button } from "./ui";

export function InvoiceDrawer({ itemId, onClose, onDecided }: {
  itemId: number; onClose: () => void; onDecided?: () => void;
}) {
  const [data, setData] = useState<ItemDetail | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<ItemDetail>(`/api/review/${itemId}`).then(setData).catch((e) => setError(e.message));
  }, [itemId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      await api(`/api/review/${itemId}`, { method: "POST", body: JSON.stringify({ decision, note }) });
      const fresh = await api<ItemDetail>(`/api/review/${itemId}`);
      setData(fresh);
      onDecided?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const item = data?.item;
  const ex = item?.extracted ?? {};
  const verdict = item ? VERDICT[item.verdict] ?? { label: item.verdict, tone: "neutral" as const } : null;
  const status = item ? STATUS[item.status] ?? { label: item.status, tone: "neutral" as const } : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button aria-label="Close" onClick={onClose} className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" />
      <aside className="relative flex h-full w-full max-w-6xl flex-col bg-background shadow-pop">
        <header className="flex items-start justify-between gap-4 border-b border-line bg-surface px-6 py-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-mono text-lg font-semibold">{item?.number ?? "…"}</h2>
              {verdict && <Badge tone={verdict.tone}>{verdict.label}</Badge>}
              {status && <Badge tone={status.tone} dot>{status.label}</Badge>}
              {item && hasHandwritingChange(item) && <Badge tone="warn"><PenLine className="size-3" /> Handwritten change</Badge>}
            </div>
            <p className="mt-1 text-sm text-muted">
              {item?.portal ? PORTALS[item.portal]?.supplier : ""}{ex.po_number ? ` · ${ex.po_number}` : ""}
              {ex.issue_date ? ` · issued ${ex.issue_date}` : ""}
            </p>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-surface-2" aria-label="Close panel"><X className="size-5" /></button>
        </header>

        <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[1.05fr_1fr] lg:overflow-hidden">
          <div className="border-b border-line bg-surface-2 p-5 lg:overflow-y-auto lg:border-b-0 lg:border-r">
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-faint">The invoice, as downloaded</p>
            {item?.pdf ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={`${API_URL}/api/review/${itemId}/page.png`} alt={`Invoice ${item.number}`}
                className="w-full rounded-lg border border-line bg-white shadow-card" />
            ) : <p className="text-sm text-muted">No document stored for this item.</p>}
          </div>

          <div className="space-y-6 p-6 lg:overflow-y-auto">
            {error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
            {item && (
              <>
                <section className="grid grid-cols-2 gap-3">
                  <Figure label="Billed" value={money(ex.total)} />
                  <Figure label="Proposed to pay" value={money(item.payable)} strong />
                </section>

                {hasHandwritingChange(item) && (
                  <section className="flex gap-3 rounded-lg border border-warn/30 bg-warn-soft p-4 text-sm">
                    <PenLine className="mt-0.5 size-4 shrink-0 text-warn" />
                    <div>
                      <p className="font-medium text-warn">Someone changed this invoice by hand</p>
                      <p className="mt-1 text-muted">
                        {(ex.handwritten_notes ?? []).map((n) => `“${n}”`).join(" · ") || "Handwriting on an amount."}{" "}
                        Neither the printed nor the handwritten amount is paid automatically.
                      </p>
                    </div>
                  </section>
                )}

                <section>
                  <h3 className="mb-2 text-sm font-semibold">3-way match</h3>
                  <MatchTable detail={data!} />
                </section>

                <section>
                  <h3 className="mb-2 text-sm font-semibold">Why</h3>
                  <ul className="space-y-1.5 text-sm text-muted">
                    {item.evidence.map((e, i) => (
                      <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-faint" />{e}</li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-faint">
                    Portal check: {item.portal_check === "agree" ? "the total, PO and date on the PDF match the portal’s own listing" : item.portal_check}
                  </p>
                </section>

                <section>
                  <h3 className="mb-2 text-sm font-semibold">What the agent read</h3>
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border border-line bg-surface p-4 text-sm">
                    {[["Document", ex.number], ["Type", ex.doc_type?.replace("_", " ")], ["PO", ex.po_number],
                      ["Issued", ex.issue_date], ["Due", ex.due_date], ["Total", money(ex.total)]].map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-3">
                        <dt className="text-muted">{k}</dt><dd className="tabular font-mono text-[13px]">{v ?? "—"}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              </>
            )}
          </div>
        </div>

        {item && (
          <footer className="border-t border-line bg-surface px-6 py-4">
            {item.decided_at ? (
              <p className="flex items-center gap-2 text-sm text-muted">
                <Check className="size-4 text-ok" /> {STATUS[item.status]?.label} by {item.decided_by} · {new Date(item.decided_at).toLocaleString()}
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the AP log (optional)"
                  className="min-w-0 flex-1 rounded-lg border border-line-strong bg-background px-3 py-2 text-sm outline-none focus:border-brand" />
                <Button variant="danger" disabled={busy} onClick={() => decide("reject")}>Reject</Button>
                <Button disabled={busy || item.payable == null} onClick={() => decide("approve")}
                  title={item.payable == null ? "No amount to approve: resolve with the supplier first" : ""}>
                  <Check className="size-4" /> Approve {item.payable != null ? money(item.payable) : ""}
                </Button>
              </div>
            )}
            <p className="mt-2 text-xs text-faint">Approving marks the invoice as approved for payment in the AP system. Nothing here moves money.</p>
          </footer>
        )}
      </aside>
    </div>
  );
}

function Figure({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`rounded-lg border p-4 ${strong ? "border-brand/30 bg-brand-soft" : "border-line bg-surface"}`}>
      <p className="text-xs text-muted">{label}</p>
      <p className={`tabular mt-1 text-2xl font-semibold tracking-tight ${strong ? "text-brand" : ""}`}>{value}</p>
    </div>
  );
}

function MatchTable({ detail }: { detail: ItemDetail }) {
  const lines = detail.item.extracted?.lines ?? [];
  const order = detail.order;
  if (!order) {
    return (
      <p className="flex items-center gap-2 rounded-lg border border-line bg-surface p-4 text-sm text-muted">
        <AlertTriangle className="size-4 text-warn" /> No purchase order {detail.item.extracted?.po_number ?? ""} in the order system.
      </p>
    );
  }
  const po = Object.fromEntries(order.lines.map((l) => [l.sku, l]));
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full text-sm">
        <thead className="border-b border-line text-left text-xs text-faint">
          <tr>
            <th className="px-3 py-2 font-medium">SKU</th>
            <th className="px-3 py-2 text-right font-medium">Billed</th>
            <th className="px-3 py-2 text-right font-medium">PO</th>
            <th className="px-3 py-2 text-right font-medium">Received</th>
          </tr>
        </thead>
        <tbody className="tabular divide-y divide-line">
          {lines.map((l) => {
            const p = po[l.sku];
            const priceOff = p && Number(l.unit_price) > Number(p.unit_price);
            const qtyOff = p && l.qty > p.received;
            return (
              <tr key={l.sku}>
                <td className="px-3 py-2 font-mono text-[13px]">{l.sku}{!p && <span className="ml-2 text-xs text-bad">not on PO</span>}</td>
                <td className="px-3 py-2 text-right">
                  <span className={qtyOff ? "rounded bg-bad-soft px-1 text-bad" : ""}>{l.qty}</span> ×{" "}
                  <span className={priceOff ? "rounded bg-bad-soft px-1 text-bad" : ""}>{money(l.unit_price)}</span>
                </td>
                <td className="px-3 py-2 text-right text-muted">{p ? <>{p.qty} × {money(p.unit_price)}</> : "—"}</td>
                <td className="px-3 py-2 text-right text-muted">{p ? p.received : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
