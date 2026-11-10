import type { ReactNode } from "react";
import type { Tone } from "@/lib/api";

const TONES: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  neutral: "bg-surface-2 text-muted",
  brand: "bg-brand-soft text-brand",
  accent: "bg-surface-2 text-accent",
};

export function Badge({ tone = "neutral", children, dot = false }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-surface shadow-card ${className}`}>{children}</div>;
}

export function Stat({ label, value, note, tone }: { label: ReactNode; value: ReactNode; note?: ReactNode; tone?: Tone }) {
  const color = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-foreground";
  return (
    <Card className="p-4 sm:p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className={`tabular mt-2 text-2xl font-semibold tracking-tight sm:text-3xl ${color}`}>{value}</p>
      {note && <p className="mt-1.5 text-xs leading-relaxed text-faint">{note}</p>}
    </Card>
  );
}

export function PageHeader({ eyebrow, title, children, actions }: {
  eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="max-w-3xl">
        {eyebrow && <p className="mb-2 text-sm font-medium text-brand">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
        {children && <div className="mt-2 text-[15px] leading-relaxed text-muted">{children}</div>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function Button({ children, variant = "primary", className = "", ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = {
    primary: "bg-brand text-brand-ink hover:opacity-90",
    secondary: "border border-line-strong bg-surface text-foreground hover:bg-surface-2",
    danger: "border border-line-strong bg-surface text-bad hover:bg-bad-soft",
    ghost: "text-muted hover:bg-surface-2 hover:text-foreground",
  }[variant];
  return (
    <button {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${styles} ${className}`}>
      {children}
    </button>
  );
}

export function Logo({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" className="fill-brand" />
      <path d="M9 9h9.5a4.5 4.5 0 0 1 0 9H13v5H9z" className="fill-brand-ink" />
      <path d="M13 13h5.3a.9.9 0 0 1 0 1.8H13z" className="fill-brand" />
      <circle cx="22.5" cy="22" r="2.5" className="fill-brand-ink" />
    </svg>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-6 py-14 text-center text-sm text-muted">{children}</div>;
}
