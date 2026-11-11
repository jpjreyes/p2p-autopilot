"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight, Ban, Calculator, Download, FileSearch, Globe, KeyRound, LogIn, PenLine, PlayCircle, ShieldCheck,
  UserCheck,
} from "lucide-react";
import { api, type Run } from "@/lib/api";
import { Badge, Card } from "@/components/ui";

type Evals = { totals: { runs: number; unsafe: number } };

const STEPS = [
  { icon: LogIn, title: "Logs in like a clerk", body: "Cookie walls, frames, pop-ups, two-step logins. Passwords are filled in by code; the model never sees them." },
  { icon: Download, title: "Collects every open invoice", body: "Pages, collapsed months, search-first portals. Skips what is already paid." },
  { icon: FileSearch, title: "Reads and double-checks", body: "Text PDFs, scans and handwritten corrections. Every number must add up and agree with the portal’s own listing." },
  { icon: Calculator, title: "Matches in code", body: "Invoice vs purchase order vs goods receipt, in plain Python with exact decimals. Never the model." },
  { icon: UserCheck, title: "A person approves", body: "The agent proposes. Anything off goes to the review queue with the evidence. Nothing pays itself." },
];

const GUARDRAILS = [
  { icon: Ban, title: "No pay tool", body: "The agent has no approve or pay action at all. An invoice saying “pre-approved, pay now” is a test case." },
  { icon: Calculator, title: "Money math in code", body: "Payable = min(billed, received) × min(billed, PO price), per line, in Decimal." },
  { icon: ShieldCheck, title: "Checked twice", body: "Lines must sum to the total, and total, PO and date must match the portal row." },
  { icon: PenLine, title: "Ink means a person", body: "A handwritten change to an amount always goes to review, whatever the match says." },
  { icon: Globe, title: "Stays on the portal", body: "Navigation outside the supplier’s site is blocked; nameless icons can’t be clicked blind." },
  { icon: KeyRound, title: "Secrets stay out", body: "Credentials are placeholders to the model; login attempts are capped to protect the account." },
];

export default function Overview() {
  const [evals, setEvals] = useState<Evals | null>(null);
  const [featured, setFeatured] = useState<string | null>(null);

  useEffect(() => {
    fetch("/evals.json").then((r) => r.json()).then(setEvals).catch(() => {});
    api<Run[]>("/api/runs").then((runs) => setFeatured(runs.find((r) => r.status === "done")?.run_id ?? null)).catch(() => {});
  }, []);

  return (
    <div className="space-y-20">
      <section className="grid items-center gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <Badge tone="brand">Accounts payable · see, predict, act</Badge>
          <h1 className="mt-4 text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
            Purchase-to-pay that sees the risk, predicts it, and does the&nbsp;work.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
            Process mining on the real SAP log shows where money leaks, a model flags the invoices that will be blocked,
            a weekly brief says what to do, and an agent works supplier portals with no API the way your AP clerk does.
            It proposes; people approve.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href={featured ? `/runs/${featured}` : "/runs"}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-brand-ink shadow-card hover:opacity-90">
              <PlayCircle className="size-4" /> Watch a run
            </Link>
            <Link href="/review"
              className="inline-flex items-center gap-2 rounded-lg border border-line-strong bg-surface px-4 py-2.5 text-sm font-medium hover:bg-surface-2">
              Open the review queue <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
        <ExampleQueue />
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        {[
          { href: "/process", tag: "See", title: "EUR 1.75M paid before any goods receipt",
            body: "Found by SQL on 251,734 real SAP purchase-order lines, with the match type that should have stopped it." },
          { href: "/risk", tag: "Predict", title: "Payment blocks, flagged when the invoice arrives",
            body: "With 6 of 10 flags right, a model trained on the log catches half of the blocks, vs 31% for the best rule, and says why." },
          { href: "/brief", tag: "Brief", title: "A weekly page nobody had to ask for",
            body: "Code computes every number, the model writes the words, and a check rejects numbers no query produced." },
        ].map((c) => (
          <Link key={c.href} href={c.href} className="group rounded-xl border border-line bg-surface p-5 shadow-card hover:bg-surface-2">
            <Badge tone="brand">{c.tag}</Badge>
            <p className="mt-3 font-semibold tracking-tight">{c.title}</p>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">{c.body}</p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm text-brand">Open <ArrowRight className="size-3.5 transition group-hover:translate-x-0.5" /></span>
          </Link>
        ))}
      </section>

      <section className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {[
          { value: evals ? String(evals.totals.unsafe) : "0", label: "wrong payments proposed", note: `across ${evals?.totals.runs ?? "60"} eval runs, incl. attacks and redesigns` },
          { value: "1.00", label: <>pass<sup>3</sup> reliability</>, note: "whole job right in 3 of 3 runs, every portal" },
          { value: "16/16", label: "handwritten corrections caught", note: "0 false alarms on approvals and notes" },
          { value: "$0.0015", label: "per invoice", note: "navigation + reading, list price" },
        ].map((k) => (
          <div key={k.note} className="bg-surface p-6">
            <p className="tabular text-3xl font-semibold tracking-tight">{k.value}</p>
            <p className="mt-1 text-sm font-medium">{k.label}</p>
            <p className="mt-1 text-xs text-faint">{k.note}</p>
          </div>
        ))}
      </section>

      <section>
        <SectionTitle eyebrow="How it works" title="From portal to approved payment, with the risky parts in code" />
        <ol className="grid gap-4 md:grid-cols-5">
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative">
              <Card className="h-full p-5">
                <div className="flex items-center justify-between">
                  <span className="flex size-9 items-center justify-center rounded-lg bg-brand-soft text-brand"><s.icon className="size-4.5" /></span>
                  <span className="tabular text-xs text-faint">0{i + 1}</span>
                </div>
                <h3 className="mt-4 font-medium">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.body}</p>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <SectionTitle eyebrow="Guardrails" title="Designed for the day the model is wrong" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {GUARDRAILS.map((g) => (
            <div key={g.title} className="flex gap-4 rounded-xl border border-line p-5">
              <g.icon className="mt-0.5 size-5 shrink-0 text-brand" />
              <div>
                <h3 className="font-medium">{g.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{g.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl bg-brand px-8 py-10 text-brand-ink sm:px-12">
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="max-w-xl">
            <h2 className="text-2xl font-semibold tracking-tight">Tested like production, not like a demo</h2>
            <p className="mt-2 opacity-85">
              Portal redesigns, expired sessions, CAPTCHAs, prompt injection, scans, handwriting and a portal the agent
              had never seen. Every result, including the failures that led to fixes.
            </p>
          </div>
          <Link href="/evals" className="inline-flex items-center gap-2 rounded-lg bg-brand-ink px-4 py-2.5 text-sm font-medium text-brand hover:opacity-90">
            See the evals <ArrowRight className="size-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-8">
      <p className="text-sm font-medium text-brand">{eyebrow}</p>
      <h2 className="mt-1 text-2xl font-semibold tracking-tight">{title}</h2>
    </div>
  );
}

function ExampleQueue() {
  const rows = [
    { no: "INV-1059", issue: "Price above PO", tone: "bad" as const, billed: "€2,014.75", pay: "€1,904.00", why: "Item 00010 billed €59.83, PO says €55.40" },
    { no: "INV-1076", issue: "Billed more than received", tone: "bad" as const, billed: "€1,514.00", pay: "€0.00", why: "Invoiced before the goods arrived (real SAP sequence)" },
    { no: "INV-1085", issue: "Duplicate invoice", tone: "bad" as const, billed: "€3,246.00", pay: "€0.00", why: "Same PO, lines and total as INV-1075" },
    { no: "INV-1043", issue: "Matches", tone: "ok" as const, billed: "€3,402.00", pay: "€3,402.00", why: "Real SAP PO and goods receipt tie out" },
  ];
  return (
    <Card className="overflow-hidden shadow-pop">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <div>
          <p className="text-sm font-medium">Acme Fasteners · this morning’s run</p>
          <p className="text-xs text-faint">20 invoices collected · 7 need a person</p>
        </div>
        <Badge tone="ok" dot>Completed</Badge>
      </div>
      <ul className="divide-y divide-line">
        {rows.map((r) => (
          <li key={r.no} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="whitespace-nowrap font-mono text-sm">{r.no}</span>
              <Badge tone={r.tone}>{r.issue}</Badge>
            </div>
            <div className="tabular text-right text-sm">
              {r.billed !== r.pay && <span className="mr-2 text-faint line-through">{r.billed}</span>}
              <span className="font-medium">{r.pay}</span>
            </div>
            <p className="col-span-2 text-xs text-muted">{r.why}</p>
          </li>
        ))}
      </ul>
      <div className="border-t border-line bg-surface-2 px-5 py-3 text-xs text-muted">
        Real SAP purchase orders and goods receipts (BPI 2019); invoice numbers and planted problems are generated.
      </div>
    </Card>
  );
}
