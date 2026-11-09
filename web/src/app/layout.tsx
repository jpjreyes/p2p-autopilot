import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Legacy Portal Agent",
  description:
    "A computer-use agent that works supplier portals with no API, reads invoices and runs the 3-way match in code. A human approves every payment.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="border-b border-line">
          <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 text-sm">
            <Link href="/" className="font-semibold tracking-tight">
              Legacy Portal Agent
            </Link>
            <Link href="/" className="text-muted hover:text-foreground">
              Runs
            </Link>
            <Link href="/review" className="text-muted hover:text-foreground">
              Review queue
            </Link>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-line px-4 py-3 text-center text-xs text-muted">
          Test environment: mock supplier portals and generated invoices. The agent never approves or pays.
        </footer>
      </body>
    </html>
  );
}
