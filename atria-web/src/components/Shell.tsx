"use client";

/**
 * The signed-in chrome: navigation, who you are, and the way out.
 *
 * Tabs are filtered by what the role may actually do. This is a courtesy, not
 * a control — the server refuses regardless — but showing a flow coordinator a
 * "Decision history" tab that answers 403 is a worse interface than not showing
 * it at all.
 */
import Link from "next/link";
import { QueueProvider } from "@/lib/queue-context";
import { StatusBar } from "@/components/StatusBar";
import { useAuth } from "@/lib/auth-context";

const TABS = [
  ["/", "Patients", "queue:read"],
  ["/operations", "Department", "ops:read"],
  ["/logs", "Logs", "history:read"],
  ["/history", "Decision history", "history:read"],
] as const;

const ROLE_LABEL: Record<string, string> = {
  nurse: "Triage nurse",
  charge_nurse: "Charge nurse",
  clinician: "Clinician",
  ops: "Flow coordinator",
  auditor: "Clinical governance",
  admin: "Administrator",
};

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, signOut, can } = useAuth();

  return (
    <QueueProvider>
      <header className="border-b border-line bg-card">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6 flex-wrap">
          <span className="text-[20px] font-bold">ATRIA</span>
          <span className="text-[14px] text-ink3">Emergency triage board</span>
          <nav className="flex gap-1 ml-2">
            {TABS.filter(([, , permission]) => can(permission)).map(
              ([href, label]) => (
                <Link key={href} href={href}
                      className="px-4 py-2 rounded-xl text-[15px] text-ink2
                                 hover:bg-sunk hover:text-ink transition-colors">
                  {label}
                </Link>
              ),
            )}
          </nav>
          <StatusBar />
          <div className="ml-auto flex items-center gap-3">
            <span className="text-[14px] text-right leading-tight">
              <span className="block font-semibold">{user?.display}</span>
              <span className="block text-ink3">
                {ROLE_LABEL[user?.role ?? ""] ?? user?.role}
              </span>
            </span>
            <button onClick={signOut}
                    className="px-3 py-2 rounded-xl border border-line text-[14px]
                               text-ink2 hover:bg-sunk transition-colors">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-[1600px] mx-auto px-6 py-5">{children}</main>
    </QueueProvider>
  );
}
