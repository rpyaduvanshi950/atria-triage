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
  ["/", "Patients"],
  ["/operations", "Department"],
  ["/history", "Decision history"],
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/*
        * suppressHydrationWarning is on <body> only, and only for its own
        * attributes. Browser extensions — Grammarly, password managers, dark-mode
        * add-ons — inject attributes here before React hydrates, which React
        * then reports as a mismatch it cannot patch. That is the extension's
        * doing, not ours.
        *
        * The suppression does not extend to children, so a genuine mismatch
        * anywhere inside the app still surfaces. Putting it higher, or on a
        * component that renders real data, would hide the bugs worth seeing.
        */}
      <body className="min-h-screen" suppressHydrationWarning>
        <QueueProvider>
          {/* INT-008: simulation data must never be mistaken for a live read. */}
          <div className="bg-warn text-white text-center text-[14px] font-semibold py-1.5">
            SIMULATION — synthetic patients. Not a live department.
          </div>
          <header className="border-b border-line bg-card">
            <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6 flex-wrap">
              <span className="text-[20px] font-bold">ATRIA</span>
              <span className="text-[14px] text-ink3">Emergency triage board</span>
              <nav className="flex gap-1 ml-2">
                {TABS.map(([href, label]) => (
                  <Link key={href} href={href}
                        className="px-4 py-2 rounded-xl text-[15px] text-ink2
                                   hover:bg-sunk hover:text-ink transition-colors">
                    {label}
                  </Link>
                ))}
              </nav>
              <StatusBar />
            </div>
          </header>
          <main className="max-w-[1600px] mx-auto px-6 py-5">{children}</main>
        </QueueProvider>
      </body>
    </html>
  );
}
