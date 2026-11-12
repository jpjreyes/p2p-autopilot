import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "P2P Autopilot", template: "%s · P2P Autopilot" },
  description:
    "A computer-use agent that collects invoices from supplier portals with no API, reads them, runs the 3-way match in code and sends every payment to a person for approval.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <Nav />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs text-faint sm:px-6">
            <span>Test environment: mock supplier portals and generated invoices. The agent cannot approve or pay.</span>
            <span>Playwright · Claude · FastAPI · Postgres · Next.js</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
