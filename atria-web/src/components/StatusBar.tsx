"use client";

import clsx from "clsx";
import { useQueue } from "@/lib/queue-context";

/**
 * Connection and clock only.
 *
 * The suggestions toggle used to live here, wedged between the navigation and
 * the clock, where it read as part of the chrome rather than something that
 * changes what the board does. It is a labelled control on the board now.
 */
export function StatusBar() {
  const { snapshot, status } = useQueue();

  return (
    <div className="ml-auto flex items-center gap-4 text-[14px] text-ink2">
      <span className="flex items-center gap-2">
        <span className={clsx("w-2 h-2 rounded-full",
                              status === "live" ? "bg-ok" : "bg-warn")} />
        {status === "live" ? "Connected" : "Reconnecting"}
      </span>
      <span className="mono">{snapshot?.now?.slice(11, 16) ?? "--:--"}</span>
    </div>
  );
}
