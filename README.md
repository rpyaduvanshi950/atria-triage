# ATRIA

**A live queue, not a label.**

Emergency-department triage that reorders attention continuously, so the patient
who is *becoming* sickest is seen sooner. It supports the triage nurse; it does
not diagnose, does not prescribe, and cannot lower anyone's priority on its own.

Accenture Innovation Challenge 2026, Round 2, Track 2 (PatientTriage.ai).
Team **Digital Ninja** — Pushpender, Shagun, Atit · IIT Kanpur.

---

## Quick start

```bash
git clone https://github.com/rpyaduvanshi950/atria-triage.git
cd atria-triage
make setup          # one-off: creates .venv, installs dependencies
make streamlit      # the board at http://localhost:8501
```

Give it about ten seconds — the acuity scorer trains on startup, so the board
reads *"waiting for the first arrival…"* until it finishes. That is not a hang.

Three other entry points:

```bash
make demo           # the FastAPI engine at http://127.0.0.1:8000
make web            # the Next.js client at http://localhost:3000 (needs make demo)
make scenarios      # seven deterministic demo cases, printed
```

`make demo` and `make streamlit` are the same engine behind different shells —
the FastAPI build pushes over a websocket, the Streamlit build redraws inside an
auto-refreshing fragment. `make scenarios` is what you narrate a video against,
because it produces identical output every run.

`make help` lists everything.

---

## What it does

The nurse commits to an ESI **before** ATRIA's recommendation exists on their
screen. Only then is it revealed, and the two are compared. Meanwhile the queue
re-ranks itself from vitals as they arrive, and patients who are held too long,
who worsen, or whose data is incomplete are surfaced rather than buried.

Four layers, each with a different amount of authority:

| Layer | Module | Responsibility | Authority |
|---|---|---|---|
| **Layer 0** | `layer0/` | Deterministic red-flag gate — 11 cited rules, age-banded, runs with no model and no network | **Decides** |
| **Layer 1** | `layer1/` | Acuity scorer, conformal confidence, three-pathway model | *Recommends* |
| **Layer 2** | `layer2/` | Re-ranks from vital trajectories inside strict safety bands | *Re-orders* |
| **Layer 3** | `layer3/` | Blind assessment workflow + hash-chained audit log | **Decides** |

**Only Layer 1 contains a trained model.** Layers 0, 2 and 3 are entirely
deterministic — cited thresholds, arithmetic on vital deltas, and a state
machine. That is a design choice, not a gap: the parts that can force a patient
to the top of the queue, or refuse to answer, or record what a clinician did,
should be inspectable line by line rather than learned.

The learned model can never suppress Layer 0, and no machine source can lower a
priority. Both are enforced by tests, not by convention.

---

## The ideas worth reading the code for

### Blind nurse-first assessment — `layer3/workflow.py`

The recommendation is **absent from the payload** before the nurse chooses, not
merely hidden by CSS, so it cannot leak through the DOM or a network tab.

Show a clinician a number first and they converge on it. Automation bias is not
a failure of diligence, it is how attention works under load. Hiding the
recommendation until the human commits is the cheapest known defence — and it
means every encounter produces an independent human label, which is the only
way to tell whether the model is adding anything.

| outcome | reason required |
|---|---|
| match | no |
| nurse **more** urgent than ATRIA | no — logged; the nurse's view stands |
| nurse **less** urgent than ATRIA | **yes**, before sign-off |
| Layer 0 guardrail active | **yes**, plus charge-nurse escalation |
| ATRIA abstained | **yes**, if signing off before the gap is resolved |

Reporting a change clears the sign-off and starts a fresh blind cycle. The old
recommendation is discarded, never carried over.

### The model may not read the nurse's answer — `layer1/features.py`

Adding the nurse's ESI as a feature lifts AUC from **0.809 to 0.859**. We
exclude it anyway. A model already told the answer cannot meaningfully disagree
with it, and the comparison above would be theatre.

Race is excluded for a different reason: it is a social construct standing in
for exposure and access, and using it as a predictor is precisely how Obermeyer
et al. (2019) describes algorithms encoding inequity. It is **audited, never
predicted from**. Sex stays — it carries genuine physiological signal.

### Three outcomes from the gate, not two — `layer0/engine.py`

- **confirmed** — a rule fired on values someone actually recorded → band 1
- **cannot rule out** — fires only on an assumed-worst missing vital → band 2
  and an instruction to measure it
- **not evaluable** — the source has no such column at all

The third matters more than it looks: no source here carries GCS, and gating
every patient on an assumed GCS of 3 fires that rule on all of them.

### When the system refuses to answer

| Rule | Behaviour |
|---|---|
| **RF11** hard stop | Fewer than 3 monitored vitals. No score at all — you cannot triage a sentence |
| **RF12** abstain | Two pathways engaged at near-equal severity. It says it cannot classify rather than manufacturing an answer |

Neither is a low-acuity finding: an unknown patient goes ahead of everyone
already cleared. Both route to a clinician and both hit the audit log.

### The three atria mortis — `layer1/pathways.py`

Every acute presentation kills through one of three gates: the lungs, the heart,
the brain. Each is monitored by four or five parameters, weighted by how
*specific* they are — weighting shared vitals equally makes all three gates light
up on any sick patient, which destroys the point.

This buys two things a single acuity score cannot express. **Diagnostic
uncertainty, separate from triage uncertainty** — a hypothermic trauma patient
scores triage confidence HIGH and diagnostic confidence LOW: certain they are
critical, honest that we cannot say which gate is closing. And **competing
pathologies** — hypothermia plus shock is flagged as a *treatment conflict*,
because a vasopressor constricts already-constricted vessels and drives
necrosis. ATRIA does not choose the drug; it says the two conflict and routes to
a human.

### Safety bands are strict — `layer2/ranking.py`

Operational pressure and waiting time reorder patients *within* a clinical band
and may never move one across a boundary. Bands are explicit and sorted
lexicographically rather than by large numeric offsets — offsets are the usual
trick and they work right up until someone adds a modifier bigger than the gap,
at which point the invariant fails silently.

A test proves a maximally boosted ESI 3 still ranks below an untouched ESI 2.

---

## What has been measured

Every figure below is regenerated by `make report`, which writes
[`docs/results.md`](docs/results.md) and the deck figures from live code. Nothing
is typed by hand, so the slides cannot drift.

| Measure | Result |
|---|---|
| **Layer 1 vs the published benchmark** | **AUC 0.809** on 560,486 real Yale encounters. Hong et al. (2018) report 0.87 — using the nurse's ESI and race, both of which we exclude |
| The price of independence | 0.859 with the nurse's ESI, 0.809 without |
| Operating point | 95.0% sensitivity, 34.1% specificity, 5.0% undertriage — tuned to the ACS ≤5% standard, not to accuracy |
| Cross-site | Train on two hospitals, test on the third: unseen-site AUC within ±0.026 |
| Racial disparity | "Other" undertriaged at 9.2% against 4.0% for White. Removing race from the model cut the gap 8.3 → 5.2 points on its own; calibration took it to 5.0% |
| Layer 2 on real trajectories | 32.2% of later-admitted flagged vs 12.2% of discharged, median **164 min** lead (159 MIMIC stays) |
| Conformal coverage | ≥95% **per class**, calibrated on held-out data |
| Latency | p95 **52 ms** under 3× surge, against a 400 ms budget |

### Three things we found by building

**A dataset that encoded its own answer.** In 143,140 Isfahan records, 100% of
the most-urgent patients had zero recorded vitals against 0.1% of the
mid-urgency band. A model using missing-indicators would have scored beautifully
by learning hospital paperwork. Excluded from training.

**A model that read missing vitals as reassuring.** Blanking HR, RR or systolic
*lowered* predicted risk — a silent undertriage path. Found by auditing, not
assuming; now clamped so an unrecorded vital can never score better than an
average one.

**Our own gate, adult-calibrated.** It fired hypotension on a 3-year-old with a
systolic of 88, which is normal at that age — the exact failure the brief names.
Thresholds are now age-banded on PALS.

---

## Data

Three open datasets, no credentialing. See **[`data/README.md`](data/README.md)**
for provenance and licences — **attribution is a licence condition for all
three**, not a courtesy.

| Source | Role | State |
|---|---|---|
| Yale ED — 560,486 visits, 3 hospitals | Trains and validates Layer 1 | extracted |
| MIMIC-IV-ED Demo — 222 stays | Layer 2 trajectories, schema truth | ready |
| Isfahan ED — 143,140 stays | Generator priors + the leakage case study | ready, **not trainable** |
| Synthetic generator | Paediatrics, surge, deterioration | fitted to real Isfahan priors |

Isfahan is marked non-trainable in code: `Dataset.require_trainable()` raises
`LeakageError` if anyone tries. No raw data is tracked in git; the deployed app
reads precomputed aggregate priors from `data/isfahan_priors.json`.

---

## Layout

```
contracts/     schema.py — the shared column contract; change by consensus only
data/
  loaders/     yale · mimic_demo · isfahan · synthetic, all behind one interface
  README.md    provenance, licences, attribution duties, known traps
layer0/        engine.py + rules.yaml — 11 cited rules, age-banded thresholds
layer1/        features · model · conformal · pathways · interactions · verify · explain
layer2/        ranking (safety bands) · trajectory (deltas) · ratchet (the invariant)
layer3/        workflow (blind assessment) · audit (hash-chained log)
service/       queue · clock · forecast · decision_window · fhir · app (FastAPI)
dashboard/     index.html (the board) · guide.html (served at /guide) · NOTES.md
streamlit_app.py   three tabs: Assessment · Operations & Flow · History
atria-web/     Next.js client — typed, virtualisable, keyboard-first
eval/          fairness · cross_site · lead_time · latency · figures · report
scenarios/     seven seeded demo cases + runner
tests/         156 tests across 13 files
docs/          pitch pack, business proposal, regulatory position, results, figures
Makefile       every command
```

---

## Commands

| Command | Does |
|---|---|
| `make setup` | venv and dependencies |
| `make streamlit` | the Streamlit board on :8501 |
| `make web` | the Next.js client on :3000 (run `make demo` alongside) |
| `make demo` | the FastAPI build on :8000 |
| `make scenarios` | seven deterministic demo cases |
| `make test` | 156 tests |
| `make report` | regenerate `docs/results.md` and all figures |
| `make eval` | latency, cross-site, Layer 2 lead time |
| `make fairness` | subgroup audit and mitigation |
| `make status` | which data sources are loadable |
| `make extract-yale` | one-off Yale extraction (needs R) |

---

## Deploying

`streamlit_app.py` at the root, `requirements.txt` pinned to runtime
dependencies, `runtime.txt` naming Python 3.12, dark theme in
`.streamlit/config.toml`.

1. <https://share.streamlit.io> → sign in with GitHub
2. **New app** → this repo, branch `main`, main file `streamlit_app.py`
3. Deploy

Two things first. **The repo is private** — the free tier allows unlimited
public apps but only one private, so either spend that slot or run
`gh repo edit --visibility public`. And **no raw data is needed**: the deployed
app reads aggregate priors precomputed from the real 143,582 encounters.

Free tier gives 1 GB RAM and sleeps after 12 quiet hours, so wake it before a
pitch. The scorer trains once per container behind `@st.cache_resource`.

---

## Documents

| Document | Contents |
|---|---|
| [`docs/pitch.md`](docs/pitch.md) | Slide content and Q&A, built from the measured results |
| [`docs/results.md`](docs/results.md) | Every measured number, regenerated by `make report` |
| [`docs/business-proposal.md`](docs/business-proposal.md) | Problem framing, users, roadmap, risks |
| [`docs/regulatory.md`](docs/regulatory.md) | Jurisdiction, SaMD class, liability, consent, bias |
| [`docs/deck-changes.md`](docs/deck-changes.md) | What to fix in the pitch deck |
| [`docs/nextjs-migration.md`](docs/nextjs-migration.md) | The migration plan; phases 1–4 are built, phase 5 is not |
| [`atria-web/README.md`](atria-web/README.md) | The Next.js client and the two rules for working on it |
| [`dashboard/NOTES.md`](dashboard/NOTES.md) | Nurse board design decisions |
| [`docsfromsatyansh/ATRIA PRD.pdf`](docsfromsatyansh) | The 55-page product spec this build is aligned to |

---

## Stated limitations

Read these before quoting any number.

- The outcome label is hospital **admission**, a coarser acuity proxy than
  ICU-transfer-or-death. No open ED dataset carries ICU timestamps.
- Yale is **adults-only** with no pain score, so `is_paediatric` and `pain` are
  dropped at fit time. Paediatric cases come from the synthetic generator.
- Layer 2 is validated on **159 real trajectories** — a small sample.
- The fairness gap is **narrowed, not closed**: 5.0% after mitigation is still
  above our own 5-point tolerance. The age finding reversed between synthetic
  and real data, so fairness results do not transfer between datasets.
- The three atria mortis pathways are the **classical triad**, assumed. Round 1
  names only "Cerebral Hypoxia"; if it defined the other two differently, change
  `PATHWAYS` and nothing else moves.
- **Every threshold is a prototype default.** None has been approved by a
  clinical governance body, and none should be used on a real patient.
