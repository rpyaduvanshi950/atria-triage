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
import { Vitals } from "@/components/Vitals";
import type { AssessmentView, Outcome, QueueRow } from "@/types/atria";

const OUTCOME: Record<Outcome, { tone: string; title: string; body: string }> = {
  match: {
    tone: "ok", title: "You and ATRIA agree",
    body: "Nothing to resolve.",
  },
  nurse_escalation: {
    tone: "warn", title: "You chose more urgent",
    body: "Your decision stands. Raising urgency is never questioned. The difference is recorded.",
  },
  nurse_downgrade: {
    tone: "warn", title: "You chose less urgent",
    body: "This is the direction that can cause harm. Please say why.",
  },
  guardrail: {
    tone: "danger", title: "A safety rule fired",
    body: "You can still choose less urgent, but say why. The charge nurse is told.",
  },
  uncertain: {
    tone: "warn", title: "ATRIA would not score",
    body: "Readings are missing and it will not guess. Take them, or say why not.",
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
  /* Set when the server says this patient cannot be assessed at all — they have
     left the board, or a previous cycle is still open. Retrying cannot fix
     either, so the buttons stop rather than firing the same refused call again
     every time a key repeats. */
  const [blocked, setBlocked] = useState(false);
  /* The ESI the nurse just pressed, shown immediately while the request is in
     flight. Optimistic about the *acknowledgement*, never about the outcome:
     the comparison and the sign-off state come from the server, because those
     are the parts a client guessing wrong would corrupt. */
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    setView(null); setToken(""); setProblem(null); setNote("");
    setPending(null); setBlocked(false);

    /*
     * Ask the server where this patient actually is.
     *
     * The panel used to assume every patient was at step one. Anyone part-way
     * through was shown the priority buttons anyway, and pressing one was
     * refused with a 409 they could do nothing about. The stage belongs to the
     * server, so it is read from the server.
     */
    if (row.assessment_stage === "awaiting_nurse") return;
    let cancelled = false;
    api.assessment(row.stay_id)
      .then((v) => { if (!cancelled) setView(v); })
      .catch(() => { /* fall back to step one; the buttons will say if not */ });
    return () => { cancelled = true; };
  }, [row.stay_id, row.assessment_stage]);

  const stage = view?.stage ?? "awaiting_nurse";
  const stepIndex = stage === "awaiting_nurse" ? 0 : stage === "compared" ? 1 : 2;

  /*
   * The keyboard shortcuts the board dispatches. They land here because this is
   * the component that owns the workflow — the page knows which keys were
   * pressed and nothing else, so there is still exactly one path that records
   * an ESI.
   *
   * A digit is ignored once the recommendation is on screen. Re-entering an
   * answer after seeing ATRIA is precisely the anchoring the blind cycle exists
   * to prevent, and the server would refuse it anyway.
   */
  useEffect(() => {
    const onEsi = (e: Event) => {
      const esi = (e as CustomEvent<number>).detail;
      if (busy || view?.revealed || stage !== "awaiting_nurse") return;
      // A key held down repeats. Without this the same ESI is posted five or
      // six times before the first response lands, and the server refuses each
      // one — which is what filled the log with 409s.
      if (blocked) return;
      choose(esi);
    };
    const onConfirm = () => {
      if (busy || stage !== "compared") return;
      if (view?.needs_reason && reason === "other" && !note.trim()) return;
      finalize();
    };
    window.addEventListener("atria:esi", onEsi);
    window.addEventListener("atria:confirm", onConfirm);
    return () => {
      window.removeEventListener("atria:esi", onEsi);
      window.removeEventListener("atria:confirm", onConfirm);
    };
  });

  const run = async (fn: () => Promise<AssessmentView>) => {
    if (busy) return;
    setBusy(true); setProblem(null);
    try {
      setView(await fn());
      onChanged();
    } catch (e) {
      if (e instanceof ApiError) {
        setProblem(e.message);
        // 409 means the server will refuse this again for the same reason.
        // Anything else may be transient and is worth another press.
        if (e.status === 409) setBlocked(true);
      } else {
        setProblem("Something went wrong.");
      }
      onChanged();   // pull a fresh board; the patient may simply have moved
    } finally { setBusy(false); }
  };

  /* One implementation, two ways in — the button and Enter. A second copy of
     this call is a second place for the reason-code rules to drift. */
  const finalize = () =>
    run(() => api.finalize(
      row.stay_id,
      view?.needs_reason ? reason : "",
      view?.needs_reason && reason === "other" ? note : ""));

  const choose = (esi: number) => {
    setPending(esi);
    return run(async () => {
      try {
        const stored = await api.nurseAssess(row.stay_id, esi);
        const t = (stored as AssessmentView & { reveal_token?: string }).reveal_token ?? "";
        setToken(t);
        return await api.reveal(row.stay_id, t);
      } finally {
        setPending(null);
      }
    });
  };

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
              Your priority for this patient
            </p>
            <p className="text-[15px] text-ink2 mt-1 leading-relaxed">
              ATRIA stays hidden until you choose. You decide first, then we
              compare.
            </p>
          </div>

          {blocked && (
            <div role="alert"
                 className="rounded-xl border border-warn bg-warnsoft px-4 py-3 mb-3">
              <b className="text-warn text-[15px]">
                This patient cannot be assessed right now.
              </b>
              <p className="text-[14px] text-ink2 mt-1 leading-relaxed">
                {problem ?? "The board has moved on."} Pick another patient from
                the queue. Trying again here will not help.
              </p>
            </div>
          )}

          {/* The readings, where the decision is made. Asking someone to choose
              a priority while the numbers live in another column is how a
              priority gets chosen from a chief complaint alone. */}
          <Vitals row={row} compact />

          <div className="grid gap-2 mt-3">
            {[1, 2, 3, 4, 5].map((esi) => (
              <button key={esi} disabled={busy || blocked} onClick={() => choose(esi)}
                      aria-keyshortcuts={String(esi)}
                      className={clsx(
                        "min-h-[64px] text-left px-4 py-3 rounded-xl border",
                        "bg-card shadow-[0_1px_2px_rgba(33,52,58,.06)]",
                        "hover:border-brand hover:bg-brandsoft",
                        "disabled:opacity-50 transition-colors",
                        // The press is acknowledged the instant it happens. The
                        // answer it produces still comes from the server.
                        pending === esi
                          ? "border-brand bg-brandsoft ring-2 ring-brand"
                          : "border-line",
                      )}>
                <div className="flex items-baseline gap-3">
                  <span className="text-[22px] font-bold w-6">{esi}</span>
                  <span className="text-[16px] font-semibold">{ESI_SHORT[esi]}</span>
                  <span className="text-[14px] text-ink3 ml-auto">{PRIORITY_NAME[esi]}</span>
                </div>
                <div className="text-[14px] text-ink2 mt-0.5 ml-9">
                  {ESI_FULL[esi].split(". ").slice(1).join(". ")}
                </div>
              </button>
            ))}
          </div>
        </>
      ) : (
        /*
         * Compare and sign off, in the column. It was briefly a modal over a
         * blurred board; that took the queue away at the moment a nurse most
         * wants to glance at it, so it is inline again.
         */
        <>
          {/* One card, and it is the nurse's. ATRIA's number belongs with the
              reasons for it, not beside yours as an equal claim. */}
          <Card label="Your priority" esi={view.nurse_esi} highlight />

          <AtriaSaid view={view} row={row} />

          {view.outcome && <Banner outcome={view.outcome} />}

          {stage === "signed" ? (
            <div className="rounded-lg border-2 border-ok bg-oksoft p-4 mt-4">
              <p className="text-[16px] font-semibold text-ok">
                Signed off at priority {view.final_esi}
              </p>
              <p className="text-[14px] text-ink2 mt-1">
                Saved with your name, the time and the readings. Pick the next
                patient.
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
                      onClick={finalize}
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
        It reopens the decision and asks for your priority again from scratch.
        ATRIA&apos;s earlier suggestion is thrown away.
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
      <div className="text-[36px] font-bold leading-tight">{esi ?? "?"}</div>
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


/**
 * What ATRIA said, and why it said it.
 *
 * A bare number invites a nurse either to defer to it or to dismiss it, and
 * neither is a judgement. The reasons come from the server with the
 * recommendation; nothing here re-derives them, because a second opinion
 * computed in a browser would be a second source of truth.
 */
function AtriaSaid({ view, row }: { view: AssessmentView; row: QueueRow }) {
  const abstained = view.atria_abstained || row.abstained;
  const why = abstained
    ? [row.abstain_reason].filter(Boolean)
    : [row.red_flag, ...row.reasons].filter(Boolean) as string[];

  return (
    <div className="rounded-xl border border-line bg-sunk p-3.5 mt-3">
      <div className="flex items-baseline gap-2">
        <span className="text-[14px] text-ink2">ATRIA said</span>
        <span className={clsx("text-[20px] font-bold",
                              abstained ? "text-danger" : "text-ink")}>
          {abstained ? "no score" : view.atria_esi}
        </span>
        {!abstained && (
          <span className="text-[13px] text-ink3 ml-auto">
            confidence {row.confidence.toLowerCase()}
          </span>
        )}
      </div>

      {why.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1">
          {why.slice(0, 3).map((r) => (
            <li key={r} className="text-[14px] text-ink2 flex gap-2">
              <span className="text-ink3">&bull;</span>{r}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[14px] text-ink2 mt-1">
          Nothing unusual in the readings it could see.
        </p>
      )}

      {row.missing.length > 0 && (
        <p className="text-[13px] text-warn mt-2">
          Judged without: {row.missing.join(", ")}
        </p>
      )}
    </div>
  );
}
