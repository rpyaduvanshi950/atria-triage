# ATRIA — Product-Level Prototype Build Plan

Companion to `README.md` (product summary) and `ATRIA_Data_to_Product_Plan.md`
(dataset mapping). This document is the engineering execution plan: what to
build, in what order, with what stack, so the static `ATRIA_Intuitive_Flow_
Deterioration_UI.html` becomes a real, testable, API-backed system that
satisfies the PRD's "Definition of done" (§21.1).

**Definition of "product-level prototype" for this project:**
a system where the frontend has no embedded clinical state, every clinical
decision is computed by a real backend service, every decision is
reconstructable from an immutable audit trail, and all PRD acceptance
scenarios (§21) pass in CI against synthetic data — *without* claiming
regulatory clearance or real-patient readiness.

---

## 1. Target architecture

This diagram now carries all **nine** service boundaries from PRD §16.1 —
the previous version folded three of them away; see the note at the end of
this section.

```
┌─────────────────────────────┐
│  Frontend (existing HTML/JS │
│  UI, incrementally rewired  │
│  to call real APIs)         │
└───────────────┬─────────────┘
                │ REST + SSE/WebSocket
┌───────────────▼───────────────────────────────────────────────┐
│  Assessment Orchestrator                                       │
│  - creates snapshots, sequences guardrail → model               │
│  - enforces blind-reveal state server-side                     │
└───────────────┬─────────────────────────────────────────────────┘
        ┌────────┼────────┬──────────┬───────────┬────────────┬──────────┐
        ▼        ▼        ▼          ▼           ▼            ▼          ▼
   Clinical   Guardrail Inference   Queue     Reassessment  Flow       Audit
   Data       Service   Service     Service   Scheduler     Forecast   Service
   Gateway    (Layer 0) (Layer 1)   (Layer 2)               Service    (append-
        │                                                              only)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Integration Adapters                                            │
│  FHIR/HL7 records · vital-device feeds · beds · staff roster     │
└─────────────────────────────────────────────────────────────────┘

   Data stores: Postgres (relational: patients, encounters, snapshots,
   assessments, queue, audit) + Redis (live queue cache, pub/sub for SSE)
```

Everything above the data-stores line is stateless and horizontally
scalable; state lives only in Postgres (durable) and Redis (ephemeral/derived).

**Note on the earlier version of this doc:** it folded the Clinical Data
Gateway into the orchestrator and dropped the Flow Forecast Service and
Integration Adapters entirely. PRD §16.1 lists all nine as distinct service
boundaries, so they're now first-class here and in the repo layout below —
even though a few of them can be thin wrappers in the prototype, keeping the
boundary explicit is what lets each one be replaced or hardened later
without touching the others.

---

## 2. Stack recommendation (prototype-appropriate, not final)

| Layer | Choice | Why |
|---|---|---|
| Backend language/framework | **Python (FastAPI)** or **Node (NestJS)** | Both have first-class async, OpenAPI generation for free, and match the PRD's JSON-contract-first approach. Pick Python if the ML team owns Layer 1 in the same repo (avoids a cross-language model-serving hop). |
| Database | **PostgreSQL** | Relational integrity for append-only audit + immutable snapshots; JSONB columns for flexible reason-code/rationale payloads. |
| Live updates | **Redis pub/sub → SSE** | Simplest path to the PRD's full §16.3 event set — `queue.updated`, `assessment.recommendation_ready`, `patient.reassessment_due`, `patient.worsening_reported`, `patient.guardrail_triggered`, `operations.snapshot_updated`, `audit.override_created` — without standing up a message broker yet. Every event carries a monotonically increasing stream version and must be safely re-derivable from a GET of the latest snapshot after a client disconnect (§16.3). |
| ML serving | **FastAPI microservice wrapping a scikit-learn/XGBoost model**, versioned artifacts in a local model registry (even just a `models/` dir with a manifest) | Matches PRD §14 model-agnostic contract; swappable later. See §2a below for what this actually means. |
| Frontend | Keep the existing HTML/CSS/JS shell; introduce a thin `api.js` fetch layer | Preserves the interaction design the PRD explicitly protects (§5) while removing embedded state. Migrate to a framework only if the team already prefers one — not required for the prototype. |
| Auth | Simple JWT/session auth with role claims (nurse, charge nurse, clinician, ops, admin, auditor) | Matches SEC-002/003; doesn't need to be enterprise SSO yet. |
| Testing | **pytest** (backend, incl. Layer 0 boundary tests), **Playwright** (frontend E2E against the acceptance scenarios) | Both support the deterministic fixture-replay approach PRD §19 asks for. |
| Infra | Docker Compose locally (`api`, `db`, `redis`, `ml-service`, `web`) | Matches "definition of done": a developer can run it locally with seed data, no production credentials. |

---

## 2a. What "ML serving" actually means here

"ML serving" is just the **Inference Service** (Layer 1) from the
architecture diagram — the piece of infrastructure whose only job is: take a
validated clinical snapshot in, return calibrated ESI probabilities out, as
fast as possible, without ever touching a database or making a clinical
decision itself.

Concretely, it's:

1. **A trained model artifact** — the gradient-boosted-trees/ordinal model from Phase 3, saved to disk (e.g. `model.pkl` or `model.json`) alongside a `manifest.json` recording `model_version`, training data hash, calibration parameters, and the feature schema it expects.
2. **A thin HTTP wrapper around it** — a FastAPI (or similar) service with basically one endpoint: `POST /predict` that takes the feature vector built from a `ClinicalSnapshot`, runs `model.predict_proba()`, and returns the exact payload shape from PRD §10.2 (`probabilities`, `recommended_esi`, `confidence`, `reason_codes`, `model_version`).
3. **Abstention logic living in this same service** — before returning a normal prediction, it checks: is confidence below threshold (ML-003)? Is the input out-of-distribution or schema-mismatched (ML-004)? If either is true, it returns `status: ABSTAIN` instead of a probability distribution — it never silently guesses.
4. **Nothing else.** It doesn't decide whether to run (that's the orchestrator's job, only after Layer 0 says "continue"). It doesn't store anything (the orchestrator persists the `AtriaAssessment`). It doesn't know about the nurse's ESI, the queue, or reveal timing. This narrowness is what makes ML-005 possible — "confidence can never soften a Layer 0 critical result" is trivially true if the inference service is never even called for a critical snapshot.

Why a *separate* service instead of a function inside the main API: it has a
different scaling profile (may need a GPU or heavier CPU later, benefits
from batching), a different deploy cadence (model updates shouldn't require
redeploying the whole API), and PRD ML-004/§20.4 want model version and
input/prediction drift monitored independently — easiest when it's a
distinct, traceable hop in the request path with its own logs and its own
`model_version` tag on every response.

In the local dev setup this is just one more container: `docker compose up
inference-service` — no different in kind from the guardrail service, just
with a model file mounted in instead of a rules YAML.

---

## 3. Repository layout

All nine PRD §16.1 service boundaries now map one-to-one onto a folder:

| PRD §16.1 service | Repo folder |
|---|---|
| Clinical data gateway | `apps/clinical-data-gateway/` |
| Guardrail service | `apps/guardrail-service/` |
| Inference service | `apps/inference-service/` |
| Assessment orchestrator | `apps/api/` |
| Queue service | `apps/queue-service/` |
| Reassessment scheduler | `apps/reassessment-scheduler/` |
| Flow forecast service | `apps/flow-forecast-service/` |
| Audit service | `apps/audit-service/` |
| Integration adapters | `apps/integration-adapters/` |

```
atria/
├── apps/
│   ├── clinical-data-gateway/  # normalize/validate patient, encounter, vital, record data; provenance
│   ├── api/                    # Assessment orchestrator + REST/SSE endpoints
│   ├── guardrail-service/      # Layer 0 — pure functions, no DB dependency
│   ├── inference-service/      # Layer 1 — model serving (see §2a)
│   ├── queue-service/          # Layer 2 — banding + ranking
│   ├── reassessment-scheduler/
│   ├── flow-forecast-service/  # PRD §13 — waiting/treatment projection vs staffed spaces
│   ├── audit-service/          # append-only decision/access event store
│   ├── integration-adapters/   # FHIR/HL7 records, vital devices, beds, staff roster
│   └── web/                    # existing HTML/JS, rewired to call apps/api
├── data/
│   ├── yale/                 # extraction scripts + slim CSV (see data plan doc)
│   ├── isfahan/
│   ├── mimic_ed_demo/
│   └── synthetic/            # generator + fixture pack (PRD Appendix B cases)
├── ml/
│   ├── training/              # feature pipeline, training scripts
│   ├── evaluation/            # PRD §20.2 evaluation matrix implementation
│   └── models/                # versioned artifacts + manifest.json
├── config/
│   ├── guardrail-ruleset.yaml # Layer 0 thresholds, versioned (Appendix A)
│   ├── reassessment-intervals.yaml
│   └── esi-nomenclature.yaml
├── tests/
│   ├── unit/                  # boundary tests (SAF-001..008, ML-001..006)
│   ├── integration/           # full snapshot → guardrail → model → queue flow
│   └── acceptance/            # PRD §21 scenarios, one test per row
├── docker-compose.yml
└── README.md
```

Keeping `guardrail-service` dependency-free (no DB, no network) is deliberate:
it should be trivially unit-testable and independently deployable, per the
PRD's "learned model must never suppress Layer 0" invariant.

---

## 4. Build phases (maps to PRD §22 delivery plan)

### Phase 0 — Contract freeze (before any code)
- [ ] Finalize JSON schemas for `ClinicalSnapshot`, `AtriaAssessment`, `NurseAssessment`, `QueueEntry`, `ReassessmentTask`, `OverrideEvent`, audit event (PRD §15, Appendix C).
- [ ] Version and check in `guardrail-ruleset.yaml` (SpO₂, SBP-by-age, RR bounds, GCS, etc. — Appendix A values as v0.1.0, pending clinical sign-off).
- [ ] Freeze the recommendation response payload shape (PRD §10.2) as an OpenAPI schema.
- [ ] Get a named clinical reviewer (even informal, for the prototype) to sign off on ESI nomenclature and reassessment intervals before Phase 1 starts.

### Phase 1 — Deterministic core
- [ ] Implement Layer 0 as pure functions: `evaluate_guardrails(snapshot) -> {critical|uncertain|continue, reason_codes[]}`.
- [ ] Implement the missing-essential-vital abstention rule as its own explicit branch (never a fallthrough).
- [ ] Age-aware vital interpretation (pediatric SBP formula, HR/RR bands from §9.2).
- [ ] Unit tests for every boundary in SAF-001–008 (89.9/90.0 SpO₂, ages 3/14/15/75, RR 9/10/30/31).
- [ ] Validate against Yale + MIMIC vitals as a real-data sanity fixture (see dataset plan §3 — don't train yet, just confirm the rule fires where `esi==1` rows suggest it should).
- **Exit criterion:** 100% of Layer 0 unit tests pass; guardrail service runs standalone with zero external dependencies.

### Phase 2 — Queue, record and workflow
- [ ] `POST /v1/encounters`, `/observations`, `/nurse-assessments`, `/reveal`, `/finalize`, `/override`, `/worsening` (PRD §16.2).
- [ ] Server-side enforcement of blind reveal: the recommendation must not exist in any API response reachable before the nurse's ESI is submitted (ASS-002 acceptance = automated DOM/response test finds nothing).
- [ ] Safety-band sorting (Critical > Diagnostic Uncertainty > ESI 2–5) with within-band modifiers (§11.2) and the invariant test that modifiers can never cross a band boundary (QUE-005).
- [ ] Reassessment scheduler: due-time computation, `recheck_due` flag, "Report change" clearing prior sign-off, **and configurable-grace-period escalation to the charge nurse with an audited acknowledgement event for overdue rechecks (REA-008)** — this was missing from the original scope and is a distinct requirement from the due-time/flag logic above.
- [ ] Rewire `apps/web` to call these APIs instead of using embedded patient objects; keep every existing visual/interaction state (nurse-first, compared-match, compared-escalation, etc.) but drive it from real API responses.
- **Exit criterion:** full synthetic workflow (check-in → vitals → blind ESI → reveal → sign-off → queue reorder) passes end-to-end against the running services, not mocks.

### Phase 3 — Model baseline
- [ ] Feature pipeline from Yale slim CSV per the column mapping in `ATRIA_Data_to_Product_Plan.md` §3. **Exclude race, ethnicity, language, and insurance from the trained feature set** — PRD §14.3 prohibits protected attributes as model inputs absent an approved clinical rationale and fairness review, and §14.2 explicitly calls out race/ethnicity as a disallowed predictive shortcut. Also exclude current bed availability, nurse count, flow state, and any post-triage/outcome fields (§14.3).
- [ ] Train an interpretable baseline (gradient-boosted trees or ordinal model), site-holdout by `dep_name`, asymmetric-loss for undertriage.
- [ ] Calibration + abstention wiring (ML-001–006): out-of-distribution check, low-confidence threshold (start at 0.70, configurable).
- [ ] Reason-code templating: model outputs map to a fixed vocabulary, never free text (§14.5).
- [ ] Evaluation report against PRD §20.2 matrix: ESI-1/2 recall, undertriage rate, calibration (reliability curve + ECE), subgroup parity computed **post hoc, from held-out labels only** using Yale's age-band/sex/language/site fields (§20.2's named fairness groups) — race/ethnicity/insurance may be added to this eval-only slice if the fairness reviewer approves it, but never feed back into training.
- **Exit criterion:** frozen model artifact + evaluation report; release gates from §20.3 checked off (even if thresholds are provisional pending clinical review).

**Failure-mode note carried over from Phase 1/3 (PRD §19.1):** guardrail-service and inference-service outages are *not* symmetric and the orchestrator must treat them differently —
- **Guardrail service down → fail closed.** The orchestrator must refuse to produce any ATRIA recommendation and surface "safety service unavailable"; it must not fall through to the model or a default ESI. This should be enforced in Phase 1/2 as an explicit orchestrator branch, not left implicit.
- **Inference service down → fail open on the model only.** Layer 0 still runs and can still force ESI 1/abstention; ATRIA shows "Recommendation unavailable" and the nurse proceeds with an audited manual sign-off. The model being unreachable must never block triage.
This distinction should be captured as its own test (`test_guardrail_service_down` in addition to the existing `test_model_unavailable`) since the two failure paths currently collapse into one test name in §5 below.

### Phase 4 — Operations & Flow
- [ ] Operational snapshot aggregation (waiting, inside, nurses, staffed spaces, arrival rate).
- [ ] 5-point forecast (now, +15/30/45/60m), capped treatment line, uncapped waiting line (§13).
- [ ] Bounded operational modifier wired into the queue service, with the invariant test proving it can't cross an ESI band (OPS-007).
- [ ] Degraded-mode behavior for each integration (records/beds/roster/vitals disconnection) per §17.
- **Exit criterion:** forecast is reproducible from a stored input snapshot and explainable in one sentence (OPS-005).

### Phase 5 — Shadow validation
- [ ] Stand up one real or sandbox integration (FHIR sandbox or a synthetic device feed) end-to-end through the clinical data gateway.
- [ ] Run the system in shadow mode: real or replayed nurse decisions flow through, ATRIA's recommendation is logged but never acted on.
- [ ] Full observability: distributed trace from ingestion → guardrail → model → queue, PHI-safe logging.
- [ ] Usability pass on an 11" tablet against the human-factors requirements (§5.3, §5.2).
- **Exit criterion:** go/no-go review package assembled — this is the gate before anything touches a real patient, and that decision sits with clinical governance, not engineering.

---

## 5. Acceptance testing strategy

Turn PRD §21's acceptance-scenario table directly into a test suite —
one test per row, named after the scenario (`test_pediatric_control`,
`test_older_adult_same_vitals`, `test_missing_essential_data`,
`test_low_oxygen`, `test_adult_rr_boundary`, `test_sepsis_trajectory`,
`test_five_hour_safeguard`, `test_blind_assessment`, `test_match`,
`test_nurse_escalation`, `test_nurse_downgrade`, `test_guardrail_override`,
`test_vitals_due`, `test_worsening_while_waiting`, `test_capacity_full`,
`test_roster_disconnected`, `test_model_unavailable`, `test_guardrail_service_down`,
`test_history_ordering`).

Each test should assert against the **actual API/DB state**, not just UI
rendering — e.g. `test_blind_assessment` should confirm the recommendation
field is genuinely absent from the API response, not merely hidden by CSS.

Feed these from the synthetic fixture pack (PRD Appendix B: Pediatric
Control, Arthur Hale, John Doe, Meera Shah, Aarav Kumar) plus any Isfahan-
informed synthetic pediatric/rare-critical cases from the generator.

---

## 6. What changes in the existing HTML file

The current `ATRIA_Intuitive_Flow_Deterioration_UI.html` is a strong reference
for interaction design and should **not** be thrown away — per the PRD's
source hierarchy, it's authoritative for visual intent. The migration is:

1. Extract the hardcoded patient array into `data/synthetic/fixtures.json`, served via `/v1/encounters` in dev/demo mode.
2. Replace direct state mutation (e.g. clicking an ESI button) with a `fetch()` call to `/v1/encounters/{id}/nurse-assessments`, which per PRD §16.2 returns a `reveal token` alongside the stored nurse assessment; the frontend's second call to `/reveal` must pass that token. This makes the ordering a server-enforced invariant (no token exists until a nurse assessment is durably stored) rather than something the frontend merely happens to call in the right sequence.
3. Replace the queue array with a subscription to `/v1/queue` (initial GET) + SSE updates on `queue.updated`.
4. Keep every CSS state (`.critical`, `.uncertain`, `.match`, etc.) — just drive the class assignment from API response fields instead of local variables.
5. Add a visible "SIMULATION" vs "LIVE" mode indicator at the top ribbon (already partially present) so simulation data can never be mistaken for a production read, per INT-008.

---

## 7. Environment & local dev setup

```bash
git clone <repo>
cd atria
cp .env.example .env          # DB creds, JWT secret — never production values
docker compose up -d db redis
make extract-yale              # see ATRIA_Data_to_Product_Plan.md §5
make seed-synthetic             # loads PRD Appendix B fixtures + generator output
docker compose up api guardrail-service inference-service queue-service web
```

A developer should be able to reach a working nurse-first assessment screen
within one `docker compose up`, using only synthetic data and no production
credentials — this is the literal "definition of done" bar from PRD §21.1.

---

## 8. Immediate next 3 tasks

1. Freeze the five core JSON schemas (Phase 0) and check them in as `config/schemas/*.json` — this unblocks both backend and frontend work in parallel.
2. Implement and unit-test the Layer 0 guardrail service in isolation (Phase 1) — it has zero dependencies and is the fastest way to get CI green and build momentum.
3. Rewire the "check in one" → nurse assessment → ESI picker flow in the existing HTML to call a stub `apps/api` (even before the real guardrail/model logic exists) — this proves the frontend/backend seam works before deeper logic is added.
