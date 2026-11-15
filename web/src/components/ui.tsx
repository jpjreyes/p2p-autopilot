import type { ReactNode } from "react";
import type { Tone } from "@/lib/api";

const INK: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  neutral: "text-muted",
  brand: "text-foreground",
  accent: "text-accent",
};

/** A status mark: typewriter capitals in the ink of its meaning, boxed like a ledger annotation. */
export function Badge({ tone = "neutral", children, dot = false }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap border border-current px-1.5 py-px font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] ${INK[tone]}`}>
      {dot && <span className="size-1.5 bg-current" />}
      {children}
    </span>
  );
}

/** A rubber stamp, for the one mark on a page that matters most. */
export function Stamp({ tone = "bad", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={`stamp text-xs ${INK[tone]} ${className}`}>{children}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`border border-line bg-surface ${className}`}>{children}</div>;
}

/** A figure on the ledger: rule above, typewriter label, the number set large in the book face. */
export function Stat({ label, value, note, tone }: { label: ReactNode; value: ReactNode; note?: ReactNode; tone?: Tone }) {
  const color = tone ? INK[tone] : "text-foreground";
  return (
    <div className="border-t-2 border-line-strong pt-3">
      <p className="label text-muted">{label}</p>
      <p className={`tabular mt-2 font-serif text-3xl leading-none tracking-tight sm:text-4xl ${color}`}>{value}</p>
      {note && <p className="mt-2 text-xs leading-relaxed text-faint">{note}</p>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children, actions }: {
  eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="mb-8 border-b border-line-strong pb-6">
      {eyebrow && <p className="label mb-3 text-bad">§ {eyebrow}</p>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h1 className="font-serif text-4xl leading-[1.02] tracking-tight sm:text-5xl">{title}</h1>
          {children && <div className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">{children}</div>}
        </div>
        {actions && <div className="flex gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Button({ children, variant = "primary", className = "", ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = {
    primary: "bg-foreground text-background hover:bg-foreground/85",
    secondary: "border border-line-strong text-foreground hover:bg-surface-2",
    danger: "border border-bad text-bad hover:bg-bad-soft",
    ghost: "text-muted hover:bg-surface-2 hover:text-foreground",
  }[variant];
  return (
    <button {...props}
      className={`inline-flex items-center justify-center gap-2 px-3.5 py-2 font-mono text-xs font-medium uppercase tracking-[0.08em] transition disabled:cursor-not-allowed disabled:opacity-45 ${styles} ${className}`}>
      {children}
    </button>
  );
}

/** Mark: a ruled ledger square with a tick in blue ink. */
export function Logo({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" fill="none" className="stroke-foreground" strokeWidth="2" />
      <path d="M6 11h20M6 16h20M6 21h20" className="stroke-faint" strokeWidth="1" />
      <path d="M9 16.5l4.5 4.5L24 9.5" fill="none" className="stroke-bad" strokeWidth="3" strokeLinecap="square" />
    </svg>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-6 py-14 text-center font-mono text-xs uppercase tracking-[0.08em] text-muted">{children}</div>;
}
