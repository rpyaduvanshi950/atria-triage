"use client";

/**
 * The readings, colour-coded.
 *
 * Colour here is a reading aid and nothing more. Every clinical decision is
 * made on the server against age-banded thresholds this component does not
 * have, so a tile may never be the reason a patient is banded, warned about, or
 * held for justification. It exists so a nurse can see at a glance which
 * numbers are the reason ATRIA is worried.
 */
import clsx from "clsx";
import { VITAL_INFO, vitalLevel } from "@/types/copy";
import type { QueueRow } from "@/types/atria";

const TONE = {
  normal:   { box: "border-line bg-card",          text: "text-ink",    tag: "" },
  abnormal: { box: "border-warn bg-warnsoft",      text: "text-warn",   tag: "High or low" },
  critical: { box: "border-danger bg-dangersoft",  text: "text-danger", tag: "Critical" },
} as const;

export function Vitals({ row, compact = false }: { row: QueueRow; compact?: boolean }) {
  return (
    <div className={clsx("grid gap-2", compact ? "grid-cols-5" : "grid-cols-2")}>
      {Object.entries(VITAL_INFO).map(([key, info]) => {
        const v = row.vitals[key as keyof typeof row.vitals];
        const missing = v === undefined || v === null;
        const tone = missing ? null : TONE[vitalLevel(key, v as number)];

        return (
          <div key={key}
               className={clsx("rounded-xl border p-2.5",
                               missing ? "border-warn bg-warnsoft border-dashed" : tone!.box)}>
            <div className="text-[12px] text-ink2">{info.label}</div>

            {missing ? (
              <div className={clsx("font-semibold text-warn leading-tight mt-0.5",
                                   compact ? "text-[13px]" : "text-[15px]")}>
                Not taken
              </div>
            ) : (
              <>
                <div className={clsx("font-bold leading-tight mt-0.5", tone!.text,
                                     compact ? "text-[18px]" : "text-[22px]")}>
                  {v}
                  <span className="text-[11px] font-normal text-ink3 ml-1">{info.unit}</span>
                </div>
                <div className={clsx("text-[11px]", tone!.tag ? tone!.text : "text-ink3")}>
                  {tone!.tag || `normal ${info.normal}`}
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
