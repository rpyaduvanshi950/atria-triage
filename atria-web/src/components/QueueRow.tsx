"use client";

import clsx from "clsx";
import type { QueueRow as Row } from "@/types/atria";

const LANE_TONE: Record<string, string> = {
  RESUS: "border-critical text-critical",
  ACUTE: "border-signal text-signal",
  "FAST TRACK": "border-rule text-ink3",
};

export function QueueRowCard({
  row, selected, onSelect, innerRef,
}: {
  row: Row;
  selected: boolean;
  onSelect: (r: Row) => void;
  innerRef?: (el: HTMLElement | null) => void;
}) {
  const treating = row.state === "IN TREATMENT";
  const why =
    row.red_flag || row.reasons.join(" · ") || row.needs_measurement || "—";

  return (
    <button
      ref={innerRef as never}
      onClick={() => onSelect(row)}
      aria-current={selected}
      aria-label={`${row.ticket}, band ${row.band}, ${row.complaint}, waited ${row.waited} minutes`}
      className={clsx(
        "w-full text-left grid grid-cols-[46px_1fr] gap-3 px-3 py-2.5 mb-1.5",
        "bg-surface border border-rule border-l-[3px] transition-colors",
        "hover:border-l-accent",
        treating && "opacity-40",
        row.abstained || row.red_flag
          ? "border-l-critical"
          : row.state === "ESCALATED"
            ? "border-l-signal"
            : row.state === "AWAITING"
              ? "border-l-accent"
              : "border-l-transparent",
        selected && "ring-1 ring-accent",
      )}
    >
      <div className="mono text-[21px] leading-none">
        {row.band}
        {row.band_before !== null && (
          <span className="block text-[9px] text-signal mt-1">
            ↑{row.band_before}
          </span>
        )}
      </div>

      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className={clsx("mono text-[8.5px] tracking-wider px-1.5 py-px border", LANE_TONE[row.lane])}>
            {row.lane}
          </span>
          <span className="mono text-[10px] text-accent border border-rule px-1.5">
            {row.ticket}
          </span>
          <span className="text-[13.5px] font-semibold truncate">{row.complaint}</span>
          <span className="mono text-[10.5px] text-ink3">
            {row.age !== null ? `${Math.round(row.age)}${row.gender ?? ""}` : "—"}
          </span>
          <span className="mono text-[10px] text-ink3 ml-auto shrink-0">
            {treating ? "in a bay" : `${row.waited}m`}
            {row.overdue_by > 0 && (
              <span className="text-signal"> · {row.overdue_by}m over</span>
            )}
          </span>
        </div>

        <div className="text-[11.5px] text-ink2 mt-1 truncate">{why}</div>

        <div className="flex gap-1 mt-1.5 flex-wrap">
          {row.red_flag && <Tag tone="critical">RED FLAG</Tag>}
          {row.abstained && <Tag tone="critical">ABSTAIN</Tag>}
          {row.needs_measurement && !row.red_flag && <Tag tone="signal">MEASURE</Tag>}
          {row.worsening && <Tag tone="signal">WORSENED</Tag>}
          <Tag tone={row.confidence === "HIGH" ? "accent" : row.confidence === "LOW" ? "critical" : "muted"}>
            TRIAGE {row.confidence}
          </Tag>
          <Tag tone={row.diagnostic_confidence === "HIGH" ? "accent" : row.diagnostic_confidence === "LOW" ? "critical" : "muted"}>
            DX {row.diagnostic_confidence}
          </Tag>
          {row.missing.length > 0 && (
            <Tag tone="signal">no {row.missing.slice(0, 2).join(", ")}</Tag>
          )}
        </div>
      </div>
    </button>
  );
}

function Tag({ children, tone }: { children: React.ReactNode; tone: string }) {
  const tones: Record<string, string> = {
    critical: "border-critical text-critical",
    signal: "border-signal text-signal",
    accent: "border-accent text-accent",
    muted: "border-rule text-ink3",
  };
  return (
    <span className={clsx("mono text-[8.5px] tracking-wider px-1.5 py-px border", tones[tone])}>
      {children}
    </span>
  );
}
