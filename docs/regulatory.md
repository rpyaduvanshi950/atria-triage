# Regulatory position

The brief asks us to name a jurisdiction. This is that answer, plus the four
questions that follow from it — raised in clinical review and answered here
rather than left for a judge to ask.

**Assumed jurisdiction: United States, HIPAA.** It matches the provenance of our
evaluation data (Yale, three Connecticut hospitals; MIMIC, Boston) and gives a
coherent frame for retention, consent, audit and override. Where the EU or
India's DPDP Act would differ materially, that is noted.

---

## 1. What kind of product is this?

**Software as a Medical Device (SaMD), and we should say so first rather than be
told.** Under the IMDRF framework and FDA's adoption of it, SaMD risk is a
function of two axes: the significance of the information provided, and the state
of the healthcare situation.

ATRIA sits at:

| Axis | Position | Why |
|---|---|---|
| Healthcare situation | **Critical** | Emergency department, time-critical deterioration |
| Information significance | **Drives clinical management** — not *treats or diagnoses* | It changes the order of attention; it never selects therapy |

That places it in the tier below the highest. The distinction is not cosmetic and
it is the single most important design decision in the system: **ATRIA orders a
queue, it does not diagnose or treat.** Everything else — no diagnosis output, no
treatment recommendation, no autonomous downgrade — exists to keep it there.

If the product ever emitted a diagnosis or a drug, it would move up a tier and
into a substantially heavier regulatory pathway. That boundary is worth defending
commercially, not only clinically.

## 2. Who is liable when it is wrong?

Clinical decision support that a clinician can review and override keeps the
clinician as the decision-maker. This is why the override path is not a
convenience feature — it is the mechanism that makes the liability position
coherent.

Three properties in the build exist for this:

- **No autonomous downgrade.** No model output can reduce a patient's priority.
  Only a licensed clinician can, and the interface makes that asymmetry visible
  at the moment of the decision.
- **Every decision is reconstructable.** The hash-chained log records the input
  snapshot, model and rule-table versions, the score, the conformal interval, the
  recommendation, the human decision and a structured reason code.
- **The system says when it does not know.** RF11 and RF12 hand the patient to a
  human rather than manufacturing a defensible-looking number. A system that
  always answers is a system that is always accountable for the answer.

**Open question for counsel:** whether a *failure to escalate* by an
advisory-only system creates exposure distinct from a nurse's own failure to
escalate. Our position is that shadow-mode deployment (Phase 1 of the roadmap)
establishes the baseline needed to answer this empirically.

## 3. How does an emergency patient consent?

The hardest of the four, and the one most often skipped.

An unconscious patient brought in by ambulance cannot consent to anything,
including to having their vitals processed by a decision-support system. US
practice relies on **implied consent / emergency exception** doctrine — treatment
necessary to prevent death or serious harm may proceed without express consent.
Good Samaritan statutes cover the bystander who brought them in, not the
hospital's software.

Our position:

- ATRIA processes data **already being collected** for clinical care. It creates
  no new collection and no new patient burden. This matters: the consent question
  is about the *processing*, not about taking a blood pressure that was going to
  be taken anyway.
- Under HIPAA, this is use for **treatment** within the covered entity, which
  does not require separate authorisation.
- **No secondary use.** Data does not leave the hospital, is not used to train a
  shared model, and is not sold. If model improvement across sites is ever wanted,
  that is a distinct consent conversation and should be federated rather than
  centralised.
- Retention follows the hospital's existing record schedule. The audit log is
  part of the medical record, not a separate product dataset.

**Under GDPR** the lawful basis would be Article 9(2)(c) — vital interests where
the patient is incapable of consent — with 9(2)(h) for the care relationship.
**Under India's DPDP Act 2023**, the equivalent is the medical-emergency ground.
Worth having read before answering in a Q&A; do not paraphrase from memory.

## 4. How would anyone come to trust it?

Clinical review was blunt: medical AI starts from a deficit of trust, and a nurse
will believe a trained colleague over a model. Three mechanisms, in order of
cost:

1. **Shadow mode first.** Phase 1 runs beside triage, recommends nothing, logs
   everything. It measures agreement with nurse decisions and would-be lead time
   without touching care. This is also the dataset that answers the liability
   question above.
2. **Clinician-led validation.** Sensitivity and specificity studies run by the
   clinicians who would use it, in small sites before large ones. Trust
   propagates through professional networks, not through marketing.
3. **Regulatory clearance as a seal.** An FDA pathway — most plausibly 510(k)
   against an existing triage-support predicate — converts an internal claim into
   an external one. Expensive and slow, and the right sequencing is after 1 and 2.

## 5. Discrimination and bias

A specific question was raised in review: is there racial or disability bias in
the model?

**What we have done.** The fairness audit (`eval/fairness.py`) measures
sensitivity and false-alarm rate per subgroup, reports equalised-odds gaps, and
mitigates with subgroup-conditional conformal calibration. It found geriatric
patients being undertriaged at 18.1% and closed the gap to 0.6%.

**What we have not done, and must say so.** Race is not currently audited,
because the dataset the model trains on today does not carry it. Yale does —
`race`, `ethnicity`, `lang` and `insurance_status` — and the audit code already
reads those columns when present. Until the Yale extraction is run, our fairness
claim covers **sex and age band only**, and the deck must say that rather than
imply a completed audit.

**Design choices that reduce exposure:**

- No protected attribute is a model input. Age is, because age-specific
  physiology is clinically mandatory — a systolic of 88 is shock in an adult and
  normal in a three-year-old — and omitting it would itself be a safety defect.
- Layer 0, which alone can force band 1, is deterministic and inspectable. It
  cannot learn a proxy.
- The Obermeyer failure mode — using cost or utilisation as a proxy for need —
  is structurally excluded: our label is a clinical outcome, never a spend or
  resource-use measure.

---

## Assumptions, stated in one place

| | |
|---|---|
| Jurisdiction | United States, HIPAA |
| Device class | SaMD, drives clinical management; not diagnosis or treatment |
| Deployment | Within a single covered entity; no data egress |
| Consent | Implied/emergency exception; treatment use under HIPAA |
| Decision-maker | The licensed clinician, always |
| Outcome label | Hospital admission — a proxy for acuity, not ICU-or-death |
| Fairness coverage | Sex and age band today; race and language once Yale is extracted |

None of the above is legal advice, and the EU AI Act's treatment of emergency
triage software should be checked against current article and annex text before
being cited on a slide.
