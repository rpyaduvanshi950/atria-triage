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
      <p className="text-[12.5px] text-ink2 max-w-3xl leading-relaxed mb-4">
        Demand against <b>staffed capacity</b> for the next hour. This informs
        ordering <i>within</i> an ESI band only — it can never move a patient across
        one. A busy department does not make a sick patient less sick.
      </p>

      <div className="grid lg:grid-cols-[300px_1fr] gap-6">
        <section>
          <h2 className="mono text-[10.5px] tracking-widest uppercase text-ink3 border-b border-rule pb-1.5 mb-3">
            Staffing
          </h2>
          <Slider label="Nurses on" value={nurses} min={1} max={12} onChange={setNurses} />
          <Slider label="Physical spaces" value={spaces} min={4} max={40} onChange={setSpaces}
                  hint="Rooms that physically exist. Capacity is the lesser of this and what your nurses can safely cover." />
        </section>

        <section>
          {data && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-rule border border-rule mb-4">
                <Stat label="Flow" value={data.state} />
                <Stat label="Open spaces" value={data.open_spaces}
                      hint="Physically available AND safely staffed. Not licensed beds." />
                <Stat label="Wait buffer" value={`${Math.round(data.wait_buffer_minutes)}m`} />
                <Stat label="Arrivals/hr" value={data.arrivals_next_hour} />
              </div>

              <p className="border-l-2 border-accent bg-surface px-4 py-3 text-[13px] text-ink2 mb-3">
                {data.explanation}
              </p>
              {data.assumptions.map((a) => (
                <p key={a} className="border-l-2 border-signal bg-surface px-4 py-2 text-[12px] text-signal mb-2">
                  {a}
                </p>
              ))}

              <div className="h-[280px] mt-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.points}>
                    <CartesianGrid stroke="#26352f" strokeDasharray="2 4" />
                    <XAxis dataKey="minute" stroke="#72837f" fontSize={11}
                           tickFormatter={(m) => `+${m}m`} />
                    <YAxis stroke="#72837f" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#15201e", border: "1px solid #26352f",
                                             fontSize: 12, color: "#e7edea" }} />
                    <ReferenceLine y={data.staffed_spaces} stroke="#e5766a"
                                   strokeDasharray="5 5"
                                   label={{ value: "staffed capacity", fill: "#e5766a", fontSize: 11 }} />
                    <Line type="monotone" dataKey="in_treatment" name="In a bay"
                          stroke="#45c4b2" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="waiting" name="Waiting"
                          stroke="#e8903f" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="grid md:grid-cols-2 gap-4 mt-3">
                <p className="text-[11.5px] text-ink3 leading-relaxed">
                  <b className="text-ink2">Why the teal line flattens.</b> Treatment is
                  capped at staffed spaces — you cannot treat more people than you have
                  staffed places for, and a chart that let it climb would be lying.
                </p>
                <p className="text-[11.5px] text-ink3 leading-relaxed">
                  <b className="text-ink2">Why the orange line can climb past it.</b> A
                  queue <i>can</i> grow beyond capacity. Hiding that would hide the single
                  condition most worth seeing.
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
      <span className="text-[12.5px] text-ink2">{label}</span>
      <span className="mono text-[13px] text-accent ml-2">{value}</span>
      <input type="range" min={min} max={max} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full mt-1.5 accent-[#45c4b2]" />
      {hint && <span className="block text-[11px] text-ink3 mt-1 leading-relaxed">{hint}</span>}
    </label>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="bg-ground px-3 py-2.5" title={hint}>
      <div className="mono text-[9.5px] tracking-widest uppercase text-ink3">{label}</div>
      <div className="text-[19px] font-semibold mt-0.5">{value}</div>
    </div>
  );
}
