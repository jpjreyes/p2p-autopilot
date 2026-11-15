"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

// One real document from the live demo: Acme's INV-1059 bills SAP PO 4508070179 (BPI 2019). Line 00010 is billed
// above the PO price; the agent reads it, the code matches it, and it goes to a person. Numbers are the run's own.
const STEPS: { no: string; title: string; body: ReactNode }[] = [
  {
    no: "01", title: "Collected",
    body: <>Acme SupplierNet has no API. The agent signs in, pages through the open invoices and downloads each PDF,
      the way the clerk would. Passwords are filled in by code; the model only ever sees placeholders.</>,
  },
  {
    no: "02", title: "Read, then checked",
    body: <>Number, date, PO, every line and the total come off the PDF. Then two checks: the lines must add up to the
      total, and the number, total and date must agree with the portal’s own listing.</>,
  },
  {
    no: "03", title: "Matched in code",
    body: <>The invoice is held against the real SAP purchase order and goods receipt, in plain Python with exact
      decimals. 25 units ordered, 25 received. Line 00010 is billed at €59.83; the PO says €55.40.</>,
  },
  {
    no: "04", title: "Stamped",
    body: <>Payable is what was ordered, at the agreed price, for what arrived: <b>€1,904.00</b>, not €2,014.75. The
      €110.75 gap is the finding, written next to the line that caused it.</>,
  },
  {
    no: "05", title: "A person signs",
    body: <>It lands in the review queue with the evidence beside it. The agent has no approve or pay action anywhere;
      a person decides, and the decision is logged.</>,
  },
];

export function InvoiceStory() {
  const [step, setStep] = useState(0);
  const [desktop, setDesktop] = useState(false);
  const refs = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setDesktop(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setStep(Number((e.target as HTMLElement).dataset.step))),
      { rootMargin: "-48% 0px -48% 0px" },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => { io.disconnect(); mq.removeEventListener("change", sync); };
  }, []);

  // on phones the sheet sits above the text with every mark already on it
  const s = desktop ? step : STEPS.length - 1;

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:gap-16">
      <div className="lg:sticky lg:top-32 lg:h-fit">
        <Sheet s={s} />
        <ol className="mt-5 hidden gap-1 lg:flex" aria-hidden="true">
          {STEPS.map((x, i) => (
            <li key={x.no} className={`h-0.5 flex-1 transition-colors duration-300 ${i <= s ? "bg-bad" : "bg-line"}`} />
          ))}
        </ol>
      </div>
      <div>
        {STEPS.map((x, i) => (
          <article key={x.no} data-step={i} ref={(el) => { refs.current[i] = el; }}
            className={`border-t border-line-strong py-8 transition-opacity duration-300 lg:flex lg:min-h-[62vh] lg:flex-col lg:justify-center lg:border-0 lg:py-0 ${desktop && i !== step ? "lg:opacity-30" : ""}`}>
            <p className="label text-bad">{x.no} / 05</p>
            <h3 className="mt-2 font-serif text-3xl tracking-tight sm:text-4xl">{x.title}</h3>
            <p className="mt-3 max-w-md leading-relaxed text-muted [&_b]:font-semibold [&_b]:text-foreground">{x.body}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function Mark({ on, children, className = "" }: { on: boolean; children: ReactNode; className?: string }) {
  return (
    <span className={`relative transition-[outline-color] duration-300 ${on ? "outline outline-[1.5px] outline-offset-2 outline-accent" : "outline-transparent"} ${className}`}>
      {children}
    </span>
  );
}

function Sheet({ s }: { s: number }) {
  const read = s >= 1, matched = s >= 2, stamped = s >= 3, signed = s >= 4;
  return (
    <div className="relative pt-4">
      {/* the clip the agent attached when it downloaded the file */}
      <div className="absolute -top-0 right-6 z-10 rotate-2 border border-line-strong bg-background px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] sm:right-10">
        Fetched · Acme SupplierNet · p. 2 of 3
      </div>

      <div className="sheet relative overflow-hidden px-5 pb-7 pt-8 font-mono text-[11px] leading-relaxed sm:px-9 sm:text-[12.5px]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-serif text-xl font-semibold not-italic tracking-tight sm:text-2xl">ACME FASTENERS INC.</p>
            <p className="text-faint">Supplier SUP-ACME · mock portal A</p>
          </div>
          <p className="font-serif text-2xl tracking-[0.2em] sm:text-3xl">INVOICE</p>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-1 border-y border-line py-3">
          <p><span className="text-faint">Bill to </span>Northline Distribution</p>
          <p className="text-right"><span className="text-faint">No. </span><Mark on={read}>INV-1059</Mark></p>
          <p><span className="text-faint">Terms </span>Net 30</p>
          <p className="text-right"><span className="text-faint">Date </span><Mark on={read}>2018-11-30</Mark></p>
          <p />
          <p className="text-right"><span className="text-faint">PO </span><Mark on={read}>PO-4508070179</Mark></p>
        </div>

        <table className="mt-4 w-full">
          <thead>
            <tr className="text-left text-faint">
              <th className="pb-2 font-normal">Item</th>
              <th className="hidden pb-2 font-normal sm:table-cell">Description</th>
              <th className="pb-2 text-right font-normal">Qty</th>
              <th className="pb-2 text-right font-normal">Unit</th>
              <th className="pb-2 text-right font-normal">Amount</th>
            </tr>
          </thead>
          <tbody className="tabular">
            <tr className={`transition-colors duration-300 ${matched ? "bg-bad-soft/60" : ""}`}>
              <td className="py-1.5"><Mark on={read && !matched}>00010</Mark></td>
              <td className="hidden sm:table-cell">MRO components</td>
              <td className="text-right">25</td>
              <td className="text-right">
                <span className={`inline-block px-1 transition-all duration-300 ${matched ? "rounded-full outline outline-[1.5px] outline-bad" : ""}`}>59.83</span>
              </td>
              <td className="text-right">1,495.75</td>
            </tr>
            <tr aria-hidden={!matched}>
              <td colSpan={5} className={`pb-1 text-right font-serif text-[13px] italic leading-tight text-bad transition-opacity duration-300 sm:text-sm ${matched ? "opacity-100" : "opacity-0"}`}>
                ↑ PO says 55.40 · 25 × 4.43 = 110.75 over
              </td>
            </tr>
            <tr>
              <td className="py-1.5"><Mark on={read && !matched}>00020</Mark></td>
              <td className="hidden sm:table-cell">MRO components</td>
              <td className="text-right">1</td>
              <td className="text-right">519.00</td>
              <td className="text-right">
                <span className={`mr-1 font-sans text-accent transition-opacity duration-300 ${matched ? "opacity-100" : "opacity-0"}`}>✓</span>
                519.00
              </td>
            </tr>
          </tbody>
        </table>

        <div className="mt-5 flex items-end justify-between gap-4 border-t border-line pt-3">
          <div className={`text-faint transition-opacity duration-300 ${matched ? "opacity-100" : "opacity-0"}`}>
            <p>PO-4508070179 · 25 × 55.40 · 1 × 519.00</p>
            <p>GR-8070179 · 25 + 1 received</p>
          </div>
          <div className="tabular shrink-0 text-right">
            <p>
              <span className="text-faint">Total EUR </span>
              <Mark on={read && !stamped}>
                <span className={stamped ? "text-faint line-through decoration-bad decoration-2" : ""}>2,014.75</span>
              </Mark>
            </p>
            <p className={`font-serif text-lg italic text-accent transition-opacity duration-300 sm:text-xl ${stamped ? "opacity-100" : "opacity-0"}`}>
              payable 1,904.00
            </p>
          </div>
        </div>

        <div className="flex h-20 items-center pl-1 sm:h-24 sm:pl-4">
          {stamped && <span key="stamp" className="stamp stamp-in text-sm text-bad sm:text-lg">Price above PO</span>}
        </div>

        <div className="flex items-end justify-between gap-4">
          <div className={`transition-opacity duration-300 ${signed ? "opacity-100" : "opacity-0"}`}>
            <p className="text-faint">Approved for payment by</p>
            <p className="mt-5 w-40 border-t border-line-strong pt-1 text-[10px] uppercase tracking-[0.1em] text-faint sm:w-52">
              a person · review queue
            </p>
          </div>
          <p className={`text-right text-[10px] uppercase tracking-[0.1em] text-faint transition-opacity duration-300 ${signed ? "opacity-100" : "opacity-0"}`}>
            agent actions: read · match · propose<br />no pay action
          </p>
        </div>

      </div>
    </div>
  );
}
