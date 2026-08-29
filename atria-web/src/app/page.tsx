"use client";

import { useEffect, useRef, useState } from "react";
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
  const waiting = rows.filter((r) => r.state !== "IN TREATMENT");
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
  const selected = pinned ?? (ticket ? null : waiting[0] ?? null);
  const pinnedLeftQueue = pinned !== null && pinned.state === "IN TREATMENT";

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

      const i = waiting.findIndex((r) => r.ticket === selected?.ticket);
      if (e.key === "j" && i < waiting.length - 1) return setTicket(waiting[i + 1].ticket);
      if (e.key === "k" && i > 0) return setTicket(waiting[i - 1].ticket);

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
  }, [waiting, selected]);

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
        <Stat label="Checked out" value={snapshot.seen} hint="Treated and sent home or admitted." />
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
        <section aria-label="Attention queue">
          <h2 className="text-[17px] font-semibold mb-1">Attention order</h2>
          <p className="text-[14px] text-ink2 mb-3 leading-relaxed">
            Tap a patient to assess them. <b>j</b> and <b>k</b> move down and
            up, <b>1</b>–<b>5</b> record your priority, <b>Enter</b> confirms.
            <br />
            <span className="text-ink3">
              The order settles every 20 seconds so it does not move while you
              are reading it — but anyone who gets <b>worse</b> moves up
              straight away.
            </span>
          </p>
          <QueueList rows={rows} selectedTicket={selected?.ticket ?? null}
                     onSelect={(x) => setTicket(x.ticket)}
                     flipRef={flipRef} scroller={scroller} />
        </section>

        <section aria-label="Nurse assessment">
          <h2 className="text-[17px] font-semibold mb-3">Nurse assessment</h2>
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
