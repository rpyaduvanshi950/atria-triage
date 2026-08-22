# ATRIA

A live queue, not a label.

Emergency-department triage assistant for the Accenture Innovation Challenge
2026, Round 2, Track 2 (PatientTriage.ai). Team **Digital Ninja** — Pushpender,
Shagun, Atit.

ATRIA re-ranks every waiting patient continuously from vitals already being
recorded. It changes **order of attention**, not clinical treatment. It may
escalate on its own; it may never de-escalate on its own.

## Running it

```bash
git clone https://github.com/rpyaduvanshi950/atria-triage.git
cd atria-triage
make setup          # one-off: creates .venv and installs dependencies
make demo           # starts the live board
```

Then open **<http://127.0.0.1:8000>**. Ctrl-C to stop.

**Give it about ten seconds.** On startup it trains the Layer 1 scorer on 3,000
synthetic patients, so the board reads *"waiting for the first arrival…"* until
that finishes. Then patients begin arriving and the queue reorders itself live.
The shift loops, so the board is never empty while you are recording.

### Things to try while it is running

| | |
|---|---|
| **AUDIT** button, top right | The hash-chained trail — every entry with its hash and predecessor, and a live chain-integrity indicator |
| **OVERRIDE** on any row | Pick a *higher* band number and the downgrade warning appears. That is the move no model is permitted to make; it writes to the audit log with a structured reason code |
| Kill the model service | `curl -X POST http://127.0.0.1:8000/api/degraded/1` — the banner appears and Layer 0 keeps gating. `/0` restores it |

### For the video, use the scripted run instead

```bash
make scenarios
```

Runs all six demo scenarios deterministically through the same engine and prints
what happened. Same result every time, so takes are reproducible. `make demo` is
the live board; `make scenarios` is what you narrate against.

### Everything else

```bash
make test           # 92 tests (skips the slow measurement runs)
make test-all       # all 94, including figure and report generation
make status         # which data sources are loadable right now
make eval           # latency, cross-site, Layer 2 lead time
make fairness       # subgroup audit and mitigation
make report         # regenerate docs/results.md and the deck figures
make extract-yale   # one-off Yale extraction (needs R — see data/README.md)
```

`make help` lists all of them.

## What is built

A working end-to-end prototype, not a notebook.

- **Four layers**, wired together in a live queue engine — deterministic gate,
  acuity scorer with conformal confidence, trajectory re-ranker, human authority
  with a tamper-evident audit trail.
- **A replay clock** with speed and surge multipliers that turns a static
  dataset into a live-feeling ED, plus a 3x surge mode.
- **A nurse-facing board** over a websocket — rows reorder as patients escalate.
  Zero dependencies: no React, no build step, no CDN.
- **A calibrated synthetic generator** fitted to real Isfahan priors, supplying
  the paediatric, surge and deterioration cases no open snapshot dataset carries.
- **Six scripted scenarios** covering every minimum expectation in the brief.
- **An evaluation suite** — fairness, latency, cross-site, Layer 2 lead time —
  that regenerates the deck's figures and numbers on demand.
- **94 tests**, including one per red-flag rule and a proof that no machine
  source can suppress a red flag.

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
| Fairness | geriatric undertriage 18.1% -> gap closed to 0.6% by subgroup-conditional calibration |

Every figure above is produced by `make report`, which writes
[`docs/results.md`](docs/results.md) and the deck figures. Nothing is typed by
hand, so the slides cannot drift away from the code.

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
eval/         fairness, cross_site, lead_time, latency, figures, report
scenarios/    the six seeded demo scenarios + runner
tests/        94 tests — one per red-flag rule, the invariant, the audit chain
docs/         business proposal, measured results, figures, deck changes
Makefile      every command above
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

## Documents

| | |
|---|---|
| [`docs/business-proposal.md`](docs/business-proposal.md) | The Round 2 proposal — framing, design, users, evidence, roadmap, risks |
| [`docs/results.md`](docs/results.md) | Every measured number, regenerated by `make report` |
| [`docs/figures/`](docs/figures) | Deck figures, palette validated for colour-vision deficiency |
| [`docs/deck-changes.md`](docs/deck-changes.md) | What to fix and add in the pitch deck |
| [`dashboard/NOTES.md`](dashboard/NOTES.md) | Nurse board design decisions |

## Plan

The seven-day build plan, with measured dataset profiles and the research behind
each decision:
<https://claude.ai/code/artifact/896e08b0-8e09-41c8-bc61-9ea2acf4e87d>
