"use client";

import { PATHWAY_NAME } from "@/types/copy";
import { Vitals } from "@/components/Vitals";
import type { QueueRow } from "@/types/atria";

export function PatientRecord({ row }: { row: QueueRow }) {
  return (
    <div>
      <div className="card border border-line p-4">
        <div className="text-[18px] font-semibold">{row.complaint}</div>
        <div className="text-[15px] text-ink2 mt-0.5">
          {row.age !== null ? `${Math.round(row.age)} years, ${row.gender ?? "?"}` : "Age unknown"}
          {" · "}waiting {row.waited} min
        </div>
      </div>

      <h3 className="text-[15px] font-semibold mt-4 mb-2">Observed</h3>
      <Vitals row={row} />

      <h3 className="text-[15px] font-semibold mt-4 mb-2">Main concern</h3>
      <p className="text-[15px] text-ink2 leading-relaxed">
        {row.red_flag || row.reasons.join(". ") || "Nothing unusual in the vitals."}
      </p>

      {row.pathway && (
        <p className="text-[15px] mt-2 px-3 py-2 rounded-lg bg-sunk">
          {PATHWAY_NAME[row.pathway] ?? row.pathway}
        </p>
      )}

      {row.missing.length > 0 && (
        <p className="text-[15px] mt-3 px-3 py-2.5 rounded-lg bg-warnsoft text-warn">
          <b>{row.missing.join(", ")} never measured.</b> Never scored as normal.
        </p>
      )}

      {row.abstained && (
        <p className="text-[15px] mt-3 px-3 py-2.5 rounded-lg bg-dangersoft text-danger">
          <b>ATRIA will not give a score for this patient.</b> {row.abstain_reason}
        </p>
      )}

      {row.conflicts.map((c) => (
        <p key={c} className="text-[15px] mt-3 px-3 py-2.5 rounded-lg bg-dangersoft text-danger">
          <b>Two problems that pull against each other.</b> {c}
        </p>
      ))}
    </div>
  );
}
