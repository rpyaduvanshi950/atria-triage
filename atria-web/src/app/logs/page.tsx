"use client";

/**
 * The logs, in two views.
 *
 * "What ATRIA did" and "what we did about it" are different questions with
 * different audiences, and a single interleaved stream makes both harder to
 * follow. The underlying trail is one hash chain either way; this only chooses
 * which entries to show.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { Logs } from "@/types/atria";

const VIEW = {
  atria: {
    title: "ATRIA's own decisions",
    blurb: "What the machine did unprompted: what it scored, what it refused to "
         + "score, what a safety rule fired on, what a trajectory escalated.",
  },
  nurse: {
    title: "Priority changes by people",
    blurb: "Every time a human moved a priority: the blind choice, the sign-off, "
         + "an override, a reported change. Each one carries the name it was made under.",
  },
} as const;

const LABEL: Record<string, string> = {
  arrival: "arrived and scored",
  abstain: "refused to score",
  escalation: "escalated on trajectory",
  atria_reveal: "recommendation revealed",
  charge_nurse_escalation: "charge nurse alerted",
  shadow_recommendation: "shadow: would have said",
  nurse_assessment: "nurse chose, blind",
  sign_off: "signed off",
  override: "override",
  worsening_reported: "change reported",
  charge_nurse_acknowledgement: "charge nurse acknowledged",
  bays_changed: "treatment bays changed",
};

/** The fields worth putting in a row, in the order a reader wants them. */
const COLUMNS = ["seq", "at", "kind", "stay_id", "band", "frm", "to",
                 "nurse_esi", "atria_esi", "final_esi", "outcome",
                 "reason_code", "clinician", "hash"];

export default function LogsPage() {
  const [view, setView] = useState<"atria" | "nurse">("atria");
  const [data, setData] = useState<Logs | null>(null);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    const load = () =>
      api.logs(view).then((d) => { setData(d); setProblem(""); })
        .catch(() => setProblem("Could not load the log."));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [view]);

  const rows = (data?.events ?? []).slice().reverse();

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
          {data ? `${data.total} entries in the chain.` : ""} Each one seals the
          one before it, so an edit anywhere shows up here as ALTERED.
        </p>
      </div>

      <div role="tablist" aria-label="Which log"
           className="flex gap-1 mb-3 p-1 rounded-xl bg-sunk border border-line max-w-[560px]">
        {(Object.keys(VIEW) as (keyof typeof VIEW)[]).map((key) => (
          <button key={key} role="tab" aria-selected={view === key}
                  onClick={() => setView(key)}
                  className={clsx(
                    "flex-1 px-3 py-2 rounded-lg text-[15px] transition-colors",
                    view === key
                      ? "bg-card text-ink font-semibold shadow-[0_1px_2px_rgba(33,52,58,.08)]"
                      : "text-ink2 hover:text-ink",
                  )}>
            {VIEW[key].title}
          </button>
        ))}
      </div>

      <p className="text-[14px] text-ink2 mb-4 max-w-3xl leading-relaxed">
        {VIEW[view].blurb}
      </p>

      {problem && <p role="alert" className="text-danger text-[15px]">{problem}</p>}

      <div className="overflow-x-auto border border-line rounded-xl bg-card">
        <table className="w-full text-[13px] border-collapse">
          <thead>
            <tr className="bg-sunk">
              {COLUMNS.map((c) => (
                <th key={c} className="text-left px-2.5 py-2 font-semibold text-ink2
                                       whitespace-nowrap border-b border-line">
                  {c === "frm" ? "from" : c === "to" ? "to" : c.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.seq}-${i}`} className="border-b border-line last:border-0">
                {COLUMNS.map((c) => {
                  const v = r[c];
                  const text = v === undefined || v === null ? "" : String(v);
                  return (
                    <td key={c} className={clsx(
                          "px-2.5 py-1.5 align-top whitespace-nowrap",
                          c === "kind" && "font-semibold",
                          c === "hash" && "font-mono text-ink3",
                        )}>
                      {c === "kind" ? (LABEL[text] ?? text)
                       : c === "at" ? text.slice(11, 19)
                       : c === "hash" ? text.slice(0, 10)
                       : text}
                    </td>
                  );
                })}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length}
                    className="px-3 py-6 text-center text-ink3 text-[14px]">
                  Nothing recorded in this view yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
