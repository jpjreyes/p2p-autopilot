"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Building2 } from "lucide-react";
import { CLIENT } from "@/lib/api";
import { Logo } from "./ui";

const LINKS = [
  { href: "/", label: "Overview", short: "Home" },
  { href: "/process", label: "Process", short: "See" },
  { href: "/risk", label: "Risk", short: "Risk" },
  { href: "/brief", label: "Weekly brief", short: "Brief" },
  { href: "/runs", label: "Agent runs", short: "Runs" },
  { href: "/review", label: "Review queue", short: "Review" },
  { href: "/evals", label: "Evals", short: "Evals" },
];

export function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:gap-6 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
          <Logo />
          <span className="hidden sm:inline">P2P Autopilot</span>
        </Link>
        <nav className="flex items-center gap-1 overflow-x-auto text-sm">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}
              className={`whitespace-nowrap rounded-md px-2.5 py-1.5 transition sm:px-3 ${active(l.href) ? "bg-surface-2 font-medium text-foreground" : "text-muted hover:text-foreground"}`}>
              <span className="sm:hidden">{l.short}</span>
              <span className="hidden sm:inline">{l.label}</span>
            </Link>
          ))}
        </nav>
        <div className="ml-auto hidden items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted md:flex">
          <Building2 className="size-3.5" />
          {CLIENT} · Accounts payable
        </div>
      </div>
    </header>
  );
}
