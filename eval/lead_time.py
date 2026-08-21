"""
Does Layer 2's trajectory signal actually discriminate — on real patients?

Runs the re-ranker over the MIMIC demo's 159 real repeated-vitals stays, reading
by reading, exactly as the live engine does. Queue aging is suppressed here on
purpose: real ED stays run for hours, so the aging term fires on essentially
everyone and would drown the physiological signal we are trying to measure.
Aging earns its place in the live system; it has no place in this measurement.

Outcome is the recorded disposition. Admission is a coarse acuity proxy, not
ICU-or-death — say so on the slide.
"""
from __future__ import annotations

import pandas as pd

from data.loaders.mimic_demo import load
from layer2.trajectory import assess

SICK = {"ADMITTED", "TRANSFER"}


def run(min_readings: int = 3) -> dict:
    ds = load()
    stays = ds.edstays.set_index("stay_id")
    tri = ds.triage.set_index("stay_id")

    rows = []
    for sid, h in ds.vitalsign.groupby("stay_id"):
        h = h.sort_values("charttime").reset_index(drop=True)
        if len(h) < min_readings:
            continue

        acuity = pd.to_numeric(pd.Series([tri.loc[sid, "acuity"]]), errors="coerce").iloc[0]
        band = int(acuity) if pd.notna(acuity) else 3

        escalated_at = None
        reasons: tuple[str, ...] = ()
        for i in range(2, len(h) + 1):
            now = h.loc[i - 1, "charttime"]
            # arrived=now suppresses queue aging, isolating physiology
            t = assess(h.iloc[:i], now=now, current_band=band, arrived=now)
            if t.escalates:
                escalated_at, reasons = now, t.reasons
                break

        disposition = str(stays.loc[sid, "disposition"])
        rows.append({
            "stay_id": sid, "triage_esi": band, "disposition": disposition,
            "sick": disposition in SICK, "readings": len(h),
            "escalated": escalated_at is not None,
            "lead_minutes": ((h["charttime"].max() - escalated_at).total_seconds() / 60
                             if escalated_at is not None else None),
            "reasons": "; ".join(reasons),
        })

    df = pd.DataFrame(rows)
    sick, well = df[df["sick"]], df[~df["sick"]]
    lead = df.loc[df["escalated"] & df["sick"], "lead_minutes"].dropna()

    return {
        "stays_examined": len(df),
        "sensitivity_admitted": round(float(sick["escalated"].mean()), 4) if len(sick) else None,
        "false_positive_discharged": round(float(well["escalated"].mean()), 4) if len(well) else None,
        "median_lead_minutes": round(float(lead.median()), 1) if len(lead) else None,
        "n_admitted": int(len(sick)), "n_discharged": int(len(well)),
        "detail": df,
    }


if __name__ == "__main__":
    r = run()
    print(f"stays examined                 {r['stays_examined']}")
    print(f"  admitted / transferred       {r['n_admitted']}")
    print(f"  discharged home              {r['n_discharged']}")
    print()
    print(f"Layer 2 escalation rate")
    print(f"  among admitted               {r['sensitivity_admitted']:.1%}")
    print(f"  among discharged home        {r['false_positive_discharged']:.1%}")
    print(f"  median lead time             {r['median_lead_minutes']:.0f} min before last reading")
    print()
    print("first escalation reasons, most common:")
    d = r["detail"]
    print(d.loc[d["escalated"], "reasons"].str.split(" ").str[0].value_counts().head(5).to_string())
