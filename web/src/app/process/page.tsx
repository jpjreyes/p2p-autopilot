"use client";

import { useEffect, useState } from "react";
import { api, eur, type ProcessOverview } from "@/lib/api";
import { Card, PageHeader, Stat } from "@/components/ui";

const DECISIONS_URL = "https://github.com/jpreyesm03/p2p-autopilot/blob/main/DECISIONS.md";

export default function ProcessPage() {
  const [d, setD] = useState<ProcessOverview | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<ProcessOverview>("/api/process/overview").then(setD).catch((e) => setErr(String(e))); }, []);
  if (err) return <p className="text-bad">{err}</p>;
  if (!d) return <p className="text-muted">Loading the process…</p>;

  const metric = (prefix: string) => d.summary.find((s) => s.metric.startsWith(prefix));
  const paidEarly = metric("paid before any goods receipt");
  const openLong = metric("open longer");
  const openAll = metric("open invoices");

  return (
    <div className="space-y-12">
      <PageHeader eyebrow="See · the real SAP process" title="Purchase-to-pay, as it actually ran">
        {d.totals.lines.toLocaleString()} purchase-order lines from {d.totals.vendors.toLocaleString()} vendors
        ({d.totals.first_day} to {d.data_end}), worth {eur(d.totals.eur, true)}: the public BPI Challenge 2019 log of a
        coatings manufacturer&apos;s SAP system. Every number below is a SQL query on that log; how each one is defined
        is in <a href={DECISIONS_URL} className="text-brand underline underline-offset-2">DECISIONS.md</a>.
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Paid before any goods receipt" value={eur(paidEarly?.eur)} tone="bad"
          note={`${paidEarly?.value.toLocaleString()} lines where the 3-way match should have held payment`} />
        <Stat label="Open longer than the vendor usually takes" value={eur(openLong?.eur)} tone="warn"
          note={`${openLong?.value.toLocaleString()} invoices beyond 90% of that vendor's paid invoices`} />
        <Stat label="Open invoices" value={eur(openAll?.eur, true)}
          note={`${openAll?.value.toLocaleString()} invoices with goods and invoice in, not paid`} />
        <Stat label="Biggest wait" value={`${d.bottlenecks[0]?.pct_of_all_waiting}%`}
          note={`of all waiting: ${d.bottlenecks[0]?.from_activity} → ${d.bottlenecks[0]?.to_activity}`} />
      </div>

      <section>
        <h2 className="text-lg font-semibold tracking-tight">Compliance by match type</h2>
        <p className="mb-4 mt-1 text-sm text-muted">
          The match type decides what must happen before paying: 3-way needs a goods receipt, 2-way doesn&apos;t,
          consignment has no invoice per line. The agent&apos;s 3-way match applies the same rule to supplier invoices.
        </p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Match type</th>
                  <th className="px-5 py-3 text-right font-medium">Lines</th>
                  <th className="px-5 py-3 text-right font-medium">Value</th>
                  <th className="px-5 py-3 text-right font-medium">Paid before goods receipt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {d.by_match_type.map((m) => (
                  <tr key={m.match_type}>
                    <td className="px-5 py-3 font-medium">{m.match_type}</td>
                    <td className="tabular px-5 py-3 text-right">{m.lines.toLocaleString()}</td>
                    <td className="tabular px-5 py-3 text-right">{eur(m.eur, true)}</td>
                    <td className="tabular px-5 py-3 text-right">
                      {m.match_type.startsWith("3-way")
                        ? <>{m.paid_before_gr.toLocaleString()} {m.paid_before_gr === 1 ? "line" : "lines"} · {eur(m.eur_paid_before_gr)}</>
                        : <span className="text-faint">not required</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section>
        <h2 className="text-lg font-semibold tracking-tight">Where the waiting goes</h2>
        <p className="mb-4 mt-1 text-sm text-muted">Gaps between consecutive steps on lines that were paid (first payment cycle).</p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">From → to</th>
                  <th className="px-5 py-3 text-right font-medium">Times</th>
                  <th className="px-5 py-3 text-right font-medium">Median days</th>
                  <th className="px-5 py-3 text-right font-medium">p90 days</th>
                  <th className="px-5 py-3 text-right font-medium">Share of all waiting</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {d.bottlenecks.map((b) => (
                  <tr key={b.from_activity + b.to_activity}>
                    <td className="px-5 py-3">{b.from_activity} → {b.to_activity}</td>
                    <td className="tabular px-5 py-3 text-right">{b.n_waits.toLocaleString()}</td>
                    <td className="tabular px-5 py-3 text-right">{b.median_days}</td>
                    <td className="tabular px-5 py-3 text-right">{b.p90_days}</td>
                    <td className="tabular px-5 py-3 text-right">{b.pct_of_all_waiting}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>
    </div>
  );
}
