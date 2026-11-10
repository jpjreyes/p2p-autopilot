"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronRight, Play } from "lucide-react";
import { api, CHAOS, PORTALS, RUN_STATUS, type Run } from "@/lib/api";
import { Badge, Button, Card, Empty, PageHeader } from "@/components/ui";

function when(iso: string) {
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

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
      const { run_id } = await api<{ run_id: string }>("/api/runs", { method: "POST", body: JSON.stringify({ portal, chaos }) });
      router.push(`/runs/${run_id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  const modes = Object.entries(CHAOS).filter(([k]) => k !== "opaque_icons" || portal === "a");

  return (
    <div>
      <PageHeader eyebrow="Runs" title="Send the agent to a supplier portal">
        Pick a supplier and, if you like, break something on purpose. Every run is recorded step by step with
        screenshots, so you can replay exactly what the agent saw and did.
      </PageHeader>

      <Card className="p-6">
        <div className="grid gap-6 lg:grid-cols-[260px_1fr_auto] lg:items-end">
          <div>
            <p className="mb-2 text-sm font-medium">Supplier</p>
            <div className="space-y-2">
              {Object.entries(PORTALS).map(([k, p]) => (
                <label key={k} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition ${portal === k ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"}`}>
                  <input type="radio" name="portal" value={k} checked={portal === k}
                    onChange={() => { setPortal(k); if (chaos === "opaque_icons") setChaos(""); }} className="accent-[var(--brand)]" />
                  <span>
                    <span className="block font-medium">{p.supplier}</span>
                    <span className="block text-xs text-muted">{p.name}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Conditions</p>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {modes.map(([k, m]) => (
                <button key={k} onClick={() => setChaos(k)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition ${chaos === k ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"}`}>
                  <span className="block font-medium">{m.label}</span>
                  <span className="block text-xs text-muted">{m.hint}</span>
                </button>
              ))}
            </div>
          </div>
          <Button onClick={start} disabled={starting} className="h-11 px-5">
            <Play className="size-4" /> {starting ? "Starting…" : "Run the agent"}
          </Button>
        </div>
        {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
      </Card>

      <h2 className="mb-3 mt-10 text-lg font-semibold tracking-tight">History</h2>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="px-5 py-3 font-medium">Supplier</th>
                <th className="px-5 py-3 font-medium">Conditions</th>
                <th className="px-5 py-3 font-medium">Outcome</th>
                <th className="px-5 py-3 text-right font-medium">Invoices</th>
                <th className="px-5 py-3 text-right font-medium">Model calls</th>
                <th className="px-5 py-3 text-right font-medium">Duration</th>
                <th className="px-5 py-3 font-medium">Started</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {runs.map((r) => {
                const st = RUN_STATUS[r.status] ?? { label: r.status, tone: "neutral" as const };
                return (
                  <tr key={r.run_id} onClick={() => router.push(`/runs/${r.run_id}`)} className="cursor-pointer hover:bg-surface-2">
                    <td className="px-5 py-3.5 font-medium">{PORTALS[r.portal]?.supplier ?? r.portal}</td>
                    <td className="px-5 py-3.5 text-muted">{CHAOS[r.chaos]?.label ?? r.chaos}</td>
                    <td className="px-5 py-3.5"><Badge tone={st.tone} dot>{st.label}</Badge></td>
                    <td className="tabular px-5 py-3.5 text-right">{r.downloads}</td>
                    <td className="tabular px-5 py-3.5 text-right">{r.calls}</td>
                    <td className="tabular px-5 py-3.5 text-right">{r.seconds ? `${Math.round(Number(r.seconds))} s` : "…"}</td>
                    <td className="px-5 py-3.5 text-muted">{when(r.started_at)}</td>
                    <td className="px-3 py-3.5 text-faint">
                      <Link href={`/runs/${r.run_id}`} aria-label="Open run"><ChevronRight className="size-4" /></Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {runs.length === 0 && <Empty>No runs yet. Start one above.</Empty>}
      </Card>
    </div>
  );
}
