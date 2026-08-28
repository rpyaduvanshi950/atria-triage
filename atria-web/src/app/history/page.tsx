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
          <span className="mono text-[9.5px] tracking-widest uppercase text-ink3">Chain</span>
          <div className={data?.intact ? "text-accent text-[19px] font-semibold"
                                       : "text-critical text-[19px] font-semibold"}>
            {data ? (data.intact ? "intact" : "BROKEN") : "…"}
          </div>
        </div>
        <p className="text-[12px] text-ink2 max-w-2xl leading-relaxed">
          {data?.note}. Append-only: a correction creates a new linked event, it never
          rewrites an old one. This is what makes a clinical decision reconstructable
          months later.
        </p>
      </div>

      <div className="flex gap-1 mb-3">
        {(["audit", "general"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
                  className={m === mode
                    ? "px-3 py-1.5 text-[12.5px] border border-accent text-accent"
                    : "px-3 py-1.5 text-[12.5px] border border-rule text-ink3 hover:text-ink2"}>
            {m === "audit" ? "Decisions" : "Everything"}
          </button>
        ))}
      </div>
      <p className="text-[11.5px] text-ink3 mb-3 leading-relaxed max-w-3xl">
        <b className="text-ink2">Decisions</b> shows only what a human or the model
        decided — the audit trail proper. <b className="text-ink2">Everything</b> adds
        arrivals, escalations and movements in time order.
      </p>

      <div className="border border-rule overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-surface2 mono text-[9.5px] tracking-widest uppercase text-ink3">
              {["#", "time", "event", "stay", "detail", "hash", "links to"].map((h) => (
                <th key={h} className="text-left px-3 py-2 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.events ?? []).slice().reverse().map((e) => {
              const { seq, at, kind, stay_id, hash, prev, ...rest } = e;
              return (
                <tr key={seq} className="border-t border-rule align-top">
                  <td className="mono px-3 py-1.5 text-ink3">{seq}</td>
                  <td className="mono px-3 py-1.5 text-ink3">{String(at).slice(11, 19)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{FRIENDLY[kind] ?? kind}</td>
                  <td className="mono px-3 py-1.5 text-ink3">{stay_id}</td>
                  <td className="px-3 py-1.5 text-ink2 max-w-[380px] truncate">
                    {Object.entries(rest)
                      .filter(([, v]) => v !== null && v !== "" && v !== false)
                      .map(([k, v]) => `${k}=${v}`).join(", ")}
                  </td>
                  <td className="mono px-3 py-1.5 text-accent">{String(hash).slice(0, 8)}</td>
                  <td className="mono px-3 py-1.5 text-ink3">{String(prev).slice(0, 8)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!data?.events.length && (
        <p className="text-[12.5px] text-ink3 py-6 text-center">
          No events yet — let the shift run for a moment.
        </p>
      )}
    </>
  );
}
