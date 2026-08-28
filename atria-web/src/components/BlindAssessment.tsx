"use client";

/**
 * The blind cycle: assess, compare, sign off.
 *
 * The recommendation is never fetched before the nurse commits. The server
 * enforces that with a 409 and an absent field; this component simply has
 * nothing to render until `revealed` is true. A client cannot leak what it was
 * never sent, which is the whole reason the guard lives on the server.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { ApiError, api } from "@/lib/api";
import {
  ESI_LABEL, ESI_MEANING, REASON_CODES,
  type AssessmentView, type Outcome, type QueueRow,
} from "@/types/atria";

const STEPS = [
  ["1", "Assess", "Choose an ESI. ATRIA is hidden."],
  ["2", "Compare", "See ATRIA and resolve the difference."],
  ["3", "Sign off", "Confirm, with a reason where required."],
] as const;

const OUTCOME_COPY: Record<Outcome, { tone: string; title: string; body: string }> = {
  match: {
    tone: "accent", title: "You agree",
    body: "Confirm and move on.",
  },
  nurse_escalation: {
    tone: "signal", title: "You are more urgent than ATRIA",
    body: "Your view stands and no reason is required — a clinician escalating is never questioned. The difference is logged.",
  },
  nurse_downgrade: {
    tone: "signal", title: "You are less urgent than ATRIA",
    body: "This is the direction that can harm someone, so it needs a reason before sign-off.",
  },
  guardrail: {
    tone: "critical", title: "A hard rule fired on recorded values",
    body: "Going less urgent needs a reason and escalates to the charge nurse. No model output can suppress this.",
  },
  uncertain: {
    tone: "signal", title: "ATRIA abstained",
    body: "Essential data is missing and it will not guess. Complete the vitals, or give a reason to sign off regardless.",
  },
};

export function BlindAssessment({ row, onChanged }: {
  row: QueueRow;
  onChanged: () => void;
}) {
  const [view, setView] = useState<AssessmentView | null>(null);
  const [reason, setReason] = useState("reassessed_at_bedside");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // A new patient means a new cycle. Never carry a view across patients.
  useEffect(() => {
    setView(null);
    setNote(null);
  }, [row.stay_id]);

  const stage = view?.stage ?? "awaiting_nurse";
  const here = STEPS.findIndex(([n]) => n === (stage === "awaiting_nurse" ? "1" : stage === "compared" ? "2" : "3"));

  /** Every transition is guarded so a double-click cannot reach the engine twice. */
  const run = async (fn: () => Promise<AssessmentView>) => {
    if (busy) return;
    setBusy(true);
    setNote(null);
    try {
      setView(await fn());
      onChanged();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const choose = (esi: number) =>
    run(async () => {
      await api.nurseAssess(row.stay_id, esi);
      return api.reveal(row.stay_id);
    });

  return (
    <div>
      <div className="flex mb-3.5">
        {STEPS.map(([n, name, hint], i) => (
          <div key={n}
               className={clsx(
                 "flex-1 px-3 py-2 border border-r-0 last:border-r mono text-[11px]",
                 i === here ? "bg-surface border-accent text-ink2" : "border-rule text-ink3",
               )}>
            <b className={clsx("block text-[12.5px] mb-0.5 font-medium",
                               i === here ? "text-accent" : "text-ink3")}>
              {n} · {name}
            </b>
            {hint}
          </div>
        ))}
      </div>

      {!view?.revealed ? (
        <>
          <div className="bg-surface border border-dashed border-accent px-4 py-3.5 text-[12.5px] text-ink2 leading-relaxed">
            <b className="text-accent">ATRIA is locked.</b> Its recommendation is
            not on this page — not hidden, <i>absent</i> — until you choose. Show a
            clinician a number first and they converge on it; this is the cheapest
            defence against that.
          </div>
          <div className="grid gap-1.5 mt-3">
            {[1, 2, 3, 4, 5].map((esi) => (
              <button key={esi} disabled={busy} onClick={() => choose(esi)}
                      title={ESI_MEANING[esi]}
                      className="min-h-[56px] px-4 text-left bg-surface border border-rule
                                 hover:border-accent disabled:opacity-50 transition-colors">
                <span className="text-[17px] font-semibold mr-3">{esi}</span>
                <span className="text-[13px] text-ink2">{ESI_LABEL[esi]}</span>
                <span className="block text-[11px] text-ink3 mt-0.5">{ESI_MEANING[esi]}</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 mb-2.5">
            <Card label="You" value={view.nurse_esi} accent />
            <Card label="ATRIA"
                  value={view.atria_abstained ? null : view.atria_esi ?? null}
                  fallback="abstained" />
          </div>

          {view.outcome && <OutcomeBanner outcome={view.outcome} />}

          {stage === "signed" ? (
            <div className="border border-accent bg-surface px-4 py-3 text-[12.5px] text-ink2 mt-2">
              <b className="text-accent">Signed off at ESI {view.final_esi}.</b>{" "}
              Recorded with your identity, the model version and the input snapshot.
            </div>
          ) : (
            <>
              {view.needs_reason && (
                <label className="block mt-3">
                  <span className="mono text-[10px] tracking-wider text-ink3">WHY?</span>
                  <select value={reason} onChange={(e) => setReason(e.target.value)}
                          className="w-full mt-1 bg-surface2 border border-rule px-3 py-2 text-[13px]">
                    {Object.entries(REASON_CODES).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </label>
              )}
              <button disabled={busy}
                      onClick={() => run(() => api.finalize(row.stay_id, view.needs_reason ? reason : ""))}
                      className="w-full mt-3 py-3 bg-accent text-ground font-semibold
                                 disabled:opacity-50 hover:opacity-90 transition-opacity">
                {(view.nurse_esi ?? 5) <= 2 ? "Confirm & send inside" : "Confirm & advance"}
              </button>
            </>
          )}
        </>
      )}

      <button disabled={busy} onClick={() => run(() => api.worsening(row.stay_id))}
              className="w-full mt-2 py-2.5 border border-rule text-[12.5px] text-ink2
                         hover:border-signal hover:text-signal disabled:opacity-50 transition-colors">
        ⟲ Report change / worsening
      </button>
      <p className="text-[11px] text-ink3 mt-1.5 leading-relaxed">
        Clears the sign-off and starts a <b>fresh blind cycle</b>. The old
        recommendation is discarded — showing it would anchor the very decision
        this keeps independent.
      </p>

      {note && (
        <p className="mono text-[11px] text-signal mt-2" role="status">↩ {note}</p>
      )}
    </div>
  );
}

function Card({ label, value, accent, fallback }: {
  label: string; value: number | null; accent?: boolean; fallback?: string;
}) {
  return (
    <div className={clsx("bg-surface border px-3 py-3 text-center",
                         accent ? "border-accent" : "border-rule")}>
      <div className="mono text-[9px] tracking-widest text-ink3 uppercase">{label}</div>
      <div className="text-[27px] font-semibold leading-tight">{value ?? "—"}</div>
      <div className="text-[11px] text-ink3">
        {value ? ESI_LABEL[value] : fallback ?? ""}
      </div>
    </div>
  );
}

function OutcomeBanner({ outcome }: { outcome: Outcome }) {
  const c = OUTCOME_COPY[outcome];
  const tones: Record<string, string> = {
    accent: "border-accent text-accent",
    signal: "border-signal text-signal",
    critical: "border-critical text-critical",
  };
  return (
    <div className={clsx("border-l-2 bg-surface px-3.5 py-3", tones[c.tone])}>
      <div className="text-[13px] font-semibold">{c.title}</div>
      <div className="text-[12px] text-ink2 mt-1 leading-relaxed">{c.body}</div>
    </div>
  );
}
