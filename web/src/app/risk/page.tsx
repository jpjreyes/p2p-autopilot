"use client";

import { useEffect, useState } from "react";
import { api, eur, type Risk } from "@/lib/api";
import { Badge, Card, PageHeader, Stat } from "@/components/ui";

const pct = (x: number) => `${Math.round(x * 100)}%`;

export default function RiskPage() {
  const [d, setD] = useState<Risk | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Risk>("/api/process/risk?limit=40").then(setD).catch((e) => setErr(String(e))); }, []);
  if (err) return <p className="text-bad">{err}</p>;
  if (!d) return <p className="text-muted">Loading the worklist…</p>;
  const m = d.model;

  return (
    <div className="space-y-12">
      <PageHeader eyebrow="Predict · payment blocks" title="Invoices likely to be blocked, before they are">
        A blocked invoice waits about 6 days for someone to remove the block. A model trained on the SAP log flags,
        when an invoice arrives, the ones likely to be blocked, so the buyer can fix the cause first. Each flag says
        why. Open invoices at the end of the data; flagged at the threshold that was 80% precise in calibration.
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Flagged now" value={d.summary.flagged.toLocaleString()} tone="warn"
          note={`of ${d.summary.open_scored.toLocaleString()} open invoices scored`} />
        <Stat label="Value flagged" value={eur(d.summary.eur_flagged)} />
        {m?.business && <Stat label="Daily top 10 that really get blocked" value={pct(m.business.daily_top10_right)} tone="ok"
          note={`of ~${Math.round(m.business.invoices_per_day)} new invoices a day; top 20: ${pct(m.business.daily_top20_right)}`} />}
        {m?.business && <Stat label="Blocked money found, vs the best rule" value={`${(m.business.eur_model_strict / m.business.eur_rule).toFixed(1)}×`}
          note={`${eur(m.business.eur_model_strict, true)} vs ${eur(m.business.eur_rule, true)} at the rule's precision; ${eur(m.business.eur_model_wide, true)} of ${eur(m.business.eur_blocked_total, true)} at a wider setting`} />}
      </div>

      <section>
        <h2 className="text-lg font-semibold tracking-tight">Worklist</h2>
        <p className="mb-4 mt-1 text-sm text-muted">Highest risk first (ties by value), the way a clerk would work the list. Reasons are the three facts that pushed each score up most.</p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">PO line</th>
                  <th className="px-5 py-3 font-medium">Vendor</th>
                  <th className="px-5 py-3 text-right font-medium">Value</th>
                  <th className="px-5 py-3 font-medium">Invoice</th>
                  <th className="px-5 py-3 font-medium">Chance of block</th>
                  <th className="px-5 py-3 font-medium">Why</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {d.items.map((i) => (
                  <tr key={i.case_id} className="align-top">
                    <td className="tabular px-5 py-3 font-medium">{i.case_id.replace("_", " · ")}</td>
                    <td className="px-5 py-3 text-muted">{i.vendor.replace("vendorID_", "Vendor ")}</td>
                    <td className="tabular px-5 py-3 text-right">{eur(i.eur)}</td>
                    <td className="tabular px-5 py-3 text-muted">{i.invoice_recorded}</td>
                    <td className="px-5 py-3"><Badge tone={i.p_block >= 0.8 ? "bad" : "warn"}>{pct(i.p_block)}</Badge></td>
                    <td className="px-5 py-3">
                      <ul className="space-y-0.5 text-[13px] text-muted">{i.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      {m && (
        <section>
          <h2 className="text-lg font-semibold tracking-tight">How good is it?</h2>
          <p className="mb-4 mt-1 text-sm text-muted">
            Scored once on {m.test_window}: {m.test_rows.toLocaleString()} invoices, {pct(m.base_rate)} of them blocked.
            Trained only on earlier months; vendor history only from months whose outcomes were already known.
          </p>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Approach</th>
                  <th className="px-5 py-3 text-right font-medium">Avg precision</th>
                  <th className="px-5 py-3 text-right font-medium">Caught at 60% precision</th>
                  <th className="px-5 py-3 text-right font-medium">Caught at 80% precision</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {([["Rule: a line on the invoice has no goods receipt yet", m.rule_invoice_before_gr],
                  ["Model at invoice receipt", m.model],
                  ["Model at PO creation (earliest warning)", m.at_po_creation]] as const).map(([label, s]) => (
                  <tr key={label}>
                    <td className="px-5 py-3">{label}</td>
                    <td className="tabular px-5 py-3 text-right">{s.avg_precision.toFixed(2)}</td>
                    <td className="tabular px-5 py-3 text-right">{pct(s["at_precision_0.6"].recall)}</td>
                    <td className="tabular px-5 py-3 text-right">{pct(s["at_precision_0.8"].recall)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <p className="mt-3 text-sm text-muted">
            At PO creation there is no usable signal beyond the vendor&apos;s history: the useful warning point is when
            the invoice arrives. And blocks that a person (not SAP itself) has to clear are no more predictable than
            the vendor&apos;s history; the model&apos;s edge is in blocks caused by goods not yet received.
          </p>
        </section>
      )}
    </div>
  );
}
