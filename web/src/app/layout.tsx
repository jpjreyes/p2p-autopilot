import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader } from "next/font/google";
import { Nav } from "@/components/nav";
import "./globals.css";

const plexSans = IBM_Plex_Sans({ variable: "--font-plex-sans", subsets: ["latin"], weight: ["400", "500", "600"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500", "700"] });
const newsreader = Newsreader({
  variable: "--font-newsreader", subsets: ["latin"], style: ["normal", "italic"], axes: ["opsz"],
});

export const metadata: Metadata = {
  title: { default: "P2P Autopilot", template: "%s · P2P Autopilot" },
  description:
    "A computer-use agent that collects invoices from supplier portals with no API, reads them, runs the 3-way match in code and sends every payment to a person for approval.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} ${newsreader.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background font-sans text-foreground">
        <Nav />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6 sm:py-14">{children}</main>
        <footer className="border-t border-line-strong">
          <div className="mx-auto grid max-w-6xl gap-3 px-4 py-6 sm:grid-cols-[1fr_auto] sm:px-6">
            <p className="label text-faint">
              Test environment · mock supplier portals · generated invoices on real SAP purchase orders (BPI 2019)
            </p>
            <div className="grid gap-1 sm:justify-items-end">
              <p className="label text-faint">The agent cannot approve or pay</p>
              <a
                className="label text-faint underline decoration-dotted underline-offset-4 hover:text-foreground"
                href="https://github.com/jpreyesm03/p2p-autopilot#models-and-mlops"
                target="_blank"
                rel="noreferrer"
              >
                Models and data platform ↗
              </a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
