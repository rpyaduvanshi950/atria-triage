"use client";

import clsx from "clsx";
import { PATHWAY_NAME, VITAL_INFO } from "@/types/copy";
import type { QueueRow } from "@/types/atria";

export function PatientRecord({ row }: { row: QueueRow }) {
  return (
    <div>
      <div className="card border border-line p-4">
        <div className="text-[18px] font-semibold">{row.complaint}</div>
        <div className="text-[15px] text-ink2 mt-0.5">
          {row.age !== null ? `${Math.round(row.age)} years, ${row.gender ?? "—"}` : "Age unknown"}
          {" · "}waiting {row.waited} min
        </div>
      </div>

      <h3 className="text-[15px] font-semibold mt-5 mb-2">Observed</h3>
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(VITAL_INFO).map(([key, info]) => {
          const v = row.vitals[key as keyof typeof row.vitals];
          const missing = v === undefined || v === null;
          return (
            <div key={key}
                 className={clsx("rounded-xl border p-3",
                                 missing ? "border-warn bg-warnsoft" : "border-line bg-card")}>
              <div className="text-[13px] text-ink2">{info.label}</div>
              {missing ? (
                <>
                  <div className="text-[16px] font-semibold text-warn leading-tight mt-0.5">
                    Not taken
                  </div>
                  <div className="text-[13px] text-warn">Please measure</div>
                </>
              ) : (
                <>
                  <div className="text-[24px] font-bold leading-tight mt-0.5">
                    {v}<span className="text-[13px] font-normal text-ink3 ml-1">{info.unit}</span>
                  </div>
                  <div className="text-[13px] text-ink3">normal {info.normal}</div>
                </>
              )}
            </div>
          );
        })}
      </div>

      <h3 className="text-[15px] font-semibold mt-5 mb-2">Main concern</h3>
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
          <b>{row.missing.join(", ")} never measured.</b> A missing reading is
          never treated as a normal one.
        </p>
      )}

      {row.abstained && (
        <p className="text-[15px] mt-3 px-3 py-2.5 rounded-lg bg-dangersoft text-danger">
          <b>ATRIA will not give a score for this patient.</b> {row.abstain_reason}
        </p>
      )}

      {row.conflicts.map((c) => (
        <p key={c} className="text-[15px] mt-3 px-3 py-2.5 rounded-lg bg-dangersoft text-danger">
          <b>Careful — two problems that pull against each other.</b> {c}
        </p>
      ))}
    </div>
  );
}
