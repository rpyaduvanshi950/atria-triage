"use client";

import clsx from "clsx";
import { VITAL_REF, type QueueRow } from "@/types/atria";

export function PatientRecord({ row }: { row: QueueRow }) {
  return (
    <div>
      <p className="text-[13.5px] font-semibold">
        {row.complaint}
        <span className="mono text-[11px] text-ink3 font-normal ml-2">
          {row.age !== null ? `${Math.round(row.age)}${row.gender ?? ""}` : "—"} · waited {row.waited}m
        </span>
      </p>

      <div className="grid grid-cols-2 gap-1.5 mt-2.5">
        {Object.entries(VITAL_REF).map(([key, ref]) => {
          const v = row.vitals[key as keyof typeof row.vitals];
          const missing = v === undefined || v === null;
          return (
            <div key={key}
                 className={clsx("bg-surface border px-2.5 py-2",
                                 missing ? "border-dashed border-signal" : "border-rule")}>
              <div className="mono text-[9px] tracking-widest uppercase text-ink3">{ref.label}</div>
              <div className={clsx("mono leading-tight",
                                   missing ? "text-[12px] text-signal" : "text-[17px]")}>
                {missing ? "not taken" : v}
              </div>
              <div className="mono text-[9px] text-ink3">
                {missing ? "must be measured" : `normal ${ref.range} ${ref.unit}`}
              </div>
            </div>
          );
        })}
      </div>

      <h3 className="mono text-[10.5px] tracking-widest uppercase text-ink3 border-b border-rule pb-1.5 mt-4 mb-2">
        Why this band
      </h3>
      <p className="text-[12px] text-ink2 leading-relaxed">
        {row.red_flag || row.reasons.join(" · ") || "—"}
      </p>
      {row.pathway && (
        <p className="text-[11.5px] text-ink3 mt-1.5">
          Pathway engaged: <b className="text-ink2">{row.pathway}</b> — which of the
          three gates (lungs, heart, brain) is closing.
        </p>
      )}
      {row.missing.length > 0 && (
        <p className="border-l-2 border-signal bg-surface px-3 py-2 mt-2.5 text-[11.5px] text-signal">
          Never measured: {row.missing.join(", ")}. A missing vital is never read as a normal one.
        </p>
      )}
      {row.abstained && (
        <p className="border-l-2 border-critical bg-surface px-3 py-2 mt-2 mono text-[11px] text-critical leading-relaxed">
          {row.abstain_reason || "system abstained"}
        </p>
      )}
      {row.conflicts.map((c) => (
        <p key={c} className="border-l-2 border-critical bg-surface px-3 py-2 mt-2 text-[11.5px] text-critical leading-relaxed">
          <b>Treatment conflict</b> — {c}
        </p>
      ))}
    </div>
  );
}
