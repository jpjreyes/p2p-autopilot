"use client";

import { useEffect, useState } from "react";
import { api, type Brief } from "@/lib/api";
import { Badge, Card, PageHeader } from "@/components/ui";

function Section({ id, s }: { id: string; s: Brief["sections"][string] }) {
  return (
    <details id={id} className="group rounded-lg border border-line bg-surface p-4">
      <summary className="cursor-pointer text-sm font-medium">{s.title} <span className="text-faint">[{id}]</span></summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="text-left text-xs uppercase tracking-wide text-faint">
            <tr>{s.columns.map((c) => <th key={c} className="py-1 pr-4 font-medium">{c.replaceAll("_", " ")}</th>)}</tr>
          </thead>
          <tbody>
            {s.rows.map((r, i) => (
              <tr key={i}>{r.map((v, j) => <td key={j} className="tabular py-1 pr-4">{Array.isArray(v) ? v.join("; ") : String(v ?? "—")}</td>)}</tr>
            ))}
          </tbody>
        </table>
        <pre className="mt-3 whitespace-pre-wrap rounded-md bg-surface-2 p-3 text-[12px] text-muted">{s.sql}</pre>
      </div>
    </details>
  );
}

export default function BriefPage() {
  const [d, setD] = useState<Brief | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Brief>("/api/process/brief").then(setD).catch((e) => setErr(String(e))); }, []);
  if (err) return <p className="text-bad">{err}</p>;
  if (!d) return <p className="text-muted">Loading the brief…</p>;

  const link = (text: string) => {
    const m = text.match(/\[(\w+)\]\s*$/);
    return m ? <>{text.slice(0, m.index)}<a href={`#${m[1]}`} className="text-brand underline underline-offset-2">[{m[1]}]</a></> : text;
  };

  return (
    <div className="space-y-10">
      <PageHeader eyebrow={`Weekly brief · ${d.week[0]} to ${d.week[1]}`} title={d.summary?.headline ?? "This week in purchase-to-pay"}>
        Written every Monday without anyone asking. Code computes every number; the model only writes the summary,
        and a check rejects any number that no query produced.{" "}
        {d.unverified_numbers?.length === 0 && <Badge tone="ok" dot>all numbers verified</Badge>}
      </PageHeader>

      {d.summary && (
        <Card className="p-6">
          <ul className="space-y-3 text-[15px] leading-relaxed">
            {d.summary.bullets.map((b) => <li key={b} className="border-l-2 border-brand pl-4">{link(b)}</li>)}
          </ul>
        </Card>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight">The queries behind it</h2>
        <div className="space-y-3">
          {Object.entries(d.sections).map(([id, s]) => <Section key={id} id={id} s={s} />)}
        </div>
      </section>
    </div>
  );
}
