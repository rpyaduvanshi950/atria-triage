"use client";

import clsx from "clsx";
import { LANE_NAME, PRIORITY_NAME } from "@/types/copy";
import type { QueueRow as Row } from "@/types/atria";

/**
 * One patient in the queue.
 *
 * Read at arm's length on a tablet: the priority number is the largest thing on
 * the row, the reason is one plain sentence, and every colour is paired with a
 * word so it still works for a colour-blind reader or a bad screen.
 */
export function QueueRowCard({
  row, selected, onSelect, innerRef,
}: {
  row: Row;
  selected: boolean;
  onSelect: (r: Row) => void;
  innerRef?: (el: HTMLElement | null) => void;
}) {
  const treating = row.state === "IN TREATMENT";
  const urgent = row.band <= 2;
  const why = row.red_flag || row.reasons[0] || row.needs_measurement || "";

  // Signed off by the nurse, but nobody has taken them through yet.
  const awaitingBay = row.signed_off && !treating;

  return (
    <button
      ref={innerRef as never}
      onClick={() => onSelect(row)}
      aria-current={selected}
      aria-label={
        `${row.ticket}, priority ${row.band} ${PRIORITY_NAME[row.band]}, ` +
        `${row.complaint}, waiting ${row.waited} minutes`
      }
      className={clsx(
        "w-full text-left flex gap-4 items-start p-4 mb-2 rounded-xl bg-card",
        "shadow-[0_1px_2px_rgba(33,52,58,.06)] transition-shadow hover:shadow-md",
        /*
         * Border colour answers one question: is anyone doing anything for this
         * patient right now?
         *
         *   green   in a bay — being treated
         *   red     signed off and still waiting for a bay. Triage is finished
         *           and nothing further is happening, which is the group that
         *           gets forgotten, so it is the loudest thing on the card.
         *
         * Only when neither applies does the border go back to describing the
         * triage itself — a red flag, an escalation, or the current selection.
         */
        treating
          ? "border-2 border-ok bg-oksoft/40"
          : awaitingBay
            ? "border-2 border-danger"
            : row.red_flag || row.abstained
              ? "border border-danger"
              : row.state === "ESCALATED"
                ? "border border-warn"
                : selected
                  ? "border border-brand"
                  : "border border-line",
      )}
    >
      <div className={clsx(
        "shrink-0 w-14 h-14 rounded-xl grid place-content-center text-center",
        urgent ? "bg-dangersoft" : row.band === 3 ? "bg-warnsoft" : "bg-sunk",
      )}>
        <div className={clsx("text-2xl font-bold leading-none",
                             urgent ? "text-danger" : "text-ink")}>
          {row.band}
        </div>
        {row.band_before !== null && (
          <div className="text-[10px] font-semibold text-warn mt-0.5">
            was {row.band_before}
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-semibold text-[17px]">{row.complaint}</span>
          <span className="text-ink2 text-[15px]">
            {row.age !== null ? `${Math.round(row.age)} ${row.gender ?? ""}` : "age unknown"}
          </span>
          <span className="mono text-[13px] text-ink3">{row.ticket}</span>
        </div>

        <div className="text-[15px] text-ink2 mt-0.5">
          <b className="text-ink">{PRIORITY_NAME[row.band]}</b>
          <span className="text-ink3"> · {LANE_NAME[row.lane] ?? row.lane}</span>
          <span className="text-ink3"> · waiting {treating ? "— in a room" : `${row.waited} min`}</span>
          {row.overdue_by > 0 && !treating && (
            <b className="text-warn"> · {row.overdue_by} min overdue for a recheck</b>
          )}
        </div>

        {why && <div className="text-[15px] text-ink2 mt-1.5 line-clamp-2">{why}</div>}

        <div className="flex gap-1.5 mt-2 flex-wrap">
          {row.red_flag && <Chip tone="danger">Safety rule — see now</Chip>}
          {row.abstained && <Chip tone="danger">Needs you to decide</Chip>}
          {row.needs_measurement && !row.red_flag && <Chip tone="warn">Take vitals</Chip>}
          {row.worsening && <Chip tone="warn">Getting worse</Chip>}
          {row.missing.length > 0 && (
            <Chip tone="warn">No {row.missing.slice(0, 2).join(", ")}</Chip>
          )}
          {treating && <Chip tone="plain">In treatment</Chip>}
        </div>
      </div>
    </button>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone: string }) {
  const tones: Record<string, string> = {
    danger: "bg-dangersoft text-danger",
    warn: "bg-warnsoft text-warn",
    ok: "bg-oksoft text-ok",
    plain: "bg-sunk text-ink2",
  };
  return (
    <span className={clsx("text-[13px] font-medium px-2 py-0.5 rounded", tones[tone])}>
      {children}
    </span>
  );
}
