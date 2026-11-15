"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PenLine } from "lucide-react";
import { api, hasHandwritingChange, money, moneySummary, PORTALS, STATUS, VERDICT, type ReviewItem } from "@/lib/api";
import { Badge, Card, Empty, PageHeader, Stat } from "@/components/ui";
import { InvoiceDrawer } from "@/components/invoice-drawer";

const TABS = ["needs_human", "proposed", "approved_for_payment", "rejected"] as const;

export default function ReviewPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("needs_human");
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<ReviewItem[]>("/api/review").then(setItems).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  const s = useMemo(() => moneySummary(items), [items]);
  const shown = items.filter((i) => i.status === tab);

  return (
    <div>
      <PageHeader eyebrow="Review queue" title="Exceptions, with the evidence next to the invoice">
        The agent proposes; a person decides. Open any invoice to see the document, what the agent read and the
        3-way match line by line.
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Waiting for a person" value={s.review.length} note={`${money(s.reviewBilled)} billed`} tone="warn" />
        <Stat label="Proposed for payment" value={money(s.proposed)} note="matched to PO and receipt" />
        <Stat label="Overbilling caught" value={money(s.caught)} note="price above PO, short deliveries, duplicates" tone="ok" />
        <Stat label="Approved for payment" value={money(s.approved)} note="by a person, in this console" />
      </div>

      <div className="mt-10 flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => {
          const n = items.filter((i) => i.status === t).length;
          return (
            <button key={t} onClick={() => setTab(t)}
              className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm transition ${tab === t ? "border-brand font-medium text-foreground" : "border-transparent text-muted hover:text-foreground"}`}>
              {STATUS[t].label}
              <span className="tabular rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">{n}</span>
            </button>
          );
        })}
      </div>

      {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}

      <Card className="mt-4 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="px-5 py-3 font-medium">Invoice</th>
                <th className="px-5 py-3 font-medium">Supplier</th>
                <th className="px-5 py-3 font-medium">Finding</th>
                <th className="px-5 py-3 text-right font-medium">Billed</th>
                <th className="px-5 py-3 text-right font-medium">Proposed</th>
                <th className="px-5 py-3 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((i) => {
                const v = VERDICT[i.verdict] ?? { label: i.verdict, tone: "neutral" as const };
                return (
                  <tr key={i.item_id} onClick={() => setOpen(i.item_id)} className="cursor-pointer align-top hover:bg-surface-2">
                    <td className="whitespace-nowrap px-5 py-3.5 font-mono font-medium">{i.number}</td>
                    <td className="px-5 py-3.5 text-muted">{i.portal ? PORTALS[i.portal]?.supplier : "—"}</td>
                    <td className="whitespace-nowrap px-5 py-3.5">
                      <div className="flex gap-1.5">
                        <Badge tone={v.tone}>{v.label}</Badge>
                        {hasHandwritingChange(i) && <Badge tone="warn"><PenLine className="size-3" /> Ink</Badge>}
                      </div>
                    </td>
                    <td className="tabular px-5 py-3.5 text-right text-muted">{money(i.extracted?.total)}</td>
                    <td className="tabular px-5 py-3.5 text-right font-medium">{money(i.payable)}</td>
                    <td className="max-w-sm px-5 py-3.5 text-xs leading-relaxed text-muted">{i.evidence[0]}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {shown.length === 0 && <Empty>Nothing in “{STATUS[tab].label}”.</Empty>}
      </Card>

      {open != null && <InvoiceDrawer key={open} itemId={open} onClose={() => setOpen(null)} onDecided={load} />}
    </div>
  );
}
