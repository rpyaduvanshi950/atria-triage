"use client";

/**
 * Nothing renders until we know who is asking.
 *
 * The board is not merely styled behind this — it is not mounted, so the
 * websocket never opens and no patient data is fetched. That matters: a
 * "hidden" board is one devtools panel away from being visible, and the whole
 * design of this system is that a guarantee lives on the server side of the
 * wire.
 */
import { useAuth } from "@/lib/auth-context";
import { SignIn } from "@/components/SignIn";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <p className="text-center text-ink3 text-[15px] mt-16">Checking session…</p>
    );
  }
  if (!user) return <SignIn />;
  return <>{children}</>;
}
