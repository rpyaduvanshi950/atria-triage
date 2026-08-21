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
make test       # 40 tests
make status     # which data sources are ready
```

## Layers

| | | |
|---|---|---|
| **Layer 0** | `layer0/` | Deterministic red-flag gate — 10 cited rules, runs offline. Decides |
| **Layer 1** | `layer1/` | Acuity scorer with conformal confidence. Recommends |
| **Layer 2** | `layer2/` | Dynamic re-ranker from vital trajectories. Re-orders |
| **Layer 3** | `layer3/` | Human authority + hash-chained audit log. Decides |

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

Isfahan is deliberately marked non-trainable: its missingness encodes the triage
decision itself. `Dataset.require_trainable()` raises `LeakageError` if anyone
tries. See `data/README.md`.

## Layout

```
contracts/    the schema contract — shared truth, change by consensus only
data/         loaders + the three datasets + provenance
layer0..3/    the four layers
service/      FastAPI, websocket, replay clock          (day 1)
dashboard/    the nurse board — design decisions in NOTES.md
eval/         vs_baseline, fairness, cross_site, lead_time, latency
scenarios/    the six seeded demo scenarios             (day 3)
tests/        40 tests, one per red-flag rule
docs/         proposal outline, deck changes
```

## Plan

The seven-day build plan, with measured dataset profiles and the research behind
each decision:
<https://claude.ai/code/artifact/896e08b0-8e09-41c8-bc61-9ea2acf4e87d>
