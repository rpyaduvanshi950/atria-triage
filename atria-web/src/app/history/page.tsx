"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { History } from "@/types/atria";

const FRIENDLY: Record<string, string> = {
  nurse_assessment: "nurse chose (blind)", atria_reveal: "ATRIA revealed",
  sign_off: "signed off", override: "override",
  worsening_reported: "change reported", abstain: "refused to score",
  arrival: "arrived", escalation: "escalated", seen: "taken through",
  departure: "left",
};

export default function HistoryPage() {
  const [mode, setMode] = useState<"audit" | "general">("audit");
  const [data, setData] = useState<History | null>(null);

  useEffect(() => {
    const load = () => api.history(mode).then(setData).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [mode]);

  return (
    <>
      <div className="flex items-baseline gap-5 flex-wrap mb-3">
        <div>
          <span className="text-[14px] text-ink2">Record</span>
          <div className={data?.intact ? "text-ok text-[22px] font-bold"
                                       : "text-danger text-[22px] font-bold"}>
            {data ? (data.intact ? "Complete and unaltered" : "ALTERED") : "…"}
          </div>
        </div>
        <p className="text-[15px] text-ink2 max-w-2xl leading-relaxed">
          Nothing here can be edited or deleted. A correction is added as a new
          entry linked to the old one, so months later you can still see exactly
          what was decided and what it was based on.
        </p>
      </div>

      <div className="flex gap-1 mb-3">
        {(["audit", "general"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
                  className={m === mode
                    ? "px-4 py-2.5 rounded-lg text-[15px] border-2 border-brand bg-brandsoft text-brand font-semibold"
                    : "px-4 py-2.5 rounded-lg text-[15px] border-2 border-line bg-card text-ink2"}>
            {m === "audit" ? "Decisions only" : "Everything"}
          </button>
        ))}
      </div>
      <p className="text-[15px] text-ink2 mb-4 leading-relaxed max-w-3xl">
        <b className="text-ink">Decisions only</b> shows what you or ATRIA decided.
        <b className="text-ink"> Everything</b> also shows arrivals, moves up the
        queue, and patients going through.
      </p>

      <div className="border-2 border-line rounded-lg overflow-x-auto bg-card">
        <table className="w-full text-[14px]">
          <thead>
            <tr className="bg-sunk text-[13px] text-ink2 font-semibold">
              {["#", "Time", "What happened", "Patient", "Details", "Fingerprint", "Follows"].map((h) => (
                <th key={h} className="text-left px-3 py-2 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.events ?? []).slice().reverse().map((e) => {
              const { seq, at, kind, stay_id, hash, prev, ...rest } = e;
              return (
                <tr key={seq} className="border-t border-line2 align-top">
                  <td className="mono px-3 py-2 text-ink3">{seq}</td>
                  <td className="mono px-3 py-2 text-ink3">{String(at).slice(11, 19)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{FRIENDLY[kind] ?? kind}</td>
                  <td className="mono px-3 py-2 text-ink3">{stay_id}</td>
                  <td className="px-3 py-2 text-ink2 max-w-[380px] truncate">
                    {Object.entries(rest)
                      .filter(([, v]) => v !== null && v !== "" && v !== false)
                      .map(([k, v]) => `${k}=${v}`).join(", ")}
                  </td>
                  <td className="mono px-3 py-2 text-brand">{String(hash).slice(0, 8)}</td>
                  <td className="mono px-3 py-2 text-ink3">{String(prev).slice(0, 8)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!data?.events.length && (
        <p className="text-[15px] text-ink2 py-8 text-center">
          Nothing recorded yet — give the shift a moment.
        </p>
      )}
    </>
  );
}
