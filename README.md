# ATRIA

**A live queue, not a label.**

Emergency-department triage that reorders attention continuously, so the patient
who is *becoming* sickest is seen sooner. It supports the triage nurse; it does
not diagnose, does not prescribe, and cannot lower anyone's priority on its own.

Accenture Innovation Challenge 2026 · Round 2, Track 2 (PatientTriage.ai)
Team **Digital Ninja** — Pushpender, Shagun, Atit · IIT Kanpur

|                                  |                                                 |
| -------------------------------- | ----------------------------------------------- |
| **Live board**             | <https://atria-triage.vercel.app>                 |
| **Live engine / API docs** | <https://atria-triage.onrender.com/docs>          |
| **Source**                 | <https://github.com/rpyaduvanshi950/atria-triage> |

> The hosted board runs on free tiers and sleeps after ~15 minutes idle. The
> first request wakes it and takes about 50 seconds. Open the engine link first,
> wait for it to answer, then open the board.

---

## Contents

1. [The problem](#1-the-problem)
2. [The solution](#2-the-solution)
3. [Architecture](#3-architecture)
4. [How each layer is implemented](#4-how-each-layer-is-implemented)
5. [Key features](#5-key-features)
6. [Data](#6-data)
7. [Results](#7-results)
8. [Three things we found by building it](#8-three-things-we-found-by-building-it)
9. [Running it locally — step by step](#9-running-it-locally--step-by-step)
10. [Deploying it](#10-deploying-it)
11. [Repository layout](#11-repository-layout)
12. [Testing](#12-testing)
13. [Limitations, stated plainly](#13-limitations-stated-plainly)

---

## 1. The problem

Triage happens once, at the door. A nurse assigns an Emergency Severity Index
from 1 (resuscitate now) to 5 (can safely wait), and that number follows the
patient into the waiting room and mostly stays there. The patient's condition
does not.

Two failures follow:

- **People deteriorate unseen.** Someone stable at 09:00 can be in trouble by
  09:40, and in a busy department nothing is systematically watching.
- **The queue drifts to first-come-first-served**, which is not the same as
  sickest-first.

Across 5.3M encounters, ESI was wrong 32.2% of the time and caught only 65.9% of
patients who went on to need a life-saving intervention. Delay converts that
error into death: one extra death per 82 patients held 6–8 hours.

## 2. The solution

A **continuously re-ranking attention list**. ATRIA watches vital signs as they
are re-taken and changes the order in which patients should be seen. Every
decision stays with a human, and the record says who made it.

> **In one sentence.** ATRIA turns triage from a decision made once into a
> decision kept under review — while leaving every actual decision with a
> clinician, and writing down who made it.

### What the prototype covers

Not a happy path. Each of these is exercised by the running system and by a
test, not described in a slide.

| | |
|---|---|
| **100-patient simulated ED shift** | Three simulated hours, replayed in six minutes from a fixed seed |
| **Paediatric and geriatric** | Five age-banded threshold functions; `is_paediatric` and `is_geriatric` as model features |
| **Ambiguous / abstain** | RF12 at ≥0.75 pathway overlap; RF11 below 3 recorded vitals |
| **Missing history and manual intake** | Check a patient in by hand with any subset of vitals; blanks stay blank |
| **Clinician override** | The only path that lowers urgency, and the only one that demands a reason |
| **3× surge** | Latency measured under three times the arrival rate |
| **Confidence shown** | Two of them: how urgent, and what is wrong — reported separately |

### Why this is hard to copy

The moat is not the model. It is the shape of the decision around it.

| Problem | What ATRIA does about it |
|---|---|
| **Automation bias** | The nurse goes first, blind. The recommendation is absent from the payload until they commit |
| **Liability** | A licensed clinician owns the final decision. No machine source can lower a priority |
| **Explainability** | Reasons appear where a decision needs justifying, not as decoration on every row |
| **Auditability** | Disagreement becomes structured evidence: nurse ESI, ATRIA ESI, outcome, reason code, and who signed |
| **Compounding advantage** | Because every nurse answers blind, **independent human labels accumulate** — the one dataset a competitor cannot buy |

That last row is the one worth pressing on. A system that shows its
recommendation first can never learn whether it helped, because every label it
collects has already been contaminated by its own suggestion.

---

## 3. Architecture

```
                     ┌─────────────────────────────────────────┐
  Vitals, arrivals   │  LAYER 0 · Safety rules      DECIDES    │
  ───────────────────▶  11 cited thresholds, age-banded        │
                     │  Runs first. No model can suppress it.  │
                     └────────────────┬────────────────────────┘
                                      ▼
                     ┌─────────────────────────────────────────┐
                     │  LAYER 1 · Acuity scorer    RECOMMENDS  │
                     │  Gradient-boosted trees, 23 features    │
                     │  Conformal confidence, per class        │
                     └────────────────┬────────────────────────┘
                                      ▼
                     ┌─────────────────────────────────────────┐
                     │  LAYER 2 · Trajectory      RE-ORDERS    │
                     │  Deltas between readings, shock index   │
                     │  Strict bands: no crossing a boundary   │
                     └────────────────┬────────────────────────┘
                                      ▼
                     ┌─────────────────────────────────────────┐
                     │  LAYER 3 · Human authority   DECIDES    │
                     │  Blind assessment · hash-chained audit  │
                     └────────────────┬────────────────────────┘
                                      ▼
        FastAPI + WebSocket ──▶ Next.js board / Streamlit board
                                      │
                             SQLite (append-only audit)
```

The important column is the last one: **which layers are allowed to decide
anything.**

| Layer                        | What it does                                                                                                                                                   | Authority                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| **0 — Safety rules**  | Eleven rules with clinical citations. SpO₂ < 90. Systolic below the**age-banded** minimum. Active seizure. Stroke signs inside the thrombolysis window. | **Decides.** Forces priority 1; no model output can suppress it |
| **1 — Acuity scorer** | The only trained model. 23 features available within five minutes of arrival                                                                                   | *Recommends*                                                        |
| **2 — Trajectory**    | Compares each reading against the previous ones — direction of travel, not the snapshot                                                                       | *Re-orders*                                                         |
| **3 — Human**         | The nurse's workflow and a tamper-evident record                                                                                                               | **Decides**                                                     |

**Only Layer 1 contains a model.** Layers 0, 2 and 3 are ordinary deterministic
code — fixed thresholds, arithmetic and a state machine. That was a choice: the
parts that can force a patient to the front, refuse to answer, or record what a
clinician did should be readable line by line by someone who does not trust
machine learning.

**The escalation ratchet.** Layers 0, 1 and 2 can all *raise* urgency. **None can
lower it.** Only a clinician can, and it is recorded with their identity, reason
code, model version and the input snapshot.

### Technology

| Part            | Built with                                     | Why                                                                                 |
| --------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| Clinical engine | Python 3.12, pandas, NumPy                     | Plain code with no framework around the safety logic                                |
| Model           | scikit-learn`HistGradientBoostingClassifier` | Handles missing values natively; each prediction is explainable by feature          |
| Safety rules    | YAML with a citation per rule                  | A clinician can change a threshold without touching code                            |
| API             | FastAPI, uvicorn, WebSocket — 25 routes       | Pushes on event rather than polling                                                 |
| Board           | Next.js 16, React 19, TypeScript, Tailwind 4   | The stack the PRD specifies; typed responses catch contract drift at build time     |
| Long queues     | TanStack Virtual                               | 200+ patients at 60fps; only visible rows in the DOM                                |
| Second board    | Streamlit                                      | Same engine, different shell — evidence the logic is UI-independent                |
| Audit store     | SQLite                                         | One portable file an auditor can take away;`UPDATE`/`DELETE` refused by trigger |
| Auth            | JWT (HS256), PBKDF2-SHA256                     | Standard and boring; no password stored readably                                    |
| Interop         | FHIR R4, read-only                             | Verified against the public HAPI sandbox                                            |
| Tests           | pytest — 274                                  | Every safety rule above has a test that fails if broken                             |

---

## 4. How each layer is implemented

### Layer 0 — the gate · [`layer0/`](layer0/)

Thresholds live in [`layer0/rules.yaml`](layer0/rules.yaml), each row carrying
its clinical source. The code reads the table; it does not contain the numbers.
Age-dependent thresholds (systolic, respiratory rate) are looked up by band
rather than assumed adult.

**The gate returns three answers, not two:**

|                           |                                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **Confirmed**       | A rule fired on a value someone actually recorded → priority 1                                                    |
| **Cannot rule out** | Fired only because a missing vital was assumed worst-case → priority 2**plus an instruction to measure it** |
| **Not evaluable**   | The source has no such column at all → skipped                                                                    |

The third matters more than it looks. No dataset here carries GCS; gating every
patient on an assumed GCS of 3 would fire RF01 on all of them.

**When it refuses to answer:**

- **RF11 — hard stop.** Fewer than 3 of the 6 monitored vitals recorded. No
  score at all. You cannot triage a sentence.
- **RF12 — abstain.** Two pathways engaged with ≥ 0.75 overlap at ≥ 0.5
  severity. It says it cannot classify rather than manufacturing an answer.

Neither is a low-acuity finding. An unknown patient goes **ahead** of everyone
already cleared (priority 2), routed to a clinician, and both are audited.

### Layer 1 — the scorer · [`layer1/`](layer1/)

Trained on **560,486 real Yale encounters**. Split three ways: fit, calibrate,
test. Band cuts come from the risk distribution, not an arbitrary threshold.

**The nurse's ESI and the patient's race are excluded from the inputs** — the
first so the model can genuinely disagree with the nurse, the second because a
model must not use race as a predictive shortcut.

**Two confidences, not one.** *Urgency* confidence comes from a Mondrian
(class-conditional) conformal set with a ≥95% guarantee **per class**; a marginal
guarantee is met by being reliable about common cases and unreliable about rare
ones, and the rare ones here are the critical patients. *Cause* confidence comes
from how much the three failure pathways overlap.

**Never scores missingness as reassuring** — see §8.

**Re-scored on every new reading.** Layers 0 and 1 re-run whenever an
observation arrives, not just at arrival, so a patient who walks in talking and
whose SpO₂ then falls to 84 gets a red-flag check rather than a trend
calculation. The model itself is held to one score per patient per ten seconds
so a rating does not churn; **Layer 0 is deliberately outside that hold**, because
a red flag has to fire on the reading that crosses the threshold rather than the
next one after a timer.

**Every score is attributed.** TreeSHAP over the fitted trees reports what the
model actually weighed for *this* patient, which is not the same as the pathway
description beside it: a patient can trip the respiratory pathway on a
borderline breathing rate while the score is driven by blood pressure. Both are
shown, because when they disagree that is worth seeing. The attribution is
read-only — nothing downstream consumes it, since an explanation that can alter
what it explains is not one. If the explainer cannot be built, patients are
still scored and the board falls back to the descriptive reasons.

### Layer 2 — trajectory · [`layer2/`](layer2/)

Arithmetic on the last few readings:

| Signal                  | Threshold   |
| ----------------------- | ----------- |
| SpO₂ falling           | ≥ 3 points |
| Systolic falling        | ≥ 15       |
| Heart rate rising       | ≥ 20       |
| Respiratory rate rising | ≥ 6        |
| Shock index (HR/SBP)    | ≥ 0.9      |

Re-assessment is due at **5 / 15 / 45 / 90 / 180 minutes** for priorities 1–5.
Being overdue forces a re-look; it does **not** raise priority. Waiting is not
deterioration. Only at 3× the safe wait does it escalate by one, as a backstop.

**Bands are strict.** Operational pressure and waiting time reorder patients
*within* a band and can never cross a boundary. A maximally boosted priority 3
still ranks below an untouched priority 2, and a test proves it.

`rank_all()` in [`layer2/ranking.py`](layer2/ranking.py) decides the board order,
and the board sorts on nothing else — the list agrees with the ratings printed on
it. Anything that needs attention first already carries a band that puts it
there: a fired rule is band 1, an abstention band 2.

### Layer 3 — workflow and record · [`layer3/`](layer3/)

A three-stage machine: awaiting nurse → compared → signed. Plus a hash chain
where **each entry embeds the hash of the one before it**, stored in SQLite and
rebuilt from disk on startup. The database refuses `UPDATE` and `DELETE` by
trigger, so tampering fails when attempted rather than being caught later by a
check nobody ran.

---

## 5. Key features

### The blind nurse-first assessment — the idea the design rests on

**The nurse decides first. ATRIA speaks second.**

The recommendation is not on the page until the nurse commits — not hidden by
CSS, **absent from the payload**. The server returns 409 if asked early and
issues a **single-use token** when the nurse's answer is stored, so the ordering
is a server invariant rather than a client convention.

Two reasons, and the second is the one people miss:

- **Anchoring.** Show a clinician a number first and they converge on it. That
  is not a failure of diligence, it is how attention works under load.
- **It creates evidence.** Because the nurse always answers blind, every
  encounter produces an independent human label — the only way to know whether
  the model adds anything.

**Measured cost: 0.05 AUC.** Letting the model read the nurse's ESI lifts it
from 0.809 to 0.859. We give that up deliberately and put it on the slide.

**What happens after the reveal:**

| The nurse chose             | What happens                   | Reason required                      |
| --------------------------- | ------------------------------ | ------------------------------------ |
| Same as ATRIA               | Confirm and move on            | No                                   |
| **More** urgent       | Stands, difference logged      | No — escalation is never questioned |
| **Less** urgent       | Blocked until justified        | **Yes**                        |
| Anything, safety rule fired | Blocked, charge nurse notified | **Yes**                        |
| Anything, ATRIA abstained   | Blocked until justified        | **Yes**                        |

Choosing "something else" as a reason requires free text: *"other"* on its own
tells a reviewer nothing.

### Everything else

- **Triage gates treatment.** A bay only takes a patient who has been signed
  off. Nobody is treated before they are triaged.
- **Two board views** — Attention order and Treatment bay, the latter ordered by
  when care began so it does not reshuffle under a nurse working down it.
- **Colour-coded priorities** — the five colours an emergency department already
  uses. Every foreground clears 4.5:1 contrast.
- **The queue settles every 20 seconds** so it does not move while being read —
  but **anything that makes a patient more urgent appears immediately.**
- **Ranking is explained** per patient, in the order the sort actually applies.
- **Logs in two views** — what ATRIA did, and what people did about it. Filters
  over one chain, never two records.
- **Roles**: nurse, charge nurse, clinician, flow coordinator, clinical
  governance, admin. The auditor cannot write; ops cannot lower a priority.
- **Shadow mode** — every layer runs, nothing acts, disagreements go to the
  trail. Phase 1 of a real deployment.
- **Degraded mode** — kill the model and Layer 0 keeps gating.
- **Check a patient in by hand**, with or without vitals.

---

## 6. Data

| Source                               | Size                                | Used for                                                        | In repo                                                       |
| ------------------------------------ | ----------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------- |
| **Yale ED** (Hong et al. 2018) | 560,486 encounters, 3 hospitals     | Trains and validates Layer 1                                    | No — re-fetchable                                            |
| **MIMIC-IV-ED demo**           | 222 stays, 159 with repeated vitals | Validates Layer 2                                               | No — ODbL                                                    |
| **Isfahan ED**                 | 143,140 stays                       | Priors for the generator.**Excluded from training** (§8) | No — CC BY 4.0                                               |
| **Synthetic generator**        | on demand                           | Paediatric and surge cases; moving vitals                       | Yes,[`data/loaders/synthetic.py`](data/loaders/synthetic.py) |

**No dataset is included in this repository.** All three are gitignored: they
are freely re-fetchable from their sources, and not redistributing them avoids
any licence question. What is committed is the *code* that reads them
([`data/loaders/`](data/loaders/)), a 1 KB file of aggregate priors, and the
extraction script.

**The application runs without any of them.** The trained model is committed as
a frozen artifact with its manifest, and the demo board generates its own
patients. `make status` shows which sources are present on your machine;
[`data/README.md`](data/README.md) records provenance, licence and attribution
for each.

---

## 7. Results

Every number is produced by a script in [`eval/`](eval/) and regenerated by
`make report`. None is typed by hand — run it and every figure below is
recomputed from the data.

| Metric                           | Result                                                                                                                                                                |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Layer 1 discrimination** | **AUC 0.809** on 560,486 real encounters (benchmark 0.87 uses nurse ESI + race, which we exclude)                                                               |
| **Operating point**        | 95.0% sensitivity / 34.1% specificity, tuned to the ACS ≤5% undertriage standard                                                                                     |
| **Layer 2 lead time**      | Flags**32.2%** of later-admitted vs **12.2%** discharged — **+20.0 points, 95% CI [+4.6, +31.2]**. Median **164 min** warning, CI [111, 258] |
| **Fairness**               | Worst subgroup gap**5.3% → 2.1%** out of sample, 95% CI [0.4, 4.3] — inside our 5-point tolerance                                                             |
| **Conformal coverage**     | ≥95%**per class**, not on average                                                                                                                              |
| **Latency**                | **p95 52 ms** under 3× surge locally; **p95 10.8 ms** on the hosted engine                                                                               |
| **Soak test**              | 25 shifts, 434 patients, 565 full workflows, 0 failures                                                                                                               |
| **Tests**                  | **274 passing**                                                                                                                                                 |

---

## 8. Three things we found by building it

None was in any plan. Each is a way the system could have quietly harmed
someone.

**The dataset that would have taught it the wrong lesson.** In the Isfahan data,
**100% of the most critical patients have no recorded vitals** — the sickest
bypass the triage form. A model using missing-indicators would learn that *an
empty form means a dying patient*: excellent scores, useless in any hospital with
different paperwork. We excluded it from training and kept it for priors.

**The model read missing vitals as reassuring.** Blanking each vital and
measuring the shift showed that a missing heart rate, respiratory rate or
systolic *lowered* predicted risk — a silent undertriage path that targets
exactly the patient nobody has got round to measuring. Scores are now clamped so
an unrecorded vital can never score better than the population median.

**Our own safety rules were adult-calibrated.** They fired hypotension on a
three-year-old at SBP 88, which is normal at that age. The layer built to
protect people was itself wrong about children. It now uses PALS age bands.

---

## 9. Running it locally — step by step

### Prerequisites

- Python **3.12**, Node **20+**, and `make`
- No dataset downloads required

### Step 1 — install

```bash
git clone https://github.com/rpyaduvanshi950/atria-triage.git
cd atria-triage
make setup                 # creates .venv and installs dependencies
```

### Step 2 — verify the build

```bash
make test                  # 274 tests, about 6 minutes
```

### Step 3 — start the engine

```bash
make demo                  # FastAPI on http://127.0.0.1:8000
```

It prints what it is running:

```
ATRIA: auth on with seeded demo accounts (nurse.demo, …); password = username
ATRIA: audit trail -> data/atria_audit.db
ATRIA: demo shift = 100 patients over 3h at 30x (~6 min real), 5 bays, seed 7
```

### Step 4 — start the board, in a second terminal

```bash
make web                   # Next.js on http://localhost:3000
```

Open **<http://localhost:3000>**. The sign-in fields are pre-filled with
`nurse.demo` / `nurse.demo` because the seeded accounts are live locally.

| Account         | Password        | Role                                    |
| --------------- | --------------- | --------------------------------------- |
| `nurse.demo`  | `nurse.demo`  | Triage nurse                            |
| `charge.demo` | `charge.demo` | Charge nurse — can open and close bays |
| `doc.demo`    | `doc.demo`    | Clinician — can lower a priority       |
| `audit.demo`  | `audit.demo`  | Clinical governance — read-only        |
| `admin.demo`  | `admin.demo`  | Everything, including shadow mode       |

### Every command

| Command | Does |
| ------------------ | ------------------------------------------------- |
| `make setup` | venv and dependencies |
| `make test` | the full test suite |
| `make demo` | the engine on :8000 |
| `make web` | the Next.js board on :3000 |
| `make streamlit` | the second board on :8501 |
| `make shadow` | run in shadow mode: everything runs, nothing acts |
| `make scenarios` | seven deterministic demo cases, printed |
| `make freeze` | retrain and pin the model artifact + manifest |
| `make report` | regenerate every measured number and figure |
| `make eval` | latency, cross-site, Layer 2 lead time |
| `make fairness` | subgroup audit and mitigation |
| `make status` | which data sources are present |
| `make explainer` | re-render the plain-words PDF |

### Everything at once, with Docker

```bash
docker compose up
```

Board on :3000, engine on :8000, Streamlit on :8501, audit trail on a named
volume.

### Configuration

| Variable                  | Default                                | Purpose                                                                            |
| ------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------- |
| `ATRIA_SECRET`          | random per process                     | JWT signing key.**Set it in production** or every restart signs everyone out |
| `ATRIA_USERS`           | seeded demo accounts                   | JSON of real accounts. Password**hashes** only                               |
| `ATRIA_AUTH`            | `on`                                 | `off` disables sign-in entirely (projector demos)                                |
| `ATRIA_DB`              | in memory                              | Path to the SQLite audit trail                                                     |
| `ATRIA_ALLOWED_ORIGINS` | localhost dev ports                    | CORS allow-list; never a wildcard                                                  |
| `ATRIA_SHADOW`          | off                                    | Start in shadow mode                                                               |
| `ATRIA_FHIR_BASE`       | unset                                  | A FHIR R4 server to read vitals from                                               |
| `ATRIA_DEMO_*`          | see[`service/app.py`](service/app.py) | Patients, speed, seed, bays, headroom                                              |

Generate a password hash:

```bash
.venv/bin/python -c "from service.auth import hash_password; print(hash_password('your-password'))"
```

---

## 10. Deploying it

Three pieces, three hosts.

| Piece           | Host                      | Notes                                                                                                          |
| --------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Engine          | **Render**          | Docker.[`render.yaml`](render.yaml) describes the service. Needs WebSockets and a long-running process        |
| Board           | **Vercel**          | Root directory`atria-web`. Set `NEXT_PUBLIC_ATRIA_API` **before the first build** — Next inlines it |
| Streamlit board | **Streamlit Cloud** | `streamlit_app.py`, optional                                                                                 |

The board **proxies the API through itself** (`next.config.ts` rewrites), so the
browser only ever talks to its own origin and the engine's CORS allow-list stays
narrow instead of growing a line for every preview deployment. The WebSocket
connects directly, because WebSockets are not subject to CORS.

---

## 11. Repository layout

```
layer0/          the red-flag gate — rules.yaml + engine.py
layer1/          the acuity model, pathways, conformal prediction
layer2/          trajectory analysis and safety-banded ranking
layer3/          blind workflow, hash-chained audit, SQLite store
service/         FastAPI app, queue engine, auth, shadow mode, FHIR client
ml/              frozen model artifact + manifest, and the freeze script
data/loaders/    one loader per source, all conforming to contracts/schema.py
eval/            every measured number, plus figures and uncertainty helpers
scenarios/       seven deterministic demo cases
tests/           274 tests
atria-web/       the Next.js board
dashboard/       a plain-HTML board served by the engine itself
```

## 12. Testing

```bash
make test
```

274 tests. The ones worth reading are the ones that encode a clinical rule:

- `test_platform.py` — **no route is accidentally public** (walks every route
  rather than a hand-written list, which is how it caught two unguarded writes)
- `test_queue.py` — a bay only takes a triaged patient; a patient who
  deteriorates after sign-off is not stranded
- `test_ratchet.py` — no machine source can lower a priority
- `test_layer0.py` — age-banded thresholds; the refusal message
- `test_abstention.py` — refusing to score is an escalation, not a shrug
- `test_uncertainty.py` — the statistics behind the reported intervals

## 13. Limitations, stated plainly

- **The outcome label is hospital admission**, a coarser acuity proxy than
  ICU-transfer-or-death. We checked: neither available dataset carries ICU
  timestamps.
- **We tried a sharper endpoint and it did not work.** A time-critical diagnosis
  instead of admission gave **+5.1 points, 95% CI [−12.9, +28.5], n=19** — not
  resolvable. Published as a negative result, and the strongest argument we have
  for credentialed data access.
- **Layer 2 rests on 159 real trajectories.** Small, and now reported that way:
  every rate carries an interval.
- **The fairness gap is inside tolerance, not zero** — 2.1%, CI [0.4, 4.3]. Four
  subgroups are too small to estimate at all; they are named rather than dropped.
- **The three failure pathways are the classical triad, assumed.** Round 1
  material names only one explicitly.
- **Patient records are held in memory.** Only the audit trail is written to
  SQLite. A restart loses the live board and keeps the evidence, which is the
  right way round but is not the same as durable state.
- **No hospital feed is connected.** FHIR is verified against a public sandbox.
- **Nothing here has been through clinical governance.** Every threshold is a
  prototype default, and none should be used on a real patient.

---

**Prototype. Not a medical device. Not for use on real patients.**
