# How ATRIA works

What is happening on the board, what each part does, and every rule that governs
it. Written after a soak test across 25 shifts and 565 full nurse workflows.

---

## What you are looking at

A simulated emergency department, replayed. Patients arrive, wait, are assessed,
go into a treatment bay, and leave. While they wait their vitals keep changing,
and ATRIA keeps re-ranking who should be seen next.

Nothing on the board is a real patient. Everyone is generated from distributions
fitted to 143,140 real Iranian emergency records, with trajectories matched to
real vital-sign sequences from Boston.

### The shift, as simulated

| | |
|---|---|
| Arrivals | 100 patients over 3 simulated hours, replayed at 30x, so a shift runs about 6 minutes |
| Treatment bays | 5, adjustable from the board by a charge nurse. When one frees, the highest-priority **triaged** patient goes in |
| Order of events | A bay only takes a patient the nurse has signed off. Nobody is treated before they are triaged |
| Repeatability | The shift uses a fixed seed, so every run brings back the same patients in the same order |
| Time in a bay | 55 min at priority 1, down to 15 min at priority 5 |
| Vitals | Re-recorded every ~15 minutes, matching real MIMIC sampling |
| Missing vitals | 18% of fields at normal load, rising to 34% under a 3× surge |

The surge figure is deliberate. A department at three times volume does not
record three times fewer vitals, but it records meaningfully fewer — and that is
exactly when a model is most tempted to read missingness as a signal.

---

## The one thing to understand: the blind cycle

**The nurse decides first. ATRIA speaks second.**

Its recommendation is not on the page until the nurse commits — not hidden by
CSS, *absent from the payload*. The server refuses to reveal it (HTTP 409) and
issues a one-time token when the nurse's answer is stored, so the ordering
cannot be skipped by a client that gets it wrong.

Why: show a clinician a number first and they converge on it. That is not a
failure of diligence, it is how attention works under load. Hiding the
recommendation until the human commits is the cheapest known defence, and it has
a second benefit — every encounter produces an independent human label, which is
the only way to tell whether the model is adding anything at all.

It is also why the model is not allowed to use the nurse's ESI as an input. A
model already told the answer cannot meaningfully disagree with it.

### What happens after the reveal

| The nurse said | ATRIA said | What happens | Reason required |
|---|---|---|---|
| Same | Same | Confirm and move on | No |
| **More** urgent | Less urgent | Nurse's view stands, difference logged | No — a clinician escalating is never questioned |
| **Less** urgent | More urgent | Blocked until justified | **Yes** |
| Anything | A hard rule fired | Blocked until justified, charge nurse notified | **Yes** |
| Anything | Refused to score | Blocked until justified | **Yes** |

**Reporting a change** clears the sign-off and starts a fresh blind cycle with a
new token. The previous recommendation is discarded rather than shown again —
carrying it over would anchor the very decision that has to stay independent.

---

## The four layers

Only **Layer 1** contains a trained model. Layers 0, 2 and 3 are deterministic:
cited thresholds, arithmetic on vital deltas, and a state machine. That is a
choice. The parts that can force a patient to the top of the queue, refuse to
answer, or record what a clinician did should be inspectable line by line.

### Layer 0 — the red-flag gate · **decides**

Eleven rules, each carrying a clinical citation. Runs before the model, with no
network and no model loaded, so it keeps working when everything else is down.

| Rule | Fires when |
|---|---|
| RF01 | GCS ≤ 8 |
| RF02 | SpO₂ < 90% |
| RF03 | Systolic below the **age-banded** minimum — 90 for adults, 70 + 2×age for children 1–10, 70 under one year, 60 under one month |
| RF13 | Respiratory rate outside the age band — adult < 10 or > 30 |
| RF04 | Active seizure |
| RF05 | Airway compromise |
| RF06 | Uncontrolled haemorrhage |
| RF07 | Anaphylaxis |
| RF08 | Stroke signs within the 4.5-hour thrombolysis window |
| RF09 | Eclampsia |
| RF10 | Paediatric retractions under age 15 |

A fired rule forces priority 1 and **no model output can suppress it.**

### The gate has three answers, not two

| | |
|---|---|
| **Confirmed** | A rule fired on values someone actually recorded → priority 1 |
| **Cannot rule out** | Fires only because a missing vital was assumed worst-case → priority 2, plus an instruction to measure it |
| **Not evaluable** | The source has no such column at all → skipped |

The third matters more than it looks. No dataset here carries GCS, and gating
every patient on an assumed GCS of 3 would fire RF01 on all of them.

### When the system refuses to answer

| | |
|---|---|
| **RF11** — hard stop | Fewer than **3** of the monitored vitals recorded. No score is produced at all. You cannot triage a sentence |
| **RF12** — abstain | Two pathways engaged with ≥ 0.75 overlap at ≥ 0.5 severity. It says it cannot classify rather than manufacturing an answer |

Neither is a low-acuity finding. An unknown patient goes **ahead** of everyone
already cleared. Both route to a clinician and both are written to the audit log.

### Layer 1 — the acuity scorer · **recommends**

Gradient-boosted trees over ~23 fields available within five minutes of arrival.
Trained on 560,486 real Yale encounters.

**Two confidences, not one.** *Urgency* confidence comes from a conformal
prediction set with a ≥95% guarantee calculated per class. *Cause* confidence
comes from how much the three pathways overlap. A hypothermic trauma patient
scores urgency HIGH and cause LOW — we are certain they are critical and honest
that we cannot say which gate is closing. That patient needs a doctor now, not a
better score.

**The three pathways** — every acute presentation kills through the lungs, the
heart or the brain. Each is monitored by four or five parameters weighted by how
*specific* they are to that gate.

**Competing pathologies** — hypothermia plus shock is flagged as a *treatment
conflict*, because a vasopressor constricts already-constricted vessels and
drives necrosis. ATRIA does not choose the drug. It says the two conflict and
routes to a human.

**Never scores missingness as reassuring.** An audit found the model had learned
that a missing heart rate, respiratory rate or systolic *lowered* risk — a silent
undertriage path. Scores are now clamped so an unrecorded vital can never score
better than an average one.

### Layer 2 — the re-ranker · **re-orders**

Watches trajectory, not snapshots.

| Signal | Threshold |
|---|---|
| SpO₂ falling | ≥ 3% over the trailing window |
| Systolic falling | ≥ 15 |
| Heart rate rising | ≥ 20 |
| Respiratory rate rising | ≥ 6 |
| Shock index (HR/SBP) | ≥ 0.9 |

**Re-assessment is due at** 5 / 15 / 45 / 90 / 180 minutes for priorities 1–5.
Being overdue forces a re-look; it does **not** by itself raise the priority.
Waiting does not make a patient sicker. Only at 3× the safe wait does it escalate
by one, as a safety net.

**Safety bands are strict.** Operational pressure and waiting time reorder
patients *within* a band and can never move one across a boundary. A maximally
boosted priority 3 still ranks below an untouched priority 2, and a test proves
it.

### Layer 3 — human authority · **decides**

The blind cycle above, plus a hash-chained audit log. Each entry embeds the hash
of the one before it, so an edit or deletion anywhere breaks the chain and is
detectable. Corrections create a new linked event; nothing is ever rewritten.

The trail is durable. It is written to SQLite as it is appended and rebuilt from
disk on startup, so the chain a restart inherits is the chain an auditor would
read off the file — and the database refuses `UPDATE` and `DELETE` outright, so
tampering fails at the point of writing rather than being caught later by a
check nobody ran.

Every entry names a person who authenticated, not a query parameter the caller
chose for themselves, and every sign-off carries the version of the model that
recommended against them.

**No machine source can lower a priority.** Layer 0 escalates, Layer 1
escalates, Layer 2 escalates — none of them can relent. Only a clinician can, and
it is recorded with their identity, their reason code, the model version and the
input snapshot.

---

## Two bugs this testing found

**A patient could be taken through mid-decision.** The queue moved whoever was
highest priority, including the patient a nurse was part-way through assessing.
That destroyed the blind cycle in flight and made the record panel appear to
change under them. It reproduced on **12 of 12 shifts**.

A patient is now held in the queue from the moment the nurse commits to an ESI
until they sign off. The hold is narrow — everyone else still moves, and the
department still treats the same number of people.

**The reveal token was reusable.** It was checked but never spent, so the same
token worked twice, which made it a password rather than a one-time proof that
the nurse's answer was stored first. Revealing twice is now refused outright,
because the comparison is the record of what the nurse thought *before* seeing
ATRIA — recomputing it would let a second call quietly overwrite that, and the
audit entry beside it.

The earlier test only proved a token from a *previous cycle* was refused, which
is why this survived. Both are now covered.

---

## What has been measured

| | |
|---|---|
| Layer 1 | **AUC 0.809** on 560,486 real Yale encounters. The published benchmark is 0.87 — using the nurse's ESI and race, which we exclude |
| Operating point | 95.0% sensitivity, 34.1% specificity, 5.0% undertriage — tuned to the ACS ≤5% standard |
| Layer 2 on real patients | Flags **32.2%** of those later admitted against **12.2%** discharged home — a **+20.0 point** difference, 95% CI [+4.6, +31.2]. Median **164 minutes** of lead time, CI [111, 258] |
| Fairness | Worst-served group undertriaged at 9.2% against 4.0%; subgroup-conditional calibration takes the gap to **2.1%** out of sample, 95% CI [0.4, 4.3] — inside the 5-point tolerance |
| Soak test | 25 shifts, 434 patients treated, 565 full nurse workflows, **0 problems** |
| Test suite | **259 passing** |

---

## Before it could run anywhere real

Four things, all built, all described in [deployment.md](deployment.md): a
durable audit trail, accounts and roles, a frozen model artifact with a
manifest, and **shadow mode** — every layer runs and nothing acts, so a
department can measure how often ATRIA would have disagreed before it is
allowed to. A Layer 0 red flag is the one thing shadow mode still acts on;
withholding it would mean not acting on a measured SpO2 of 84% to keep an
experiment clean.

---

## What it deliberately does not do

- **No diagnosis.** It never suggests what is wrong with a patient.
- **No treatment.** It changes who is seen next, not what happens when they are.
- **No autonomous downgrade.** Every reduction in urgency is a human decision.
- **No silent failure.** Missing data, low confidence and degraded mode are shown
  on the face of the board rather than hidden behind a number.

## Limitations, stated plainly

- The outcome label is hospital **admission**, a coarser proxy for acuity than
  ICU-transfer-or-death. No open ED dataset carries ICU timestamps, which is
  checked rather than assumed: neither Yale nor the MIMIC demo has one. The
  sharpest available substitute — a time-critical diagnosis on the encounter —
  is measured and reported, and at 19 patients it cannot resolve the question.
  This is the strongest argument for credentialed access.
- Layer 2 is validated on **159 real trajectories**. Small, and reported that
  way: every rate carries an interval. The primary endpoint clears zero; the
  sharper critical-diagnosis endpoint does not, on 19 patients. That negative
  result is published rather than dropped.
- The fairness gap is **inside tolerance but not zero**: 2.1%, measured out of
  sample, CI [0.4, 4.3]. Four subgroups are too small to estimate their own rate
  to better than the tolerance; they are named rather than dropped.
- The three pathways are the classical triad, assumed. Round 1 names only
  "Cerebral Hypoxia".
- **Every threshold here is a prototype default.** None has been approved by a
  clinical governance body, and none should be used on a real patient.
