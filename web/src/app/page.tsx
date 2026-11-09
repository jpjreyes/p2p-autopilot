"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, CHAOS, PORTALS, type Run } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  running: "text-accent",
  done: "text-ok",
  handoff: "text-warn",
  budget: "text-bad",
  error: "text-bad",
};

export default function RunsPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [portal, setPortal] = useState("a");
  const [chaos, setChaos] = useState("");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    const load = () => api<Run[]>("/api/runs").then(setRuns).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  async function start() {
    setStarting(true);
    setError("");
    try {
      const { run_id } = await api<{ run_id: string }>("/api/runs", {
        method: "POST",
        body: JSON.stringify({ portal, chaos }),
      });
      router.push(`/runs/${run_id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">An agent for supplier portals with no API</h1>
        <p className="max-w-3xl text-muted">
          It logs in like a clerk, finds every open invoice, reads each PDF, checks it against the portal and
          runs the 3-way match (PO, goods receipt, invoice) in code. Anything off goes to a human. There is no
          approve or pay action: people decide in the review queue.
        </p>
      </section>

      <section className="rounded-lg border border-line bg-card p-4">
        <h2 className="mb-3 font-medium">Start a run</h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-muted">Supplier portal</span>
            <select value={portal} onChange={(e) => setPortal(e.target.value)}
              className="rounded border border-line bg-background px-2 py-1.5">
              {Object.entries(PORTALS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-muted">Break something (failure injection)</span>
            <select value={chaos} onChange={(e) => setChaos(e.target.value)}
              className="rounded border border-line bg-background px-2 py-1.5">
              {Object.entries(CHAOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <button onClick={start} disabled={starting}
            className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-background disabled:opacity-50">
            {starting ? "Starting…" : "Run agent"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      </section>

      <section>
        <h2 className="mb-2 font-medium">Recent runs</h2>
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-muted">
              <tr><th className="p-2">Run</th><th className="p-2">Portal</th><th className="p-2">Failure</th>
                <th className="p-2">Outcome</th><th className="p-2 text-right">PDFs</th>
                <th className="p-2 text-right">Model calls</th><th className="p-2 text-right">Seconds</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-t border-line">
                  <td className="p-2 font-mono"><Link className="text-accent hover:underline" href={`/runs/${r.run_id}`}>{r.run_id}</Link></td>
                  <td className="p-2">{PORTALS[r.portal] ?? r.portal}</td>
                  <td className="p-2">{CHAOS[r.chaos] ?? r.chaos}</td>
                  <td className={`p-2 font-medium ${STATUS_STYLE[r.status] ?? ""}`}>{r.status}</td>
                  <td className="p-2 text-right">{r.downloads}</td>
                  <td className="p-2 text-right">{r.calls}</td>
                  <td className="p-2 text-right">{r.seconds ?? "…"}</td>
                </tr>
              ))}
              {runs.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-muted">No runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
