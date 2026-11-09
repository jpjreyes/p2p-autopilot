"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, API_URL, CHAOS, PORTALS, VERDICT_LABEL, type ReviewItem, type Run, type Step } from "@/lib/api";

type RunDetail = { run: Run; steps: Step[]; review: ReviewItem[] };

function describe(a: Step["action"]): string {
  if (a.action === "look") return "look (screenshot with numbered marks)";
  const target = a.mark != null ? `mark ${a.mark}` : `${a.role ?? ""} "${a.name ?? ""}"${a.nth != null ? ` [${a.nth}]` : ""}`;
  return `${a.action} ${target}`.trim();
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<RunDetail | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    const load = () =>
      api<RunDetail>(`/api/runs/${id}`)
        .then((d) => {
          if (stop) return;
          setData(d);
          if (d.run.status !== "running" && d.review.length > 0) stop = true;
        })
        .catch((e) => setError(e.message));
    load();
    const t = setInterval(() => !stop && load(), 2000);
    return () => clearInterval(t);
  }, [id]);

  if (error) return <p className="text-bad">{error}</p>;
  if (!data) return <p className="text-muted">Loading…</p>;
  const { run, steps, review } = data;
  const shownIdx = selected ?? [...steps].reverse().find((s) => s.has_shot)?.idx ?? null;

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <h1 className="font-mono text-lg">{run.run_id}</h1>
        <span>{PORTALS[run.portal] ?? run.portal}</span>
        <span className="text-muted">{CHAOS[run.chaos] ?? run.chaos}</span>
        <span className="font-medium">{run.status === "running" ? "Running…" : run.status}</span>
        <span className="text-muted">{run.downloads} PDFs · {run.calls} model calls · {run.seconds ?? "…"} s</span>
      </section>
      {run.reason && <p className="rounded border border-line bg-card p-3 text-sm"><b>Agent:</b> {run.reason}</p>}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <ol className="max-h-[560px] space-y-1 overflow-y-auto rounded-lg border border-line p-2 text-sm">
          {steps.map((s) => (
            <li key={s.idx}>
              <button onClick={() => setSelected(s.idx)}
                className={`w-full rounded px-2 py-1 text-left ${shownIdx === s.idx ? "bg-card" : ""}`}>
                <span className={s.ok ? "text-ok" : "text-bad"}>{s.ok ? "✓" : "✗"}</span>{" "}
                <span className="font-mono text-xs text-muted">{s.n}.</span> {describe(s.action)}
                <span className="block truncate pl-5 text-xs text-muted">{s.result}</span>
              </button>
            </li>
          ))}
          {steps.length === 0 && <li className="p-2 text-muted">Waiting for the first step…</li>}
        </ol>
        <div className="rounded-lg border border-line p-2">
          {shownIdx != null ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`${API_URL}/api/runs/${id}/steps/${shownIdx}.png`} alt={`Screenshot of step ${shownIdx}`}
              className="w-full rounded" />
          ) : <p className="p-4 text-muted">Screenshots appear here as the agent works.</p>}
        </div>
      </section>

      {review.length > 0 && (
        <section>
          <h2 className="mb-2 font-medium">What the agent proposes ({review.length} documents)</h2>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-sm">
              <thead className="bg-card text-left text-muted">
                <tr><th className="p-2">Document</th><th className="p-2">Verdict</th><th className="p-2 text-right">Pay</th>
                  <th className="p-2">Status</th><th className="p-2">Evidence</th></tr>
              </thead>
              <tbody>
                {review.map((i) => (
                  <tr key={i.item_id} className="border-t border-line align-top">
                    <td className="p-2 font-mono">{i.number}</td>
                    <td className="p-2">{VERDICT_LABEL[i.verdict] ?? i.verdict}</td>
                    <td className="p-2 text-right font-mono">{i.payable ?? "—"}</td>
                    <td className={`p-2 ${i.status === "needs_human" ? "text-warn" : "text-ok"}`}>{i.status.replaceAll("_", " ")}</td>
                    <td className="p-2 text-xs text-muted">{i.evidence.join(" ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
