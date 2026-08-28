"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "@/lib/api";
import type { Forecast } from "@/types/atria";

export default function OperationsPage() {
  const [nurses, setNurses] = useState(6);
  const [spaces, setSpaces] = useState(20);
  const [data, setData] = useState<Forecast | null>(null);

  useEffect(() => {
    let cancelled = false;
    // debounced: dragging a slider should not fire a request per pixel
    const t = setTimeout(async () => {
      try {
        const f = await api.forecast(nurses, spaces);
        if (!cancelled) setData(f);
      } catch { /* keep the last good forecast on screen */ }
    }, 220);
    return () => { cancelled = true; clearTimeout(t); };
  }, [nurses, spaces]);

  return (
    <>
      <h1 className="text-[20px] font-semibold mb-1">Next-hour outlook</h1>
      <p className="text-[15px] text-ink2 max-w-3xl leading-relaxed mb-5">
        This only affects the order of patients who are <b>equally urgent</b>. It
        can never move someone down a priority. A busy department does not make a
        sick patient less sick.
      </p>

      <div className="grid lg:grid-cols-[300px_1fr] gap-6">
        <section>
          <h2 className="text-[17px] font-semibold mb-3">Staffing</h2>
          <Slider label="Nurses available" value={nurses} min={1} max={12} onChange={setNurses} />
          <Slider label="Treatment spaces" value={spaces} min={4} max={40} onChange={setSpaces}
                  hint="How many rooms exist. What you can actually use is the smaller of this and what your nurses can safely cover." />
        </section>

        <section>
          {data && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
                <Stat label="Current flow" value={data.state === "Steady" ? "Steady" : data.state === "Busy" ? "Busy" : "Very busy"} />
                <Stat label="Open spaces" value={data.open_spaces}
                      hint="Rooms that are both empty and have a nurse for them." />
                <Stat label="Time in hand" value={`${Math.round(data.wait_buffer_minutes)} min`} />
                <Stat label="Expected arrivals" value={`${data.arrivals_next_hour}/hr`} />
              </div>

              <p className="rounded-xl border border-brand bg-brandsoft px-4 py-3.5 text-[16px] mb-3">
                {data.explanation}
              </p>
              {data.assumptions.map((a) => (
                <p key={a} className="rounded-xl border border-warn bg-warnsoft px-4 py-2.5 text-[15px] text-warn mb-2">
                  {a}
                </p>
              ))}

              <div className="h-[280px] mt-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.points}>
                    <CartesianGrid stroke="#e3e8e9" strokeDasharray="2 4" />
                    <XAxis dataKey="minute" stroke="#52605d" fontSize={13}
                           tickFormatter={(m) => `+${m}m`} />
                    <YAxis stroke="#52605d" fontSize={13} />
                    <Tooltip contentStyle={{ background: "#ffffff", border: "2px solid #d9dfe0",
                                             borderRadius: 8, fontSize: 14, color: "#16211f" }} />
                    <ReferenceLine y={data.staffed_spaces} stroke="#b3261e"
                                   strokeDasharray="6 6"
                                   label={{ value: "rooms we can staff", fill: "#b3261e", fontSize: 13 }} />
                    <Line type="monotone" dataKey="in_treatment" name="In treatment"
                          stroke="#0f766e" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="waiting" name="Waiting"
                          stroke="#a1580a" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="grid md:grid-cols-2 gap-4 mt-3">
                <p className="text-[15px] text-ink2 leading-relaxed">
                  <b className="text-ink">Why the green line stops rising.</b> You cannot
                  treat more people than you have staffed rooms for. A chart that let it
                  keep climbing would be telling you something untrue.
                </p>
                <p className="text-[15px] text-ink2 leading-relaxed">
                  <b className="text-ink">Why the orange line can go above it.</b> The
                  waiting room can keep filling past what you can treat. That is exactly
                  the thing worth seeing early.
                </p>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}

function Slider({ label, value, min, max, onChange, hint }: {
  label: string; value: number; min: number; max: number;
  onChange: (v: number) => void; hint?: string;
}) {
  return (
    <label className="block mb-4">
      <span className="text-[15px] font-medium">{label}</span>
      <span className="text-[16px] font-bold text-brand ml-2">{value}</span>
      <input type="range" min={min} max={max} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full mt-2 h-6 accent-[#0f766e]" />
      {hint && <span className="block text-[14px] text-ink2 mt-1 leading-relaxed">{hint}</span>}
    </label>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card border border-line px-4 py-3" title={hint}>
      <div className="text-[14px] text-ink2">{label}</div>
      <div className="text-[24px] font-bold mt-0.5 leading-none">{value}</div>
    </div>
  );
}
