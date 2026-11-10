"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Pause, PenLine, Play, Quote, X } from "lucide-react";
import {
  api, API_URL, CHAOS, describeStep, hasHandwritingChange, money, moneySummary, PORTALS, RUN_STATUS, STATUS,
  VERDICT, type ReviewItem, type Run, type Step,
} from "@/lib/api";
import { Badge, Card, Stat } from "@/components/ui";
import { InvoiceDrawer } from "@/components/invoice-drawer";

type RunDetail = { run: Run; steps: Step[]; review: ReviewItem[] };

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<RunDetail | null>(null);
  const [cur, setCur] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    let stop = false;
    const load = () =>
      api<RunDetail>(`/api/runs/${id}`)
        .then((d) => {
          if (stop) return;
          setData(d);
          if (d.run.status !== "running" && (d.review.length > 0 || d.run.downloads === 0)) stop = true;
        })
        .catch((e) => setError(e.message));
    load();
    const t = setInterval(() => !stop && load(), 2000);
    return () => clearInterval(t);
  }, [id]);

  const steps = useMemo(() => data?.steps ?? [], [data]);
  const live = data?.run.status === "running";
  const pos = cur ?? (live ? steps.length - 1 : 0);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      setCur((c) => {
        const next = (c ?? 0) + 1;
        if (next >= steps.length) { setPlaying(false); return steps.length - 1; }
        return next;
      });
    }, 1100);
    return () => clearInterval(t);
  }, [playing, steps.length]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-pos="${pos}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [pos]);

  if (error) return <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>;
  if (!data) return <p className="text-muted">Loading run…</p>;

  const { run, review } = data;
  const portal = PORTALS[run.portal];
  const st = RUN_STATUS[run.status] ?? { label: run.status, tone: "neutral" as const };
  const frame = [...steps.slice(0, pos + 1)].reverse().find((s) => s.has_shot) ?? steps.find((s) => s.has_shot);
  const step = steps[pos];
  const money_ = moneySummary(review);

  const groups: { n: number; reason?: string; items: { s: Step; i: number }[] }[] = [];
  steps.forEach((s, i) => {
    const last = groups[groups.length - 1];
    if (last && last.n === s.n) last.items.push({ s, i });
    else groups.push({ n: s.n, reason: s.action.reason, items: [{ s, i }] });
  });

  return (
    <div className="space-y-8">
      <div>
        <Link href="/runs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
          <ChevronLeft className="size-4" /> Runs
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{portal?.supplier ?? run.portal}</h1>
          <Badge tone={st.tone} dot>{live ? "Running live" : st.label}</Badge>
          <Badge>{CHAOS[run.chaos]?.label ?? run.chaos}</Badge>
        </div>
        <p className="mt-1 text-sm text-muted">{portal?.name} · run {run.run_id}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <Stat label="Invoices collected" value={run.downloads} />
        <Stat label="Model calls" value={run.calls || "…"} note="several clicks per call when targets are visible" />
        <Stat label="Duration" value={run.seconds ? `${Math.round(Number(run.seconds))} s` : "…"} note="unattended" />
        <Stat label="Need a person" value={review.length ? money_.review.length : "…"} note={review.length ? `of ${review.length} documents` : undefined} tone="warn" />
      </div>

      {run.reason && (
        <div className="flex gap-3 rounded-xl border border-line bg-surface p-4 text-sm">
          <Quote className="mt-0.5 size-4 shrink-0 text-faint" />
          <p><span className="font-medium">Agent’s closing note: </span><span className="text-muted">{run.reason}</span></p>
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="grid lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="border-b border-line lg:border-b-0 lg:border-r">
            <div className="flex items-center gap-3 border-b border-line bg-surface-2 px-4 py-2.5">
              <span className="flex gap-1.5"><i className="size-2.5 rounded-full bg-line-strong" /><i className="size-2.5 rounded-full bg-line-strong" /><i className="size-2.5 rounded-full bg-line-strong" /></span>
              <span className="flex-1 truncate rounded-md bg-surface px-3 py-1 text-xs text-muted">{portal?.name ?? "supplier portal"}</span>
            </div>
            <div className="flex aspect-[3/2] items-start justify-center overflow-hidden bg-white">
              {frame ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`${API_URL}/api/runs/${id}/steps/${frame.idx}.png`} alt="What the agent saw" className="w-full" />
              ) : <p className="p-10 text-sm text-muted">Screenshots appear here as the agent works.</p>}
            </div>
            <div className="flex items-center gap-3 border-t border-line px-4 py-3">
              <button onClick={() => { setPlaying(false); setCur(Math.max(0, pos - 1)); }} className="rounded-md p-1.5 text-muted hover:bg-surface-2" aria-label="Previous step"><ChevronLeft className="size-4" /></button>
              <button onClick={() => { if (pos >= steps.length - 1) setCur(0); setPlaying((p) => !p); }} disabled={!steps.length}
                className="flex size-9 items-center justify-center rounded-full bg-brand text-brand-ink hover:opacity-90" aria-label={playing ? "Pause" : "Play"}>
                {playing ? <Pause className="size-4" /> : <Play className="ml-0.5 size-4" />}
              </button>
              <button onClick={() => { setPlaying(false); setCur(Math.min(steps.length - 1, pos + 1)); }} className="rounded-md p-1.5 text-muted hover:bg-surface-2" aria-label="Next step"><ChevronRight className="size-4" /></button>
              <input type="range" min={0} max={Math.max(0, steps.length - 1)} value={pos}
                onChange={(e) => { setPlaying(false); setCur(Number(e.target.value)); }} className="flex-1 accent-[var(--brand)]" />
              <span className="tabular w-24 text-right text-xs text-muted">Step {steps.length ? pos + 1 : 0} of {steps.length}</span>
            </div>
            {step && (
              <div className="border-t border-line bg-surface-2 px-4 py-3 text-sm">
                <span className="font-medium">{describeStep(step).title}</span>
                {step.action.reason && <span className="text-muted"> · {step.action.reason}</span>}
              </div>
            )}
          </div>

          <ol ref={listRef} className="max-h-[640px] overflow-y-auto p-3">
            {groups.map((g, gi) => (
              <li key={gi} className="mb-3">
                <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-faint">Decision {g.n}</p>
                {g.reason && <p className="px-2 pb-2 text-xs italic leading-relaxed text-muted">{g.reason}</p>}
                <ul className="space-y-0.5">
                  {g.items.map(({ s, i }) => {
                    const d = describeStep(s);
                    return (
                      <li key={s.idx}>
                        <button data-pos={i} onClick={() => { setPlaying(false); setCur(i); }}
                          className={`flex w-full gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition ${i === pos ? "bg-brand-soft" : "hover:bg-surface-2"}`}>
                          <span className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full ${s.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`}>
                            {s.ok ? <Check className="size-2.5" /> : <X className="size-2.5" />}
                          </span>
                          <span className="min-w-0">
                            <span className="block">{d.title}</span>
                            {d.detail && <span className="block truncate text-xs text-muted">{d.detail}</span>}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
            {steps.length === 0 && <li className="p-4 text-sm text-muted">Waiting for the first step…</li>}
          </ol>
        </div>
      </Card>

      {review.length > 0 && (
        <section>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">What the agent proposes</h2>
              <p className="text-sm text-muted">Read, checked and matched in code. Click a row to see the invoice next to the PO.</p>
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge tone="ok">{money(money_.proposed)} proposed</Badge>
              <Badge tone="warn">{money_.review.length} for review</Badge>
              <Badge tone="brand">{money(money_.caught)} overbilling caught</Badge>
            </div>
          </div>
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-line bg-surface-2 text-left text-xs uppercase tracking-wide text-faint">
                  <tr>
                    <th className="px-5 py-3 font-medium">Invoice</th>
                    <th className="px-5 py-3 font-medium">Finding</th>
                    <th className="px-5 py-3 text-right font-medium">Billed</th>
                    <th className="px-5 py-3 text-right font-medium">Proposed</th>
                    <th className="px-5 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {review.map((i) => {
                    const v = VERDICT[i.verdict] ?? { label: i.verdict, tone: "neutral" as const };
                    const s = STATUS[i.status] ?? { label: i.status, tone: "neutral" as const };
                    return (
                      <tr key={i.item_id} onClick={() => setOpen(i.item_id)} className="cursor-pointer hover:bg-surface-2">
                        <td className="px-5 py-3 font-mono font-medium">{i.number}</td>
                        <td className="px-5 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            <Badge tone={v.tone}>{v.label}</Badge>
                            {hasHandwritingChange(i) && <Badge tone="warn"><PenLine className="size-3" /> Ink</Badge>}
                          </div>
                        </td>
                        <td className="tabular px-5 py-3 text-right text-muted">{money(i.extracted?.total)}</td>
                        <td className="tabular px-5 py-3 text-right font-medium">{money(i.payable)}</td>
                        <td className="px-5 py-3"><Badge tone={s.tone} dot>{s.label}</Badge></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </section>
      )}

      {open != null && <InvoiceDrawer key={open} itemId={open} onClose={() => setOpen(null)}
        onDecided={() => api<RunDetail>(`/api/runs/${id}`).then(setData)} />}
    </div>
  );
}
