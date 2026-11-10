"use client";

import { useEffect, useState } from "react";
import { Check, Minus, X } from "lucide-react";
import { CHAOS, PORTALS } from "@/lib/api";
import { Card, PageHeader, Stat } from "@/components/ui";

type Cell = {
  variant: string; portal: string; mode: string; latest_pass: boolean; latest_docs_right: string | null;
  runs: number; passed: number; unsafe: number; side_effects: number; latest_side_effects: number; calls_median: number; seconds_median: number;
  nav_usd: number | null; hw_caught: string | null;
};
type Evals = { generated_at: string; totals: { runs: number; unsafe: number; side_effects_full: number }; cells: Cell[] };

const MODES = ["none", "layout_variant", "renamed_fields", "session_expiry", "slow", "captcha", "icon_links",
  "opaque_icons", "injection", "scanned", "handwritten"];
const VARIANTS: [string, string, string][] = [
  ["full", "Production agent", "accessibility tree + screenshots, up to 5 actions per call"],
  ["no_look", "Screen reading only", "no screenshots"],
  ["batch1", "One action per call", "no batching"],
];
const DECISIONS_URL = "https://github.com/jpreyesm03/legacy-portal-agent/blob/main/DECISIONS.md";

function modeLabel(m: string) {
  return m === "none" ? "Normal day" : CHAOS[m]?.label ?? m;
}

export default function EvalsPage() {
  const [d, setD] = useState<Evals | null>(null);
  useEffect(() => { fetch("/evals.json").then((r) => r.json()).then(setD).catch(() => {}); }, []);
  if (!d) return <p className="text-muted">Loading results…</p>;

  const get = (v: string, p: string, m: string) => d.cells.find((c) => c.variant === v && c.portal === p && c.mode === m);

  return (
    <div className="space-y-12">
      <PageHeader eyebrow="Evals" title="Every test the agent has run, including the ones it failed">
        Generated invoices with known answers, so every verdict and every dollar is scored. A run passes only if the
        agent finishes, every document gets the right verdict, nothing unsafe is proposed and nothing unwanted
        happens on the portal. Failures led to fixes; the reasoning for each is in{" "}
        <a href={DECISIONS_URL} className="text-brand underline underline-offset-2">DECISIONS.md</a>.
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Eval runs" value={d.totals.runs} note="each one: a full portal, 20 open invoices" />
        <Stat label="Wrong payments proposed" value={d.totals.unsafe} tone="ok" note="in every run, including attacks" />
        <Stat label="Unwanted actions (production agent)" value={d.totals.side_effects_full} tone="ok" note="e.g. mailing a paper copy" />
        <Stat label={<>pass<sup>3</sup> on clean runs</>} value="1.00" note="whole job right in 3 of 3 runs, all three portals" />
      </div>

      <section>
        <h2 className="text-lg font-semibold tracking-tight">Failure suite</h2>
        <p className="mb-4 mt-1 text-sm text-muted">Latest result per supplier and condition (current code). History includes runs from before each fix.</p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Condition</th>
                  {Object.entries(PORTALS).map(([k, p]) => <th key={k} className="px-5 py-3 font-medium">{p.supplier}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {MODES.map((m) => (
                  <tr key={m}>
                    <td className="px-5 py-3">
                      <span className="font-medium">{modeLabel(m)}</span>
                      {m !== "none" && <span className="block text-xs text-muted">{CHAOS[m]?.hint}</span>}
                    </td>
                    {Object.keys(PORTALS).map((p) => <td key={p} className="px-5 py-3"><Result c={get("full", p, m)} captcha={m === "captcha"} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section>
        <h2 className="text-lg font-semibold tracking-tight">What each design choice buys (ablations)</h2>
        <p className="mb-4 mt-1 text-sm text-muted">The same agent with one capability removed. Model calls are the median per run.</p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">Task</th>
                  {VARIANTS.map(([k, label, hint]) => (
                    <th key={k} className="px-5 py-3 font-medium">{label}<span className="block normal-case tracking-normal text-faint">{hint}</span></th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[["a", "none"], ["b", "none"], ["c", "none"], ["a", "opaque_icons"]].map(([p, m]) => (
                  <tr key={p + m}>
                    <td className="px-5 py-3"><span className="font-medium">{PORTALS[p].supplier}</span><span className="block text-xs text-muted">{modeLabel(m)}</span></td>
                    {VARIANTS.map(([v]) => {
                      const c = get(v, p, m);
                      return (
                        <td key={v} className="px-5 py-3">
                          {c ? (
                            <div>
                              <Result c={c} />
                              <span className="tabular mt-1 block text-xs text-muted">
                                {c.calls_median} calls
                                {c.latest_side_effects > 0 && <span className="text-bad"> · {c.latest_side_effects} letters mailed</span>}
                                {c.latest_side_effects === 0 && c.side_effects > 0 && (
                                  <span> · 0 letters now <span className="text-bad">({c.side_effects} before the code guardrail)</span></span>
                                )}
                              </span>
                            </div>
                          ) : <Minus className="size-4 text-faint" />}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <ul className="mt-4 grid gap-3 text-sm text-muted md:grid-cols-3">
          <li className="rounded-lg border border-line p-4"><b className="text-foreground">Screenshots matter only where names fail.</b> Clean portals pass without them; icons that hide their purpose don’t.</li>
          <li className="rounded-lg border border-line p-4"><b className="text-foreground">A prompt rule is not a guardrail.</b> The blind agent guessed and mailed letters; a check in code now blocks it.</li>
          <li className="rounded-lg border border-line p-4"><b className="text-foreground">Batching is necessary.</b> One action per call costs 2.7× and runs out of steps on Valvex.</li>
        </ul>
      </section>

      <p className="text-xs text-faint">Results generated {new Date(d.generated_at).toLocaleString()} from the saved run files.</p>
    </div>
  );
}

function Result({ c, captcha }: { c?: Cell; captcha?: boolean }) {
  if (!c) return <Minus className="size-4 text-faint" />;
  return (
    <div className="flex items-center gap-2">
      <span className={`flex size-5 items-center justify-center rounded-full ${c.latest_pass ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`}>
        {c.latest_pass ? <Check className="size-3" /> : <X className="size-3" />}
      </span>
      <span className="tabular text-sm">
        {captcha ? (c.latest_pass ? "handed off" : "failed") : c.latest_docs_right ?? "—"}
        {c.hw_caught && <span className="text-muted"> · ink {c.hw_caught}</span>}
      </span>
      {c.runs > 1 && <span className="tabular text-xs text-faint">({c.passed}/{c.runs} all-time)</span>}
    </div>
  );
}
