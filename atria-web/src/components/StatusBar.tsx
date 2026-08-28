"use client";

import clsx from "clsx";
import { useQueue } from "@/lib/queue-context";
import { api } from "@/lib/api";

export function StatusBar() {
  const { snapshot, status } = useQueue();

  return (
    <div className="ml-auto flex items-center gap-4 text-[14px] text-ink2">
      <button
        onClick={() => api.degraded(!snapshot?.degraded)}
        title="Turns the suggestion engine off. The safety rules keep running."
        className="px-3 py-2 rounded-xl border border-line hover:border-danger
                   hover:text-danger transition-colors text-[14px]">
        {snapshot?.degraded ? "Turn suggestions back on" : "Turn suggestions off"}
      </button>
      <span className="flex items-center gap-2">
        <span className={clsx("w-2 h-2 rounded-full",
                              status === "live" ? "bg-ok" : "bg-warn")} />
        {status === "live" ? "Connected" : "Reconnecting"}
      </span>
      <span className="mono">{snapshot?.now?.slice(11, 16) ?? "--:--"}</span>
    </div>
  );
}
