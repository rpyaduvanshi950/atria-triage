"use client";

/**
 * The attention queue, virtualised.
 *
 * The board used to render `rows.slice(0, 14)`. That is fine for a demo and
 * wrong for the claim being made: a real department is two hundred people, and
 * a list that silently stops at fourteen is not a triage board, it is the top
 * of one. Everyone is rendered now; only the visible ones exist in the DOM.
 *
 * Two things this has to keep working while it scrolls:
 *
 * **FLIP still animates.** Rows that scroll out unregister themselves, so the
 * measure-and-animate pass only ever runs over what is on screen. A patient who
 * moves up while off-screen simply appears in their new place, which is correct
 * — there was nothing to see move.
 *
 * **Keyboard navigation stays in view.** `j`/`k` on a virtualised list is
 * useless unless the list scrolls to follow, because the selected row may not
 * be rendered at all.
 */
import { useEffect, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { QueueRowCard } from "@/components/QueueRow";
import type { QueueRow } from "@/types/atria";

/**
 * A labelled break in the list.
 *
 * Patients already in a treatment bay stay on the board on purpose — a nurse
 * needs to know who is where, not only who is queueing. But they were sitting
 * in a list headed "Attention order" with nothing to say they were no longer
 * waiting, which reads as "this person still needs you" when the opposite is
 * true. They now sit under their own heading, below everyone waiting.
 */
type Item = { kind: "row"; row: QueueRow } | { kind: "divider"; label: string };

//: Measured from the rendered card. The virtualiser re-measures each row as it
//: mounts, so this only has to be close enough to size the scrollbar sensibly.
const ESTIMATED_ROW_PX = 108;

export function QueueList({ rows, selectedTicket, onSelect, flipRef, scroller }: {
  rows: QueueRow[];
  selectedTicket: string | null;
  onSelect: (row: QueueRow) => void;
  flipRef: (key: string) => (el: HTMLElement | null) => void;
  /** Owned by the page so the FLIP hook can compensate for scroll position. */
  scroller: React.RefObject<HTMLDivElement | null>;
}) {

  const items = useMemo<Item[]>(() => {
    const waiting = rows.filter((r) => r.state !== "IN TREATMENT");
    const inside = rows.filter((r) => r.state === "IN TREATMENT");
    return [
      ...waiting.map((row) => ({ kind: "row" as const, row })),
      ...(inside.length
        ? [{ kind: "divider" as const,
             label: `In a treatment bay — ${inside.length} ${inside.length === 1 ? "patient" : "patients"}` },
           ...inside.map((row) => ({ kind: "row" as const, row }))]
        : []),
    ];
  }, [rows]);

  const virtual = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: (i) => (items[i]?.kind === "divider" ? 34 : ESTIMATED_ROW_PX),
    // Render a few rows beyond the fold so a FLIP animation into view has
    // something to animate, and so scrolling does not flash empty space.
    overscan: 6,
    getItemKey: (i) => {
      const it = items[i];
      return it.kind === "divider" ? "divider:treatment" : it.row.ticket;
    },
    /*
     * By default the virtualiser applies each row measurement inside
     * flushSync, to avoid a flicker while a fast scroll re-measures. Rows here
     * are measured by a ref callback, which React runs during commit — and
     * flushing synchronously from inside a commit is what React was warning
     * about: "flushSync was called from inside a lifecycle method".
     *
     * Turning it off lets the measurement land on the next ordinary render.
     * The flicker it guards against needs rows of wildly differing heights
     * scrolled quickly; these are near-uniform cards in a 640px window, and
     * nothing is visible. The warning was pointing at something real — React
     * can drop or mis-order a synchronous flush issued mid-commit — so this is
     * a fix rather than a way to silence it.
     */
    useFlushSync: false,
  });

  // Follow the selection. Without this, j/k walks off the bottom of the visible
  // window and the nurse is navigating a list they cannot see.
  const index = items.findIndex(
    (it) => it.kind === "row" && it.row.ticket === selectedTicket);
  useEffect(() => {
    if (index >= 0) virtual.scrollToIndex(index, { align: "auto" });
  }, [index, virtual]);

  if (items.length === 0) {
    return <p className="text-[15px] text-ink3">Nobody waiting.</p>;
  }

  return (
    <div ref={scroller}
         // A fixed viewport is what makes virtualisation possible at all. It is
         // tall enough to show the working set without the page itself scrolling.
         className="h-[640px] overflow-y-auto pr-1 -mr-1"
         role="list"
         aria-label={`Attention queue, ${rows.length} patients`}>
      <div className="relative w-full" style={{ height: virtual.getTotalSize() }}>
        {virtual.getVirtualItems().map((item) => {
          const entry = items[item.index];
          return (
            <div key={item.key}
                 ref={virtual.measureElement}
                 data-index={item.index}
                 role={entry.kind === "row" ? "listitem" : "presentation"}
                 className="absolute top-0 left-0 w-full"
                 style={{ transform: `translateY(${item.start}px)` }}>
              {entry.kind === "divider" ? (
                <p className="text-[13px] font-semibold text-ink3 uppercase
                              tracking-wide pt-3 pb-1.5 border-t border-line">
                  {entry.label}
                </p>
              ) : (
                <QueueRowCard row={entry.row}
                              selected={entry.row.ticket === selectedTicket}
                              onSelect={onSelect}
                              innerRef={flipRef(entry.row.ticket)} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
