# ATRIA

A live queue, not a label.

Emergency-department triage assistant for the Accenture Innovation Challenge
2026, Round 2, Track 2 (PatientTriage.ai). Team **Digital Ninja** — Pushpender,
Shagun, Atit.

ATRIA re-ranks every waiting patient continuously from vitals already being
recorded. It changes **order of attention**, not clinical treatment. It may
escalate on its own; it may never de-escalate on its own.

## Quick start

```bash
make setup      # venv + dependencies
make test       # 85 tests
make demo       # live board at http://127.0.0.1:8000
make status     # which data sources are ready
make scenarios  # the six demo scenarios, scripted
make eval       # latency, cross-site, Layer 2 lead time
```

## Layers

| | | |
|---|---|---|
| **Layer 0** | `layer0/` | Deterministic red-flag gate — 10 cited rules, runs offline. Decides |
| **Layer 1** | `layer1/` | Acuity scorer + Mondrian conformal confidence. Recommends |
| **Layer 2** | `layer2/` | Dynamic re-ranker from vital trajectories. Re-orders |
| **Layer 3** | `layer3/` | Human authority + hash-chained audit log. Decides |

## What has been measured

| | |
|---|---|
| Layer 2 on 159 real MIMIC trajectories | 32.2% of admitted flagged vs 12.2% of discharged, median 164 min lead |
| Conformal coverage | >=95% per class, calibrated on held-out data |
| Latency, p95 | 41 ms at 3x surge, against a 400 ms budget |
| Missingness audit | HR, RR and SBP absences were read as *reassuring*; now clamped |

The escalation invariant lives in `layer2/ratchet.py` and is five lines long.
`tests/test_ratchet.py` proves no machine source can suppress a red flag.

## Data

Three open datasets, no credentialing. See **`data/README.md`** for provenance,
licences and attribution duties — attribution is a licence condition for all
three, not a courtesy.

| Source | Role | Ready |
|---|---|---|
| Yale ED (560,486 visits) | Trains Layer 1 | needs one R extraction step |
| MIMIC-IV-ED Demo (222 stays) | Layer 2 trajectories, schema truth | yes |
| Isfahan ED (143,140 stays) | Generator priors + leakage case study | yes, **not trainable** |
| Synthetic | Trajectories, paediatrics, surge | generated, fitted to Isfahan priors |

Isfahan is deliberately marked non-trainable: its missingness encodes the triage
decision itself. `Dataset.require_trainable()` raises `LeakageError` if anyone
tries. See `data/README.md`.

## Layout

```
contracts/    the schema contract — shared truth, change by consensus only
data/         loaders + the three datasets + provenance
layer0..3/    the four layers
service/      replay clock, queue engine, FastAPI + websocket
dashboard/    the nurse board — design decisions in NOTES.md
eval/         vs_baseline, fairness, cross_site, lead_time, latency
scenarios/    the six seeded demo scenarios             (day 3)
tests/        40 tests, one per red-flag rule
docs/         proposal outline, deck changes
```

## Layer 0's three outcomes

The gate does not answer yes/no. It answers one of three things, and the
distinction is what keeps it usable:

- **confirmed** — a rule fired on values someone actually recorded. Band 1.
- **cannot rule out** — a rule fires only when a missing vital is assumed
  worst-case. Band 2, plus an instruction to measure it. Unknown is not normal,
  but it is not the same as critical either: escalating every blank field to
  band 1 floods the board and trains staff to ignore it.
- **not evaluable** — the source has no such column at all. No source here
  carries GCS, and gating every patient on an assumed GCS of 3 would fire that
  rule on all of them.

## Three findings worth a slide each

**Isfahan encodes its own triage decision.** 100% of grade-1 patients have zero
recorded vitals against 0.1% of grade-3. A model using missing-indicators would
have scored near-perfectly on hospital workflow rather than physiology. Excluded
from training, kept as the case study.

**The model learned that missing vitals are reassuring.** Blanking heart rate,
respiratory rate or systolic *lowered* predicted risk — a silent undertriage
path, found by auditing rather than assuming. `layer1/verify.py` reports it and
the scorer clamps it.

**Our own Layer 0 was adult-calibrated.** It fired hypotension on a 3-year-old
with SBP 88, which is normal for that age — exactly the failure the brief names.
Thresholds are now age-banded on PALS.

## Plan

The seven-day build plan, with measured dataset profiles and the research behind
each decision:
<https://claude.ai/code/artifact/896e08b0-8e09-41c8-bc61-9ea2acf4e87d>
