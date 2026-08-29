"use client";

/**
 * Escalations, spoken.
 *
 * A queue that reorders silently is invisible to a screen reader — the FLIP
 * animation carries the whole message, and an animation is not information a
 * blind nurse can use. This watches the snapshot for patients who moved up and
 * announces them in a polite live region.
 *
 * `polite` rather than `assertive` on purpose: assertive interrupts whatever
 * the nurse is reading mid-sentence, which during an assessment is the wrong
 * trade. The queue is important; the sentence they are in the middle of is the
 * patient in front of them.
 */
import { useEffect, useRef, useState } from "react";
import { useQueue } from "@/lib/queue-context";

export function Announcer() {
  const { snapshot } = useQueue();
  const previous = useRef(new Map<string, number>());
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!snapshot) return;
    const moved: string[] = [];
    const next = new Map<string, number>();

    for (const row of snapshot.rows) {
      next.set(row.ticket, row.band);
      const before = previous.current.get(row.ticket);
      // Lower band number is more urgent. Only escalations are announced —
      // nothing in the system lowers a priority without a human, and that
      // human already knows they did it.
      if (before !== undefined && row.band < before) {
        moved.push(`${row.ticket} moved up to priority ${row.band}`);
      }
    }

    // Skip the first snapshot: every patient is "new" and announcing the whole
    // board on connect is noise, not information.
    if (previous.current.size > 0 && moved.length > 0) {
      setMessage(moved.slice(0, 3).join(". ") +
                 (moved.length > 3 ? `. And ${moved.length - 3} more.` : "."));
    }
    previous.current = next;
  }, [snapshot]);

  return (
    <p role="status" aria-live="polite" className="sr-only">{message}</p>
  );
}
