"use client";

import { useEffect, useState } from "react";
import { useQueue } from "@/lib/queue-context";
import { useFlip } from "@/lib/useFlip";
import { QueueRowCard } from "@/components/QueueRow";
import { BlindAssessment } from "@/components/BlindAssessment";
import { PatientRecord } from "@/components/PatientRecord";
import type { QueueRow } from "@/types/atria";

export default function AssessmentPage() {
  const { snapshot, status, refresh } = useQueue();
  const [ticket, setTicket] = useState<string | null>(null);

  const rows = snapshot?.rows ?? [];
  const waiting = rows.filter((r) => r.state !== "IN TREATMENT");
  const selected = waiting.find((r) => r.ticket === ticket) ?? waiting[0] ?? null;

  const flipRef = useFlip(rows.map((r) => r.ticket));

  // Keyboard-first: a nurse under load should not need a mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement &&
          ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
      const i = waiting.findIndex((r) => r.ticket === selected?.ticket);
      if (e.key === "j" && i < waiting.length - 1) setTicket(waiting[i + 1].ticket);
      if (e.key === "k" && i > 0) setTicket(waiting[i - 1].ticket);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [waiting, selected]);

  if (!snapshot) {
    return (
      <p className="mono text-[13px] text-ink3 py-16 text-center">
        {status === "live" ? "waiting for the first arrival…" : "connecting to the engine…"}
      </p>
    );
  }

  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-6 gap-px bg-rule border border-rule mb-4">
        <Stat label="Waiting" value={snapshot.waiting} hint="Patients in the queue right now." />
        <Stat label="In a bay" value={`${snapshot.in_treatment}/${snapshot.slots}`}
              hint="Treatment spaces occupied. When one frees, the highest-priority waiting patient is taken through." />
        <Stat label="Seen" value={snapshot.seen} hint="Treated and discharged this shift." />
        <Stat label="Escalated" value={snapshot.escalated}
              hint="Times a machine raised someone's priority. It can never lower one." />
        <Stat label="Abstained" value={snapshot.abstained}
              hint="Times ATRIA refused to score — too little data, or the picture fits more than one pathway." />
        <Stat label="p95" value={snapshot.p95_ms ? `${snapshot.p95_ms}ms` : "–"}
              hint="Scoring latency, 95th percentile. Budget is 400ms." />
      </div>

      {snapshot.degraded && (
        <div className="border-l-2 border-critical bg-surface px-4 py-3 mb-4 text-[13px]">
          <b className="text-critical">Model service down.</b>{" "}
          <span className="text-ink2">
            Layer 0 is still gating on hard rules, offline. Every score drops to LOW
            confidence, because the thing that produced confidence is gone.
          </span>
        </div>
      )}

      <div className="flex gap-5 mono text-[11px] text-ink3 border-y border-rule py-2 mb-3 flex-wrap">
        {Object.entries(snapshot.lanes).map(([lane, n]) => (
          <span key={lane}>{lane} <b className="text-ink2">{n}</b></span>
        ))}
        <span className="ml-auto">RESUS never queues behind anyone</span>
      </div>

      <div className="grid lg:grid-cols-[1.15fr_1.15fr_1fr] gap-5">
        <section aria-label="Attention queue">
          <h2 className="mono text-[10.5px] tracking-widest uppercase text-ink3 border-b border-rule pb-1.5 mb-2">
            Attention queue
          </h2>
          <p className="text-[11.5px] text-ink3 mb-2.5 leading-relaxed">
            Rank is <b>not</b> ESI. ESI is the acuity the nurse signs; rank is a live
            sequence that changes as people wait and worsen. <span className="mono">j</span>/<span className="mono">k</span> to move.
          </p>
          {rows.slice(0, 14).map((r) => (
            <QueueRowCard key={r.ticket} row={r} selected={r.ticket === selected?.ticket}
                          onSelect={(x) => setTicket(x.ticket)} innerRef={flipRef(r.ticket)} />
          ))}
        </section>

        <section aria-label="Nurse assessment">
          <h2 className="mono text-[10.5px] tracking-widest uppercase text-ink3 border-b border-rule pb-1.5 mb-3">
            Nurse assessment
          </h2>
          {selected
            ? <BlindAssessment key={selected.stay_id} row={selected} onChanged={refresh} />
            : <p className="text-[13px] text-ink3">Nobody waiting.</p>}
        </section>

        <section aria-label="Patient record">
          <h2 className="mono text-[10.5px] tracking-widest uppercase text-ink3 border-b border-rule pb-1.5 mb-3">
            Patient record
          </h2>
          {selected && <PatientRecord row={selected} />}
        </section>
      </div>
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint: string }) {
  return (
    <div className="bg-ground px-3 py-2.5" title={hint}>
      <div className="mono text-[9.5px] tracking-widest uppercase text-ink3">{label}</div>
      <div className="text-[20px] font-semibold mt-0.5">{value}</div>
    </div>
  );
}
