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
import { useEffect } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { QueueRowCard } from "@/components/QueueRow";
import type { QueueRow } from "@/types/atria";

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

  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ESTIMATED_ROW_PX,
    // Render a few rows beyond the fold so a FLIP animation into view has
    // something to animate, and so scrolling does not flash empty space.
    overscan: 6,
    getItemKey: (i) => rows[i].ticket,
  });

  // Follow the selection. Without this, j/k walks off the bottom of the visible
  // window and the nurse is navigating a list they cannot see.
  const index = rows.findIndex((r) => r.ticket === selectedTicket);
  useEffect(() => {
    if (index >= 0) virtual.scrollToIndex(index, { align: "auto" });
  }, [index, virtual]);

  if (rows.length === 0) {
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
          const row = rows[item.index];
          return (
            <div key={item.key}
                 ref={virtual.measureElement}
                 data-index={item.index}
                 role="listitem"
                 className="absolute top-0 left-0 w-full"
                 style={{ transform: `translateY(${item.start}px)` }}>
              <QueueRowCard row={row}
                            selected={row.ticket === selectedTicket}
                            onSelect={onSelect}
                            innerRef={flipRef(row.ticket)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
