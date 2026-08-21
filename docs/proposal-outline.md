# Business proposal — outline

Round 2 asks for problem framing, solution design, target users, business case
and impact, a phased roadmap, and key risks with mitigations. One section each,
in that order, so a judge can find what they are scoring.

## 1. Problem framing
- Triage is a one-time snapshot on a patient who is still changing.
- Evidence already on the deck: 32.2% mistriage / 65.9% sensitivity (Sax 2023);
  1 in 82 at 6–8h (Jones 2022); +1.8%/hr in septic shock (Liu 2017); 12.7% silent
  MI (Björck 2018).
- The design question: not "who is sickest now?" but "who is becoming sickest
  while nobody is looking?"

## 2. Solution design
- The four layers, and the decide-vs-recommend split already on the deck.
- **The invariant**, stated as code: machines escalate, only clinicians relent.
- Where ATRIA sits: beside the triage nurse, changing order of attention, never
  clinical treatment.

## 3. Target users
- Primary: the triage nurse, mid-shift, managing several patients at once.
- Secondary: the charge nurse (surge view), the clinical governance lead (audit).
- Explicitly not: physicians making treatment decisions.

## 4. Evidence and impact
- Results table: ATRIA vs the published Hong et al. baseline and vs ESI.
- The fairness audit, before and after mitigation.
- **The Isfahan leakage finding** — a trap detected and stepped around.
- Lead time on escalations, measured on real MIMIC trajectories.

## 5. Phased roadmap
- Phase 1 — shadow mode: runs beside triage, recommends nothing, logs everything.
  Measures agreement and would-be lead time without touching care.
- Phase 2 — advisory: recommendations surfaced, every action a nurse decision.
- Phase 3 — integrated: writes priority to the EHR track board.
- Each phase gated on a stated metric, not a date.

## 6. Risks and mitigations
- Alert fatigue → tuned operating point, cost curve shown, not just a threshold.
- Automation bias → the interface shows uncertainty and missing fields by default.
- Calibration drift across sites → per-site recalibration, monitored.
- Liability → hash-chained audit log; clinician authority absolute.

## 7. Assumptions and limitations — one findable place
- Outcome label is admission, a proxy for acuity, not ICU-transfer-or-death.
- Layer 2 validated on 159 real trajectories plus calibrated synthetic.
- Paediatric cases are synthetic; the adult sources cannot supply them.
- Jurisdiction assumed: HIPAA (US), matching the data's provenance.

## 8. Attribution
Required by licence, not courtesy: Hong et al. 2018 (Yale), Data in Brief 2024
(Isfahan, CC BY 4.0), MIMIC-IV-ED Demo (ODbL v1.0). See `data/README.md`.
