"use client";

import { useQueue } from "@/lib/queue-context";
import { api } from "@/lib/api";

export function StatusBar() {
  const { snapshot, status } = useQueue();

  return (
    <div className="ml-auto flex items-center gap-4 mono text-[11px] text-ink3">
      <button
        onClick={() => api.degraded(!snapshot?.degraded)}
        title="Scenario 06 — Layer 0 keeps gating deterministically, offline."
        className="px-2.5 py-1 border border-rule hover:border-critical
                   hover:text-critical transition-colors">
        {snapshot?.degraded ? "restore model" : "kill model"}
      </button>
      <span className="flex items-center gap-1.5">
        <span className={
          status === "live" ? "w-1.5 h-1.5 rounded-full bg-accent"
                            : "w-1.5 h-1.5 rounded-full bg-signal"
        } />
        {status}
      </span>
      <span>{snapshot?.now?.slice(11, 16) ?? "--:--"}</span>
    </div>
  );
}
