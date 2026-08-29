"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useQueue } from "@/lib/queue-context";
import { useFlip } from "@/lib/useFlip";
import { QueueList } from "@/components/QueueList";
import { Announcer } from "@/components/Announcer";
import { BlindAssessment } from "@/components/BlindAssessment";
import { PatientRecord } from "@/components/PatientRecord";
import { LANE_NAME } from "@/types/copy";
import type { QueueRow } from "@/types/atria";

export default function AssessmentPage() {
  const { snapshot, status, refresh } = useQueue();
  const [ticket, setTicket] = useState<string | null>(null);

  const rows = snapshot?.rows ?? [];
  /*
   * The board splits on "is triage finished for this person", not on "are they
   * in a bay".
   *
   * A patient the nurse has signed off is done with the attention queue — there
   * is nothing left for a triage nurse to do — but they are not being treated
   * either. Leaving them in a list headed "Attention order" hides the group
   * that most needs watching: triaged, cleared, and still sitting there.
   */
  const waiting = rows.filter(
    (r) => r.state !== "IN TREATMENT" && !r.signed_off);
  const inTreatment = rows.filter(
    (r) => r.state === "IN TREATMENT" || r.signed_off);
  const awaitingBay = inTreatment.filter((r) => r.state !== "IN TREATMENT");
  /*
   * The selection is pinned once a nurse picks someone.
   *
   * It used to fall back to waiting[0] whenever the chosen patient was not in
   * the waiting list — and the queue reorders every couple of seconds, so the
   * panel jumped to a different patient mid-decision. Look for them across the
   * whole board, not just the waiting part, so a patient who moves into a bay
   * stays on screen instead of being silently swapped for someone else.
   */
  const pinned = ticket ? rows.find((r) => r.ticket === ticket) ?? null : null;
  /*
   * Only a move into a bay drags the tab across, not a sign-off. Being taken
   * through happens TO the patient while the nurse is looking elsewhere, so the
   * view should follow. A sign-off is something the nurse just did deliberately
   * and expects to move on from — yanking them to the other tab would take away
   * the list they need next.
   */
  const pinnedLeftQueue = pinned !== null && pinned.state === "IN TREATMENT";

  /*
   * Follow the patient. If the person you were looking at is taken through to a
   * bay, the tab moves with them — otherwise they vanish from the list you are
   * on and it looks as though the board lost them, which is the confusion this
   * whole change is meant to remove.
   */
  useEffect(() => {
    if (pinnedLeftQueue) setView("treatment");
  }, [pinnedLeftQueue]);

  /*
   * Which list occupies the left column.
   *
   * Patients in a bay belong on the board — a nurse needs to know who is where
   * — but not mixed into a list headed "Attention order", where they read as
   * still needing you. Two views in one place, and the tab says how many are
   * in each, so nothing is hidden by being on the other tab.
   */
  const [view, setView] = useState<"waiting" | "treatment">("waiting");
  const listed = view === "waiting" ? waiting : inTreatment;

  /*
   * Never show an empty right-hand side while there is somebody on the list.
   *
   * The panels used to go blank whenever the pinned patient left the board, and
   * "no patient" is a worse answer than "the one at the top" — the top of the
   * attention queue is exactly who a nurse should be looking at next anyway.
   * A deliberate selection still wins; this only fills the gap.
   */
  const selected = pinned ?? listed[0] ?? null;

  const scroller = useRef<HTMLDivElement>(null);
  const flipRef = useFlip(rows.map((r) => r.ticket), scroller);

  /*
   * Keyboard-first: a nurse under load should not need a mouse.
   *
   *   j / k     next / previous patient
   *   1 - 5     record your ESI for the selected patient
   *   Enter     confirm the step the assessment panel is on
   *
   * The digits are dispatched as an event rather than lifted into state, so the
   * assessment panel stays the only thing that knows how to record an ESI. Two
   * code paths posting the nurse's answer is exactly how the blind cycle would
   * come apart.
   */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement &&
          ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const i = listed.findIndex((r) => r.ticket === selected?.ticket);
      if (e.key === "j" && i < listed.length - 1) return setTicket(listed[i + 1].ticket);
      if (e.key === "k" && i > 0) return setTicket(listed[i - 1].ticket);

      if (/^[1-5]$/.test(e.key)) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("atria:esi", { detail: Number(e.key) }));
      }
      if (e.key === "Enter") {
        window.dispatchEvent(new CustomEvent("atria:confirm"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [listed, selected]);

  if (!snapshot) {
    return (
      <p className="text-[16px] text-ink2 py-20 text-center">
        {status === "live" ? "Waiting for the first patient…" : "Connecting…"}
      </p>
    );
  }

  return (
    <>
      <Announcer />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
        <Stat label="Waiting" value={snapshot.waiting} hint="Patients in the queue now." />
        <Stat label="In treatment" value={`${snapshot.in_treatment} of ${snapshot.slots}`}
              hint="Rooms in use. When one frees up, the most urgent waiting patient goes next." />
        <Stat label="Waiting for a bay" value={awaitingBay.length}
              hint="Triage is finished and nobody has taken them through yet. Shown with a red border." />
        <Stat label="Moved up" value={snapshot.escalated}
              hint="Patients ATRIA moved to a higher priority. It can never move anyone down." />
        <Stat label="Needs you" value={snapshot.abstained}
              hint="ATRIA would not give a score — too little information to be safe." />
      </div>

      {snapshot.degraded && (
        <div className="rounded-xl border border-danger bg-dangersoft px-4 py-3.5 mb-5">
          <b className="text-danger text-[16px]">Suggestions are off.</b>{" "}
          <span className="text-ink2 text-[15px]">
            The safety rules are still running and will still flag a critical
            patient. You will not see a suggested priority until they are back on.
          </span>
        </div>
      )}

      <div className="flex gap-6 text-[15px] text-ink2 mb-4 flex-wrap items-center">
        {Object.entries(snapshot.lanes).map(([lane, n]) => (
          <span key={lane}>{LANE_NAME[lane] ?? lane} <b className="text-ink">{n}</b></span>
        ))}
        <span className="ml-auto text-[14px] text-ink3">
          Resus patients never wait behind anyone else
        </span>
      </div>

      <div className="grid lg:grid-cols-[1.15fr_1.15fr_1fr] gap-5">
        <section aria-label="Patient lists">
          <div role="tablist" aria-label="Which patients to show"
               className="flex gap-1 mb-2 p-1 rounded-xl bg-sunk border border-line">
            {([["waiting", "Attention order", waiting.length],
               ["treatment", "Treatment bay", inTreatment.length]] as const)
              .map(([key, text, count]) => (
                <button key={key} role="tab" aria-selected={view === key}
                        onClick={() => setView(key)}
                        className={clsx(
                          "flex-1 px-3 py-2 rounded-lg text-[15px] transition-colors",
                          view === key
                            ? "bg-card text-ink font-semibold shadow-[0_1px_2px_rgba(33,52,58,.08)]"
                            : "text-ink2 hover:text-ink",
                        )}>
                  {text}{" "}
                  <span className={view === key ? "text-brand" : "text-ink3"}>{count}</span>
                </button>
              ))}
          </div>
          <p className="text-[14px] text-ink2 mb-3 leading-relaxed">
            {view === "waiting" ? (
              <>
                Tap a patient to assess them. <b>j</b> and <b>k</b> move down
                and up, <b>1</b>–<b>5</b> record your priority, <b>Enter</b>{" "}
                confirms.
                <br />
                <span className="text-ink3">
                  The order settles every 20 seconds so it does not move while
                  you are reading it — but anyone who gets <b>worse</b> moves up
                  straight away.
                </span>
              </>
            ) : (
              <>
                Triage is finished for these patients.{" "}
                <b className="text-ok">Green</b> means they are in a bay being
                treated. <b className="text-danger">Red</b> means you have signed
                them off and nobody has taken them through yet.
                <br />
                <span className="text-ink3">
                  Tap one to read their record or report a change.
                </span>
              </>
            )}
          </p>
          <QueueList rows={listed} selectedTicket={selected?.ticket ?? null}
                     onSelect={(x) => setTicket(x.ticket)}
                     flipRef={flipRef} scroller={scroller}
                     label={view === "waiting" ? "Attention order" : "Treatment bay"}
                     emptyMessage={view === "waiting"
                       ? "Everybody waiting has been assessed."
                       : "Nobody has been signed off yet."} />
        </section>

        <section aria-label="Nurse assessment">
          <h2 className="text-[17px] font-semibold mb-3">
            Nurse assessment
            {selected && !pinned && (
              <span className="font-normal text-[14px] text-ink3">
                {" "}— top of the list
              </span>
            )}
          </h2>
          {selected
            ? <BlindAssessment key={selected.stay_id} row={selected} onChanged={refresh} />
            : <p className="text-[13px] text-ink3">Nobody waiting.</p>}
        </section>

        <section aria-label="Patient record">
          <h2 className="text-[17px] font-semibold mb-3">Patient record</h2>
          {selected && <PatientRecord row={selected} />}
        </section>
      </div>
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint: string }) {
  return (
    <div className="card border border-line px-4 py-3" title={hint}>
      <div className="text-[14px] text-ink2">{label}</div>
      <div className="text-[26px] font-bold mt-0.5 leading-none">{value}</div>
    </div>
  );
}
