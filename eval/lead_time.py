"""
Does Layer 2's trajectory signal actually discriminate — on real patients?

Runs the re-ranker over the MIMIC demo's 159 real repeated-vitals stays, reading
by reading, exactly as the live engine does. Queue aging is suppressed here on
purpose: real ED stays run for hours, so the aging term fires on essentially
everyone and would drown the physiological signal we are trying to measure.
Aging earns its place in the live system; it has no place in this measurement.

Two endpoints, because one of them was never good enough.

**Admitted or transferred.** The headline number, and a coarse acuity proxy —
plenty of admissions are precautionary and plenty of discharges were genuinely
unwell on arrival. No open ED dataset carries ICU timestamps, so the usual
"ICU transfer or death within 24 hours" is not available here.

**A critical diagnosis on the encounter.** Sharper, and the closest this data
gets to the endpoint that matters. It is a secondary, exploratory measure: it
rests on far fewer patients, and it is a diagnosis recorded at any point in the
encounter rather than an event with a timestamp, so it cannot distinguish "was
already critical at triage" from "became critical later". Both are reported
with intervals, and the interval on the second one is wide.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.loaders.mimic_demo import load
from eval.uncertainty import bootstrap, gap_with_ci, rate_with_ci
from layer2.trajectory import assess

SICK = {"ADMITTED", "TRANSFER"}

#: Diagnoses that make an encounter critical regardless of where the patient
#: went afterwards. Deliberately specific: conditions with a recognised
#: time-critical pathway, matched on the ICD title because the demo mixes ICD-9
#: and ICD-10 coding.
#:
#: "Altered mental status" and unspecified GI haemorrhage are excluded despite
#: being the most common matches for a looser pattern. Both span the range from
#: trivial to peri-arrest, and an endpoint that admits them measures how a
#: clerk coded the visit rather than how sick the patient was.
CRITICAL_DIAGNOSIS = (
    r"SEPSIS|SEPTIC|SEPTICEMIA"
    r"|MYOCARDIAL INFARCT|STEMI"
    r"|CARDIAC ARREST"
    r"|RESPIRATORY FAILURE"
    r"|INTRACEREBRAL|SUBARACHNOID|SUBDURAL"
    r"|CEREBRAL INFARCT|STROKE"
    r"|PULMONARY EMBOL"
    r"|GRAND MAL STATUS|STATUS EPILEPTICUS"
    r"|KETOACIDOSIS|KETOACID"
    r"|SHOCK|HYPOTENSION"
)


def critical_stays(ds) -> set:
    """Stay ids carrying at least one time-critical diagnosis."""
    # The loader keeps diagnosis as a path in `extensions` rather than loading
    # it — nothing in the four layers reads a discharge diagnosis, and it must
    # stay that way. It is an outcome, and a model that sees it is scoring the
    # answer. This is an evaluation script, which is the one place it belongs.
    d = pd.read_csv(ds.extensions["diagnosis"], quotechar='"')
    hit = d["icd_title"].str.upper().str.contains(CRITICAL_DIAGNOSIS,
                                                  regex=True, na=False)
    return set(d.loc[hit, "stay_id"])


def run(min_readings: int = 3) -> dict:
    ds = load()
    stays = ds.edstays.set_index("stay_id")
    tri = ds.triage.set_index("stay_id")

    critical = critical_stays(ds)

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
            "sick": disposition in SICK,
            "critical": sid in critical, "readings": len(h),
            "escalated": escalated_at is not None,
            "lead_minutes": ((h["charttime"].max() - escalated_at).total_seconds() / 60
                             if escalated_at is not None else None),
            "reasons": "; ".join(reasons),
        })

    df = pd.DataFrame(rows)
    sick, well = df[df["sick"]], df[~df["sick"]]
    crit, not_crit = df[df["critical"]], df[~df["critical"]]
    lead = df.loc[df["escalated"] & df["sick"], "lead_minutes"].dropna()
    crit_lead = df.loc[df["escalated"] & df["critical"], "lead_minutes"].dropna()

    return {
        "stays_examined": len(df),
        # --- primary endpoint: admitted or transferred
        "sensitivity_admitted": round(float(sick["escalated"].mean()), 4) if len(sick) else None,
        "sensitivity_admitted_ci": rate_with_ci(sick["escalated"].to_numpy()),
        "false_positive_discharged": round(float(well["escalated"].mean()), 4) if len(well) else None,
        "false_positive_discharged_ci": rate_with_ci(well["escalated"].to_numpy()),
        "median_lead_minutes": round(float(lead.median()), 1) if len(lead) else None,
        "median_lead_ci": bootstrap(lead.to_numpy()),
        # The claim is not "32% of admitted patients were flagged" — it is that
        # admitted patients were flagged MORE than discharged ones. That is a
        # difference, and a difference needs an interval.
        "discrimination_admitted": gap_with_ci(sick["escalated"].to_numpy(),
                                               well["escalated"].to_numpy()),
        "n_admitted": int(len(sick)), "n_discharged": int(len(well)),
        # --- secondary endpoint: a time-critical diagnosis on the encounter
        "sensitivity_critical": round(float(crit["escalated"].mean()), 4) if len(crit) else None,
        "sensitivity_critical_ci": rate_with_ci(crit["escalated"].to_numpy()),
        "false_positive_noncritical": round(float(not_crit["escalated"].mean()), 4) if len(not_crit) else None,
        "false_positive_noncritical_ci": rate_with_ci(not_crit["escalated"].to_numpy()),
        "median_lead_critical_ci": bootstrap(crit_lead.to_numpy()),
        "discrimination_critical": gap_with_ci(crit["escalated"].to_numpy(),
                                               not_crit["escalated"].to_numpy()),
        "n_critical": int(len(crit)),
        "detail": df,
    }


def _pct(d: dict) -> str:
    return f"{d['rate']:.1%}  95% CI [{d['ci_low']:.1%}, {d['ci_high']:.1%}]  n={d['n']}"


if __name__ == "__main__":
    r = run()
    print(f"stays examined                 {r['stays_examined']}")
    print(f"  admitted / transferred       {r['n_admitted']}")
    print(f"  discharged home              {r['n_discharged']}")
    print(f"  critical diagnosis           {r['n_critical']}")
    print()
    print("PRIMARY ENDPOINT — admitted or transferred")
    print(f"  escalated, admitted          {_pct(r['sensitivity_admitted_ci'])}")
    print(f"  escalated, discharged home   {_pct(r['false_positive_discharged_ci'])}")
    lc = r["median_lead_ci"]
    print(f"  median lead time             {lc['estimate']:.0f} min  "
          f"95% CI [{lc['ci_low']:.0f}, {lc['ci_high']:.0f}]  n={lc['n']}")
    g = r["discrimination_admitted"]
    print(f"  difference                   {g['gap']:+.1%}  "
          f"95% CI [{g['ci_low']:+.1%}, {g['ci_high']:+.1%}]  "
          f"-> {'discriminates' if g['distinguishable'] else 'NOT resolvable'}")
    print()
    print("SECONDARY ENDPOINT — a time-critical diagnosis (exploratory, small n)")
    print(f"  escalated, critical          {_pct(r['sensitivity_critical_ci'])}")
    print(f"  escalated, non-critical      {_pct(r['false_positive_noncritical_ci'])}")
    cc = r["median_lead_critical_ci"]
    if cc["estimate"] is not None:
        print(f"  median lead time             {cc['estimate']:.0f} min  "
              f"95% CI [{cc['ci_low']:.0f}, {cc['ci_high']:.0f}]  n={cc['n']}")
    gc = r["discrimination_critical"]
    print(f"  difference                   {gc['gap']:+.1%}  "
          f"95% CI [{gc['ci_low']:+.1%}, {gc['ci_high']:+.1%}]  "
          f"-> {'discriminates' if gc['distinguishable'] else 'NOT resolvable'}")
    print()
    print("first escalation reasons, most common:")
    d = r["detail"]
    print(d.loc[d["escalated"], "reasons"].str.split(" ").str[0].value_counts().head(5).to_string())
