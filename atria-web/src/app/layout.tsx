import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { QueueProvider } from "@/lib/queue-context";
import { StatusBar } from "@/components/StatusBar";

export const metadata: Metadata = {
  title: "ATRIA · live triage board",
  description:
    "Emergency-department triage that reorders attention continuously. " +
    "It supports the nurse; it never prescribes, and never lowers a priority on its own.",
};

const TABS = [
  ["/", "Assessment"],
  ["/operations", "Operations & Flow"],
  ["/history", "History"],
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <QueueProvider>
          <header className="border-b border-rule bg-surface">
            <div className="max-w-[1500px] mx-auto px-6 py-3 flex items-baseline gap-6 flex-wrap">
              <span className="text-[17px] font-semibold">ATRIA</span>
              <span className="mono text-[11px] text-ink3">a live queue, not a label</span>
              <nav className="flex gap-1 ml-4">
                {TABS.map(([href, label]) => (
                  <Link key={href} href={href}
                        className="px-3 py-1.5 text-[13px] text-ink2 border border-transparent
                                   hover:border-rule hover:text-ink transition-colors">
                    {label}
                  </Link>
                ))}
              </nav>
              <StatusBar />
            </div>
          </header>
          <main className="max-w-[1500px] mx-auto px-6 py-5">{children}</main>
        </QueueProvider>
      </body>
    </html>
  );
}
