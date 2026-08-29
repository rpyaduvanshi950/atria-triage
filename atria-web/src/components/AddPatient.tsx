"use client";

/**
 * Check a patient in by hand.
 *
 * The board is normally fed by a replay, which is fine for showing what it does
 * and useless for showing what it does with *your* patient. This puts a real
 * one in: details, then whatever vitals have actually been taken.
 *
 * Leaving a vital blank is meaningful and is meant to be easy. A blank field
 * means nobody has measured it, and that is exactly the case the safety layers
 * treat differently from a normal reading — check somebody in with two vitals
 * and watch ATRIA refuse to score them.
 */
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { VITAL_INFO } from "@/types/copy";

const TRANSPORT = ["walk-in", "ambulance", "other"];

export function AddPatient({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [complaint, setComplaint] = useState("");
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const [transport, setTransport] = useState("walk-in");
  const [vitals, setVitals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const numbers: Record<string, number | undefined> = {};
      for (const [k, v] of Object.entries(vitals)) {
        const n = Number(v);
        if (v.trim() !== "" && !Number.isNaN(n)) numbers[k] = n;
      }
      await api.addPatient({
        // Well clear of the replay's 900000 block, so a hand-added patient is
        // never wiped by a shift rollover or confused with a generated one.
        stayId: 950_000 + Math.floor(Math.random() * 49_000),
        age: age.trim() === "" ? undefined : Number(age),
        gender: gender || undefined,
        complaint: complaint.trim(),
        transport,
        vitals: numbers,
      });
      onAdded();
      onClose();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not check them in.");
      setBusy(false);
    }
  };

  const field = "w-full h-10 px-3 rounded-lg border border-line bg-page text-[15px]";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         role="dialog" aria-modal="true" aria-label="Check a patient in">
      <button className="fixed inset-0 bg-ink/30" aria-label="Cancel" onClick={onClose} />
      <form onSubmit={submit}
            className="relative w-full max-w-[520px] max-h-[90vh] overflow-y-auto
                       rounded-2xl bg-card border border-line shadow-xl p-5">
        <h2 className="text-[19px] font-bold">Check a patient in</h2>
        <p className="text-[14px] text-ink2 mt-1">
          Leave a reading blank if nobody has taken it. Blank is not zero and is
          never scored as normal.
        </p>

        <div className="grid grid-cols-2 gap-3 mt-4">
          <label className="col-span-2 text-[14px] font-semibold text-ink2">
            Why they came
            <input className={field} value={complaint} autoFocus required
                   placeholder="chest pain"
                   onChange={(e) => setComplaint(e.target.value)} />
          </label>
          <label className="text-[14px] font-semibold text-ink2">
            Age
            <input className={field} value={age} inputMode="numeric"
                   placeholder="54" onChange={(e) => setAge(e.target.value)} />
          </label>
          <label className="text-[14px] font-semibold text-ink2">
            Sex
            <select className={field} value={gender}
                    onChange={(e) => setGender(e.target.value)}>
              <option value="">Not recorded</option>
              <option value="F">Female</option>
              <option value="M">Male</option>
            </select>
          </label>
          <label className="col-span-2 text-[14px] font-semibold text-ink2">
            Arrived by
            <select className={field} value={transport}
                    onChange={(e) => setTransport(e.target.value)}>
              {TRANSPORT.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        </div>

        <h3 className="text-[15px] font-semibold mt-5 mb-2">Readings</h3>
        <div className="grid grid-cols-2 gap-3">
          {Object.entries(VITAL_INFO).map(([key, info]) => (
            <label key={key} className="text-[14px] font-semibold text-ink2">
              {info.full} <span className="font-normal text-ink3">{info.unit}</span>
              <input className={field} inputMode="decimal"
                     placeholder={info.normal}
                     value={vitals[key] ?? ""}
                     onChange={(e) =>
                       setVitals((v) => ({ ...v, [key]: e.target.value }))} />
            </label>
          ))}
        </div>

        {problem && (
          <p role="alert" className="text-[15px] text-danger font-semibold mt-3">
            {problem}
          </p>
        )}

        <div className="flex gap-3 mt-5">
          <button type="button" onClick={onClose}
                  className="flex-1 h-12 rounded-xl border border-line text-[16px]">
            Cancel
          </button>
          <button type="submit" disabled={busy || !complaint.trim()}
                  className="flex-1 h-12 rounded-xl bg-brand text-white text-[16px]
                             font-semibold disabled:opacity-40">
            {busy ? "Checking in…" : "Check in"}
          </button>
        </div>
      </form>
    </div>
  );
}
