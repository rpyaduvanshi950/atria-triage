"use client";

/**
 * Decide, compare, sign off.
 *
 * One decision on screen at a time. The recommendation is not fetched until the
 * nurse has committed, and the reveal call carries a token the server issued
 * when their answer was stored — so the order cannot be skipped from here.
 */
import { useEffect, useState } from "react";
import clsx from "clsx";
import { ApiError, api } from "@/lib/api";
import { ESI_FULL, ESI_SHORT, PRIORITY_NAME, REASON_CHOICES } from "@/types/copy";
import type { AssessmentView, Outcome, QueueRow } from "@/types/atria";

const OUTCOME: Record<Outcome, { tone: string; title: string; body: string }> = {
  match: {
    tone: "ok", title: "You and ATRIA agree",
    body: "Nothing to resolve. Confirm and move on.",
  },
  nurse_escalation: {
    tone: "warn", title: "You chose more urgent than ATRIA",
    body: "Your decision stands and you do not need to explain it. Nurses raising urgency are never questioned. The difference is recorded.",
  },
  nurse_downgrade: {
    tone: "warn", title: "You chose less urgent than ATRIA",
    body: "This is the direction that can cause harm, so please say why before you sign off.",
  },
  guardrail: {
    tone: "danger", title: "A safety rule fired on a recorded reading",
    body: "You can still choose less urgent, but please say why. The charge nurse is told.",
  },
  uncertain: {
    tone: "warn", title: "ATRIA would not give a score",
    body: "Important readings are missing and it will not guess. Take the vitals, or say why you are signing off without them.",
  },
};

export function BlindAssessment({ row, onChanged }: {
  row: QueueRow; onChanged: () => void;
}) {
  const [view, setView] = useState<AssessmentView | null>(null);
  const [token, setToken] = useState("");
  const [reason, setReason] = useState("reassessed_at_bedside");
  const [note, setNote] = useState("");
  /* "Something else" names no reason at all, so it has to be written out. The
     server enforces this too — the UI just says so before you press the button. */
  const noteRequired = reason === "other";
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => { setView(null); setToken(""); setProblem(null); setNote(""); },
            [row.stay_id]);

  const stage = view?.stage ?? "awaiting_nurse";
  const stepIndex = stage === "awaiting_nurse" ? 0 : stage === "compared" ? 1 : 2;

  const run = async (fn: () => Promise<AssessmentView>) => {
    if (busy) return;
    setBusy(true); setProblem(null);
    try { setView(await fn()); onChanged(); }
    catch (e) { setProblem(e instanceof ApiError ? e.message : "Something went wrong."); }
    finally { setBusy(false); }
  };

  const choose = (esi: number) =>
    run(async () => {
      const stored = await api.nurseAssess(row.stay_id, esi);
      const t = (stored as AssessmentView & { reveal_token?: string }).reveal_token ?? "";
      setToken(t);
      return api.reveal(row.stay_id, t);
    });

  return (
    <div>
      <ol className="flex gap-2 mb-5" aria-label="Steps">
        {["Your decision", "Compare", "Sign off"].map((label, i) => (
          <li key={label}
              className={clsx(
                "flex-1 rounded-xl px-3 py-2.5 text-[14px] border",
                i === stepIndex ? "border-brand bg-brandsoft text-brand font-semibold"
                                : i < stepIndex ? "border-line bg-card text-ink3"
                                                : "border-line2 bg-card text-ink3",
              )}>
            <span className="font-semibold">{i + 1}.</span> {label}
          </li>
        ))}
      </ol>

      {!view?.revealed ? (
        <>
          <div className="rounded-xl border border-brand bg-brandsoft p-4 mb-4">
            <p className="text-[16px] font-semibold text-brand">
              Choose nurse ESI
            </p>
            <p className="text-[15px] text-ink2 mt-1 leading-relaxed">
              Atria stays hidden until you choose. Seeing a number first makes it
              harder to trust your own judgement, so you decide, then we compare.
            </p>
          </div>

          <div className="grid gap-2">
            {[1, 2, 3, 4, 5].map((esi) => (
              <button key={esi} disabled={busy} onClick={() => choose(esi)}
                      className="min-h-[64px] text-left px-4 py-3 rounded-xl border border-line
                                 bg-card shadow-[0_1px_2px_rgba(33,52,58,.06)]
                                 hover:border-brand hover:bg-brandsoft
                                 disabled:opacity-50 transition-colors">
                <div className="flex items-baseline gap-3">
                  <span className="text-[22px] font-bold w-6">{esi}</span>
                  <span className="text-[16px] font-semibold">{ESI_SHORT[esi]}</span>
                  <span className="text-[14px] text-ink3 ml-auto">{PRIORITY_NAME[esi]}</span>
                </div>
                <div className="text-[14px] text-ink2 mt-0.5 ml-9">
                  {ESI_FULL[esi].split(" — ")[1]}
                </div>
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Card label="Nurse ESI" esi={view.nurse_esi} highlight />
            <Card label="Atria recommendation"
                  esi={view.atria_abstained ? null : view.atria_esi ?? null}
                  fallback="No score" />
          </div>

          {view.outcome && <Banner outcome={view.outcome} />}

          {stage === "signed" ? (
            <div className="rounded-lg border-2 border-ok bg-oksoft p-4 mt-4">
              <p className="text-[16px] font-semibold text-ok">
                Signed off at priority {view.final_esi}
              </p>
              <p className="text-[14px] text-ink2 mt-1">
                Saved with your name, the time, and the readings it was based on.
                Nothing more is needed for this patient — pick the next one from
                the queue.
              </p>
            </div>
          ) : (
            <>
              {view.needs_reason && (
                <label className="block mt-4">
                  <span className="text-[15px] font-semibold">Add a reason</span>
                  <select value={reason} onChange={(e) => setReason(e.target.value)}
                          className="w-full mt-1.5 rounded-xl border border-line bg-card
                                     px-3 py-3 text-[15px] min-h-[52px]">
                    {Object.entries(REASON_CHOICES).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                  {noteRequired && (
                    <span className="block mt-3">
                      <span className="text-[15px] font-semibold">
                        In your own words
                      </span>
                      <span className="block text-[14px] text-ink2 mb-1.5">
                        &quot;Something else&quot; on its own tells whoever reviews
                        this nothing. Say what you saw.
                      </span>
                      <textarea
                        value={note} onChange={(e) => setNote(e.target.value)}
                        rows={3} autoFocus
                        placeholder="e.g. Family says this is his normal breathing pattern."
                        className="w-full rounded-xl border border-line bg-card
                                   px-3 py-2.5 text-[15px] resize-y" />
                    </span>
                  )}
                </label>
              )}
              <button disabled={busy || (view.needs_reason && noteRequired && !note.trim())}
                      title={view.needs_reason && noteRequired && !note.trim()
                        ? "Write what you saw before signing off" : undefined}
                      onClick={() => run(() => api.finalize(
                        row.stay_id,
                        view.needs_reason ? reason : "",
                        view.needs_reason && noteRequired ? note : ""))}
                      className="w-full mt-4 min-h-[60px] rounded-xl bg-brand text-white
                                 text-[17px] font-semibold hover:opacity-90
                                 disabled:opacity-50 transition-opacity">
                {(view.nurse_esi ?? 5) <= 2 ? "Confirm and take them through" : "Confirm and next patient"}
              </button>
            </>
          )}
        </>
      )}

      <button disabled={busy} onClick={() => run(() => api.worsening(row.stay_id))}
              className="w-full mt-3 min-h-[52px] rounded-xl border border-line bg-card
                         text-[15px] hover:border-warn hover:text-warn
                         disabled:opacity-50 transition-colors">
        Report a change in this patient
      </button>
      <p className="text-[14px] text-ink3 mt-2 leading-relaxed">
        Press this if they have worsened, or new observations have come back.
        It reopens the decision and asks for your ESI again from scratch —
        ATRIA&apos;s earlier suggestion is thrown away so it cannot sway you the
        second time.
      </p>

      {problem && (
        <p role="status" className="text-[15px] text-warn mt-3 px-3 py-2 rounded-lg bg-warnsoft">
          {note}
        </p>
      )}
    </div>
  );
}

function Card({ label, esi, highlight, fallback }: {
  label: string; esi: number | null; highlight?: boolean; fallback?: string;
}) {
  return (
    <div className={clsx("rounded-xl border p-4 text-center",
                         highlight ? "border-brand bg-brandsoft" : "border-line bg-card")}>
      <div className="text-[14px] text-ink2">{label}</div>
      <div className="text-[36px] font-bold leading-tight">{esi ?? "—"}</div>
      <div className="text-[14px] text-ink2">{esi ? ESI_SHORT[esi] : fallback ?? ""}</div>
    </div>
  );
}

function Banner({ outcome }: { outcome: Outcome }) {
  const c = OUTCOME[outcome];
  const tones: Record<string, string> = {
    ok: "border-ok bg-oksoft text-ok",
    warn: "border-warn bg-warnsoft text-warn",
    danger: "border-danger bg-dangersoft text-danger",
  };
  return (
    <div className={clsx("rounded-xl border p-4", tones[c.tone])}>
      <p className="text-[16px] font-semibold">{c.title}</p>
      <p className="text-[15px] text-ink2 mt-1 leading-relaxed">{c.body}</p>
    </div>
  );
}
