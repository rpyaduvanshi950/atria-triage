# Pitch pack

Slide content and Q&A prep, built from `docs/results.md`. Every number here is
measured — regenerate with `make report` and these figures update with it.

---

## Deck fixes

**Remove.** The problem-statement slide appears twice, long and short. Keep the
short one; give the freed slide to Results.

**Fill.** The video frame is still an empty placeholder.

**Keep untouched.** The evidence slide with Sax / Jones / Liu / Björck is strong
and well sourced.

---

## New slide 1 — Results

> ### We score below the published benchmark. On purpose.

| model | features | AUC |
|---|---|---|
| Hong et al. 2018, triage variables only | ~90 | 0.87 |
| **ATRIA**, PRD-compliant | **23** | **0.809** |
| Hong et al. 2018, full model with history | 972 | 0.92 |

560,486 real ED encounters, three hospitals, Yale 2014–2017.

**The benchmark uses two inputs we refuse.** It reads the nurse's own ESI level,
and it uses race as a predictor. Adding the nurse's ESI back would put us at
0.859 — near the published number — and we do not, for the reason on the next
slide.

**Operating point: 95.0% sensitivity, 34.1% specificity, 5.0% undertriage** —
tuned to the American College of Surgeons ≤5% standard, not to accuracy.
Specificity is the price and we report it.

**Say out loud:** our label is hospital *admission*, not ICU-transfer-or-death.
It is a coarser proxy for acuity. No open ED dataset carries ICU timestamps; it
is the first thing we would fix with real hospital access.

**Say out loud:** our label is hospital *admission*, not ICU-transfer-or-death.
It is a coarser proxy for acuity. A true critical-outcome label needs ICU
timestamps, which no open ED dataset provides, and it is the first thing we would
fix with real hospital access.

---

## New slide 2 — What independence costs

> ### 0.859 if we read the nurse's answer. 0.809 if we don't.

The same model, the same 560,486 patients, one input different.

**That 0.05 is the price of being able to disagree.** A model that reads the
nurse's ESI cannot meaningfully contradict it — it has already been told the
answer. So the comparison that follows would be theatre, and the blind
assessment built on it would be worthless.

We pay the 0.05 and keep the disagreement real.

The same logic bars race. It lifts accuracy and it is a social construct
standing in for exposure and access — using it as a predictor is precisely how
Obermeyer et al. (2019) describes algorithms encoding inequity. Race is audited,
never predicted from.

**This is the slide that separates a prototype from a product.** Anyone can
optimise an AUC. Choosing to give up 0.05 of it, and being able to say exactly
what you bought with it, is a different claim.

---

## New slide 3 — Blind nurse-first assessment

> ### The nurse decides first. Only then does ATRIA speak.

ATRIA's recommendation is not on the screen until the nurse has committed to an
ESI — absent from the payload, not merely hidden, so it cannot leak through the
DOM or a network tab.

**Why:** show a clinician a number first and they converge on it. Automation
bias is not a failure of diligence; it is how attention works under load. This
is the cheapest known defence against it.

**Second benefit:** every encounter now produces an independent human label.
That is the only way to measure whether the model is adding anything at all.

| outcome | reason required |
|---|---|
| match | no |
| nurse **more** urgent | no — logged, nurse's view stands |
| nurse **less** urgent | **yes**, before sign-off |
| guardrail active | **yes**, plus charge-nurse escalation |
| ATRIA abstained | **yes**, if signing off before the gap is resolved |

Reporting a change clears the sign-off and starts a fresh blind cycle. The old
recommendation is discarded, not carried over.

---

## New slide 4 — The invariant

> ### It may escalate on its own. It may never de-escalate on its own.

```python
if source is HUMAN:
    return proposed          # nurse authority is absolute
return min(current, proposed) # machines escalate, never relent
```

Five lines, in `layer2/ratchet.py`. `tests/test_ratchet.py` proves no machine
source can suppress a red flag, under any order of proposals.

This is not a policy in a document. It is a function every priority change passes
through, with a test that fails if it is ever violated.

---

## New slide 5 — We found a racial disparity in our own model

> ### "Other" patients undertriaged at 9.2%. White patients at 4.0%.

At the operating point, on real race data, in our own model. Measured, not
assumed.

| | sensitivity | undertriage |
|---|---|---|
| White or Caucasian | 96.0% | 4.0% |
| Black or African American | 94.8% | 5.3% |
| Asian | 93.7% | 6.3% |
| **Other** | **90.8%** | **9.2%** |

**Removing race from the model narrowed the gap on its own** — from 8.3
percentage points to 5.2 — before any mitigation was applied. A protected
attribute does not have to be used maliciously to do harm; it is enough for the
model to learn that one group is admitted less often and act on it.

**Then we mitigated.** Subgroup-conditional conformal calibration — Mondrian
conformal takes an arbitrary taxonomy, so calibrating on class × subgroup gives
each group its own coverage guarantee instead of a shared average that hides
the worst-served group inside it.

**TPR gap 9.2% → 5.0%.** Every group brought to ~95% sensitivity.

Obermeyer et al. (2019) is on our problem slide as a warning. This is the same
warning, found in our own system, and closed.

**Two honest caveats.** The gap is narrowed, not eliminated — 5.0% is above our
own 5-point tolerance. And the age finding *reversed* between synthetic and real
data, so fairness results do not transfer between datasets. That is itself the
argument for auditing on the data you deploy against.

---

## New slide 6 — Three traps we caught

> ### Most teams show a model that worked.

**A dataset that encoded its own answer.** In 143,140 real Iranian ED records,
100% of the most-urgent patients had zero recorded vitals, against 0.1% of the
mid-urgency band — the sickest bypass the triage form entirely. A model using
missing-indicators would have scored beautifully by learning hospital paperwork.
Excluded from training.

**A model that learned missing vitals are reassuring.** Blanking heart rate,
respiratory rate or systolic *lowered* predicted risk. A silent undertriage path,
in a system that promises the opposite. Found by auditing, not assuming; now
clamped so an unrecorded vital can never score better than an average one.

**Our own gate, adult-calibrated.** It fired hypotension on a 3-year-old with a
systolic of 88, which is normal at that age — precisely the failure the brief
names. Thresholds are now age-banded on PALS.

---

## Supporting numbers, if asked

| | |
|---|---|
| Cross-site | Train on two hospitals, test on the third: unseen AUC within ±0.026. Holding out B scores *higher* than either training site |
| Layer 2 on real trajectories | 32.2% of later-admitted flagged vs 12.2% of discharged, median **164 minutes** before their last recorded reading (159 MIMIC stays) |
| Conformal coverage | ≥95% **per class**, calibrated on held-out data |
| Latency | p95 **52 ms** under 3× surge, against a 400 ms budget |
| Abstention under surge | 3× volume drives missingness 18% → 34%; abstentions rise with it |

---

## Q&A prep

**"Why not just tune ESI?"**
ESI is a five-level ordinal label assigned once, at the door. You cannot tune a
snapshot into a trajectory. Our Layer 2 result is the answer: 164 minutes of
median lead time on patients whose ESI never changed because nobody re-checked
them. The problem is not that the scale is badly calibrated — it is that it is
evaluated once on a patient who keeps changing.

**"Admission isn't the same as critical. Why should we believe this?"**
You shouldn't, entirely, and we say so on the slide. Admission is a coarse
acuity proxy — plenty of admitted patients are not critical and some discharged
ones were. It is what the open data supports, and it is what the published
benchmark predicts, so the comparison is like-for-like. With ICU-transfer
timestamps we would use in-hospital mortality or ICU transfer within 12 hours,
which is the definition the MIMIC benchmark uses.

**"What does a false alarm cost the nurse?"**
Attention, which is the scarcest thing in the department. At our operating point
specificity is 52.1%, so roughly half of non-admitted patients get flagged. We
chose that deliberately: the cost curve is on the slide with our chosen point
marked. A false positive costs minutes; a false negative costs a life. We also
did the two things that make the alarm rate survivable — abstention rather than
guessing, and a board that shows *why*, so an alarm is a reason and not a noise.

**"How do you know it generalises past these hospitals?"**
Within the data: train on two sites, test on the third — AUC holds within
±0.026, and one holdout scores higher than its training sites. Beyond the data:
we don't, and the roadmap says so. Phase 1 is shadow mode, which measures
agreement and would-be lead time on a new site's own patients before touching
care.

**"What happens when it's wrong?"**
Every recommendation is reviewable and overridable, and no model output can
lower a patient's priority. Every decision appends to a hash-chained log
carrying the inputs, the score, the conformal interval, the model version and
the clinician's reason code — edits and deletions both detectable. The clinician
remains the decision-maker, which is what keeps the liability position coherent.
See `docs/regulatory.md`.

**"Is this a medical device?"**
Yes — software as a medical device, in the tier that *drives clinical
management* rather than diagnosing or treating. It changes the order of
attention, never the therapy. That boundary is deliberate and it is why we emit
no diagnosis and no treatment recommendation. Crossing it moves us up a tier and
into a much heavier regulatory pathway.

**"Did you train on real patients?"**
Layer 1, yes — 560,486 Yale encounters. Layer 2 is rule-based and evaluated on
159 real MIMIC trajectories. The patients on the demo board are synthetic,
generated from distributions fitted to 143,140 real Iranian records, because the
paediatric, surge and deterioration cases no open snapshot dataset carries.

**"Your AUC is below the paper's. Why?"**
Deliberately. The published model reads the nurse's own ESI level and uses race
as a predictor. We exclude both, which costs about 0.05 AUC. A model that has
already been told the nurse's answer cannot disagree with it, so the blind
comparison — the entire point of the workflow — would be meaningless. We would
rather have a weaker model that can genuinely contradict a nurse than a stronger
one that cannot.

**"Doesn't hiding the recommendation slow the nurse down?"**
It adds one tap. What it removes is anchoring: the nurse's ESI is now an
independent judgement rather than a reaction to ours. That matters twice — it
protects the patient from a confidently wrong model, and it gives us the only
clean signal we have for whether the model is worth anything. The decision
window is 75–135 seconds depending on acuity, load and age, and it is
deliberately non-numeric, because a visible countdown turns a clinical judgement
into a race.

**"Why should a nurse trust it?"**
They shouldn't yet, and pretending otherwise is how these systems fail. Phase 1
is shadow mode: it recommends nothing and logs everything, measuring agreement
against the nurses' own decisions. That is also the evidence base for clinician-
led validation, and only then a regulatory clearance. Trust propagates through
professional networks, not marketing.
