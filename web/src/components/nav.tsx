"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CLIENT } from "@/lib/api";
import { Logo } from "./ui";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/process", label: "Process" },
  { href: "/risk", label: "Risk" },
  { href: "/brief", label: "Brief" },
  { href: "/runs", label: "Runs" },
  { href: "/review", label: "Review" },
  { href: "/evals", label: "Evals" },
];

export function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-0 z-30 border-b border-line-strong bg-background/90 backdrop-blur-sm">
      <div className="border-b border-line">
        <div className="mx-auto flex h-7 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <span className="label truncate text-faint">{CLIENT} · Accounts payable desk</span>
          <span className="label hidden text-faint sm:inline">Ledger 2019 · BPI SAP log</span>
        </div>
      </div>
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:gap-8 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <Logo />
          <span className="hidden font-serif text-xl italic tracking-tight sm:inline">P2P Autopilot</span>
        </Link>
        <nav className="-mx-1 flex items-center overflow-x-auto [scrollbar-width:none]">
          {LINKS.map((l, i) => (
            <Link key={l.href} href={l.href} aria-current={active(l.href) ? "page" : undefined}
              className={`flex items-baseline gap-1.5 whitespace-nowrap px-2 py-1 font-mono text-[12.5px] uppercase tracking-[0.08em] transition sm:px-2.5 ${active(l.href) ? "text-foreground" : "text-muted hover:text-foreground"}`}>
              <span className={`text-[10px] ${active(l.href) ? "text-bad" : "text-faint"}`}>0{i + 1}</span>
              <span className={`border-b-2 pb-px ${active(l.href) ? "border-bad" : "border-transparent"}`}>{l.label}</span>
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
