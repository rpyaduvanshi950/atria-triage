import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { AuthGate } from "@/components/AuthGate";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "ATRIA · live triage board",
  description:
    "Emergency-department triage that reorders attention continuously. " +
    "It supports the nurse; it never prescribes, and never lowers a priority on its own.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    /*
     * suppressHydrationWarning sits on <html> and <body> because browser
     * extensions mutate both before React hydrates — Grammarly writes
     * data-gr-ext-installed on <body>, QuillBot writes data-qb-installed on
     * <html>, password managers and dark-mode add-ons do the same. React then
     * reports a mismatch it cannot patch, for markup we did not write.
     *
     * This is narrower than it looks. The flag suppresses only the element's
     * OWN attributes and text — it does not extend to descendants — so a
     * genuine mismatch inside the app still surfaces. That is why it is safe
     * here and would not be safe on a component rendering patient data.
     */
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen" suppressHydrationWarning>
        <AuthProvider>
          {/* INT-008: simulation data must never be mistaken for a live read.
              Outside the gate on purpose — it is true of the sign-in page too. */}
          <div className="bg-warn text-white text-center text-[14px] font-semibold py-1.5">
            SIMULATION — synthetic patients. Not a live department.
          </div>
          <AuthGate>
            <Shell>{children}</Shell>
          </AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
