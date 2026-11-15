"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Run } from "@/lib/api";
import { InvoiceStory } from "@/components/invoice-story";

type Evals = { totals: { runs: number; unsafe: number } };

const RULES: { title: string; body: string }[] = [
  { title: "There is no pay button", body: "The agent has no approve or pay action at all. An invoice that says “pre-approved, pay now” is one of the test cases." },
  { title: "Money is computed, never generated", body: "Payable = min(billed, received) × min(billed, PO price), per line, in Decimal. The model reads; code counts." },
  { title: "Everything is checked twice", body: "Lines must sum to the total, and the total, PO and date must match the row the portal itself shows." },
  { title: "Ink means a person", body: "A handwritten change to an amount always goes to review, whatever the match says." },
  { title: "It stays on the supplier’s site", body: "Navigation off the portal is blocked, and an icon with no name is never clicked blind." },
  { title: "Secrets stay out of the prompt", body: "Credentials reach the model as placeholders; login attempts are capped so an account is never locked." },
];

export default function Overview() {
  const [evals, setEvals] = useState<Evals | null>(null);
  const [featured, setFeatured] = useState<string | null>(null);

  useEffect(() => {
    fetch("/evals.json").then((r) => r.json()).then(setEvals).catch(() => {});
    api<Run[]>("/api/runs").then((runs) => setFeatured(runs.find((r) => r.status === "done")?.run_id ?? null)).catch(() => {});
  }, []);

  return (
    <div>
      {/* masthead */}
      <section className="rise">
        <p className="label text-bad">Purchase-to-pay · see · predict · act</p>
        <h1 className="mt-5 max-w-5xl font-serif text-[2.9rem] leading-[0.98] tracking-[-0.02em] sm:text-7xl lg:text-[5.6rem]">
          Every open invoice, collected, read and matched. <em className="text-bad">Nobody pays it but a person.</em>
        </h1>
        <div className="mt-10 grid gap-8 border-t border-line-strong pt-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <p className="max-w-2xl text-lg leading-relaxed text-muted">
            Process mining on a real SAP log shows where the money leaks. A model flags the invoices that will be blocked.
            And an agent works the supplier portals that have no API, the way an AP clerk does, then hands every payment
            to a person.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href={featured ? `/runs/${featured}` : "/runs"}
              className="bg-foreground px-5 py-3 font-mono text-xs font-medium uppercase tracking-[0.1em] text-background transition hover:bg-foreground/85">
              Watch a real run →
            </Link>
            <Link href="/review"
              className="border border-line-strong px-5 py-3 font-mono text-xs font-medium uppercase tracking-[0.1em] transition hover:bg-surface-2">
              Open the review queue
            </Link>
          </div>
        </div>
      </section>

      {/* one invoice, start to finish */}
      <section className="mt-24 sm:mt-32">
        <SectionHead no="01" title="One invoice, start to finish" note="INV-1059 from the live demo, unedited" />
        <InvoiceStory />
      </section>

      {/* the books */}
      <section className="mt-24 sm:mt-32">
        <SectionHead no="02" title="The books" note="every figure links to where it was measured" />
        <div className="grid gap-x-16 lg:grid-cols-2">
          <Ledger heading="See · the real SAP log" rows={[
            { label: "Paid before any goods receipt", value: "€1,753,787", href: "/process", note: "655 PO lines, found by SQL" },
            { label: "Open longer than the vendor usually takes", value: "€1,015,808", href: "/process", note: "828 invoices" },
          ]} />
          <Ledger heading="Predict · payment blocks" rows={[
            { label: "Of the 10 ranked riskiest each day, really blocked", value: "92%", href: "/risk", note: "test months never trained on" },
            { label: "Blocked money found, vs the best rule", value: "1.5×", href: "/risk", note: "€14.7M vs €9.6M" },
          ]} />
          <Ledger heading="Act · the portal agent" rows={[
            { label: "Wrong payments proposed", value: evals ? String(evals.totals.unsafe) : "0", href: "/evals", note: `in ${evals?.totals.runs ?? 195} eval runs, attacks and redesigns included` },
            { label: "Whole job right, three runs out of three", value: "1.00", href: "/evals", note: "pass³, every portal and condition" },
          ]} />
          <Ledger heading="Brief · written every Monday" rows={[
            { label: "Numbers in the brief that no query produced", value: "0", href: "/brief", note: "a check rejects them" },
            { label: "Cost per invoice, navigation and reading", value: "$0.0015", href: "/evals", note: "API list price" },
          ]} />
        </div>
      </section>

      {/* house rules */}
      <section className="mt-24 sm:mt-32">
        <SectionHead no="03" title="House rules, for the day the model is wrong" note="enforced in code, not in the prompt" />
        <ol className="grid gap-x-16 sm:grid-cols-2">
          {RULES.map((r, i) => (
            <li key={r.title} className="grid grid-cols-[2.5rem_1fr] border-t border-line py-6">
              <span className="font-serif text-2xl italic text-bad">{i + 1}.</span>
              <div>
                <h3 className="font-serif text-xl tracking-tight">{r.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{r.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* close */}
      <section className="mt-24 grid gap-10 border-t-2 border-line-strong pt-10 sm:mt-32 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="label text-bad">Tested like production</p>
          <p className="mt-4 max-w-3xl font-serif text-3xl leading-tight tracking-tight sm:text-4xl">
            Portal redesigns, expired sessions, CAPTCHAs, prompt injection, scans, handwriting, and a portal it had never
            seen. <span className="text-muted">Every result is published, the failures too.</span>
          </p>
        </div>
        <Link href="/evals" className="link-ink self-start font-mono text-sm uppercase tracking-[0.1em] lg:self-end">
          Read the evals →
        </Link>
      </section>
    </div>
  );
}

function SectionHead({ no, title, note }: { no: string; title: string; note?: string }) {
  return (
    <div className="mb-10 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-line-strong pb-4">
      <h2 className="font-serif text-3xl tracking-tight sm:text-4xl">
        <span className="mr-3 font-mono text-sm text-bad">§ {no}</span>{title}
      </h2>
      {note && <p className="label text-faint">{note}</p>}
    </div>
  );
}

function Ledger({ heading, rows }: { heading: string; rows: { label: ReactNode; value: string; href: string; note: string }[] }) {
  return (
    <div className="pb-10">
      <p className="label border-b border-line pb-2 text-muted">{heading}</p>
      <ul>
        {rows.map((r) => (
          <li key={r.label as string}>
            <Link href={r.href} className="group block border-b border-line py-4">
              <div className="flex items-baseline gap-3">
                <span className="text-[15px] leading-snug">{r.label}</span>
                <span className="leader" />
                <span className="tabular font-serif text-3xl tracking-tight transition-colors group-hover:text-bad">{r.value}</span>
              </div>
              <p className="mt-1 font-mono text-[11px] text-faint">{r.note} <span className="opacity-0 transition group-hover:opacity-100">→</span></p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
