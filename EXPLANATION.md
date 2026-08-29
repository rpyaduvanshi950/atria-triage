# ATRIA — What Has Been Done & What Has Not

> **Project:** Accenture Innovation Challenge 2026, Round 2, Track 2 (PatientTriage.ai)
> **Team:** Digital Ninja — Pushpender, Shagun, Atit · IIT Kanpur
> **Date:** 2026-08-29

---

## TL;DR

ATRIA is **substantially built**. The four-layer clinical engine, three frontends, evaluation framework, test suite, and documentation are all functional. What remains is the transition from a **prototype with embedded state** to a **production-grade, API-backed system** as described in the Build Plan — specifically, the microservice decomposition (the 9-service architecture from PRD §16.1) and the Postgres/Redis data persistence layer have not been implemented.

---

## 1. What Has Been Done ✅

### 1.1 Core Engine (~3,500 lines of Python)

| Component | Files | Status | Notes |
|---|---|---|---|
| **Layer 0 — Deterministic Red-Flag Gate** | `layer0/engine.py`, `layer0/rules.yaml` | ✅ Complete | 11 cited rules, age-banded thresholds (PALS), three outcomes (confirmed/cannot-rule-out/not-evaluable). Missing-vital assumed-worst logic implemented. |
| **Layer 1 — Acuity Scorer** | `layer1/model.py`, `features.py`, `conformal.py`, `pathways.py`, `interactions.py`, `explain.py`, `verify.py` | ✅ Complete | Gradient-boosted-trees model. AUC 0.809 on 560K Yale encounters. Conformal prediction with ≥95% per-class coverage. Three "atria mortis" pathways (lungs/heart/brain). Race excluded from features, nurse ESI excluded. Abstention logic for low-confidence/OOD. |
| **Layer 2 — Dynamic Re-ranking** | `layer2/ranking.py`, `trajectory.py`, `ratchet.py` | ✅ Complete | Safety-band sorting (critical > diagnostic uncertainty > ESI 2-5). Within-band modifiers from vital trajectories. Ratchet invariant: modifiers can never cross a band boundary. Queue-aging with overdue detection. |
| **Layer 3 — Blind Workflow & Audit** | `layer3/workflow.py`, `audit.py` | ✅ Complete | Nurse-first blind assessment (recommendation absent from payload, not just hidden). Three-stage workflow (assess → compare → sign-off). Hash-chained append-only audit log. Report-change clears sign-off and starts fresh blind cycle. |

### 1.2 Data Pipeline

| Source | Status | Notes |
|---|---|---|
| **Yale ED — 560,486 visits** | ✅ Loader built | `data/loaders/yale.py`. Trains Layer 1. Extraction script in R. |
| **MIMIC-IV-ED Demo — 222 stays** | ✅ Loader built | `data/loaders/mimic_demo.py`. Layer 2 trajectory validation (159 stays with trajectories). |
| **Isfahan ED — 143,140 stays** | ✅ Loader built, marked non-trainable | `data/loaders/isfahan.py`. `LeakageError` raised if anyone tries to train on it. Priors extracted to `data/isfahan_priors.json`. |
| **Synthetic Generator** | ✅ Complete | `data/loaders/synthetic.py`. Fitted to real Isfahan priors. Generates paediatric, geriatric, surge, and deterioration profiles. |
| **Fixtures** | ✅ Present | `data/synthetic/fixtures.json` — 8.5KB of named test patient profiles. |

### 1.3 Configuration Files

| File | Status | Notes |
|---|---|---|
| `config/guardrail-ruleset.yaml` | ✅ Complete | Versioned thresholds (SpO₂, SBP-by-age, RR bounds, GCS, etc.) |
| `config/esi-nomenclature.yaml` | ✅ Complete | ESI 1-5 definitions |
| `config/reassessment-intervals.yaml` | ✅ Complete | Per-band reassessment timing |
| `config/schemas/clinical_snapshot.json` | ✅ Complete | JSON schema for clinical snapshots |
| `config/schemas/atria_assessment.json` | ✅ Complete | JSON schema for ATRIA assessments |
| `config/schemas/nurse_assessment.json` | ✅ Complete | JSON schema for nurse assessments |
| `config/schemas/queue_entry.json` | ✅ Complete | JSON schema for queue entries |
| `config/schemas/audit_event.json` | ✅ Complete | JSON schema for audit events |
| `contracts/schema.py` | ✅ Complete | Shared column contract (MIMIC-IV-ED names) |

### 1.4 Service Layer

| Component | Status | Notes |
|---|---|---|
| **FastAPI Application** (`service/app.py`) | ✅ Complete | 300 lines. Full REST API with all PRD §16.2 endpoints. |
| **Queue Engine** (`service/queue.py`) | ✅ Complete | 481 lines. Complete queue management with treatment slots, escalation, and all workflow integration. |
| **Replay Clock** (`service/clock.py`) | ✅ Complete | Simulated shift replay at configurable speed. |
| **Flow Forecast** (`service/forecast.py`) | ✅ Complete | 5-point projection (now, +15/30/45/60m). Capped treatment line, uncapped waiting line. |
| **Decision Window** (`service/decision_window.py`) | ✅ Complete | Adaptive timing for decision workflow. |
| **FHIR adapter** (`service/fhir.py`) | ✅ Complete | FHIR R4 mapping for encounter export. |
| **WebSocket** | ✅ Complete | Real-time broadcast to all connected clients. |

### 1.5 API Endpoints Implemented

| Endpoint | Status |
|---|---|
| `POST /v1/encounters` | ✅ |
| `POST /v1/encounters/{id}/observations` | ✅ |
| `POST /v1/encounters/{id}/nurse-assessments` | ✅ |
| `POST /v1/assessments/{id}/reveal` | ✅ (with token enforcement) |
| `POST /v1/assessments/{id}/finalize` | ✅ |
| `POST /v1/encounters/{id}/worsening` | ✅ |
| `POST /v1/charge-nurse/{id}/acknowledge` | ✅ (REA-008) |
| `GET /v1/queue` | ✅ |
| `GET /v1/operations/forecast` | ✅ |
| `GET /v1/history` | ✅ |
| `GET /v1/integrations/health` | ✅ |
| `POST /api/degraded/{0|1}` | ✅ |
| `POST /api/override/{stay_id}/{band}` | ✅ |
| `GET /api/audit` | ✅ |
| `GET /api/snapshot` | ✅ |
| `WS /ws` | ✅ |

### 1.6 Frontend — Three Separate Interfaces

| Frontend | Status | Notes |
|---|---|---|
| **Streamlit App** (`streamlit_app.py`) | ✅ Complete (652 lines) | Three tabs: Assessment, Operations & Flow, History. Dark theme, auto-refreshing, blind workflow integrated. Deployable to Streamlit Cloud. |
| **Dashboard HTML** (`dashboard/index.html`) | ✅ Complete | 3-column ATRIA Workstation layout. Redesigned in last conversation to match reference UI (`image.png`). Served by FastAPI at `/`. |
| **Next.js Client** (`atria-web/`) | ✅ Phases 1-4 built | TypeScript, App Router. Components: QueueRow, BlindAssessment, PatientRecord, StatusBar. WebSocket context with FLIP animations. Pages: main queue, operations, history. |

### 1.7 Evaluation & Measurement

| Component | Status | Notes |
|---|---|---|
| `eval/fairness.py` | ✅ | Subgroup audit: racial disparity narrowed (8.3 → 5.0 pt gap) |
| `eval/cross_site.py` | ✅ | Site-holdout validation: ±0.026 AUC |
| `eval/lead_time.py` | ✅ | Layer 2 lead time: median 164 min on MIMIC |
| `eval/latency.py` | ✅ | p95 52ms under 3× surge |
| `eval/figures.py` | ✅ | Deck figure generation |
| `eval/report.py` | ✅ | Regenerates `docs/results.md` from live code |

### 1.8 Test Suite

**14 test files, ~2,023 lines, 156 tests** covering:
- Layer 0 boundary tests (`test_layer0.py` — SAF-001 through SAF-008)
- Abstention logic (`test_abstention.py`)
- Acceptance scenarios (`test_acceptance.py` — 624 lines, all PRD §21 scenarios)
- PRD compliance (`test_prd_compliance.py` — 402 lines)
- Queue invariants (`test_queue.py`)
- Ratchet invariant (`test_ratchet.py` — modifiers never cross bands)
- Pathways (`test_pathways.py`)
- Conformal calibration (`test_conformal.py`)
- Fairness (`test_fairness.py`)
- Audit chain (`test_audit.py`)
- Scenarios (`test_scenarios.py`)
- Data loaders (`test_loaders.py`)
- Model verification (`test_verify.py`)
- Report generation (`test_report.py`)

### 1.9 Documentation

| Document | Status |
|---|---|
| `README.md` | ✅ Complete (303 lines) |
| `docs/how-it-works.md` | ✅ |
| `docs/pitch.md` | ✅ |
| `docs/results.md` | ✅ (auto-generated) |
| `docs/business-proposal.md` | ✅ |
| `docs/regulatory.md` | ✅ (HIPAA, SaMD class, liability, consent, bias) |
| `docs/nextjs-migration.md` | ✅ |
| `docs/deck-changes.md` | ✅ |
| `docs/proposal-outline.md` | ✅ |
| `dashboard/NOTES.md` | ✅ |
| `ATRIA_Product_Prototype_Build_Plan (2).md` | ✅ |
| `docsfromsatyansh/ATRIA PRD.pdf` | ✅ (55-page product spec) |

### 1.10 DevOps & Infrastructure

| Item | Status |
|---|---|
| `Makefile` | ✅ (12 commands) |
| `Dockerfile` | ✅ |
| `docker-compose.yml` | ✅ (7 services: db, redis, api, guardrail-service, inference-service, web, streamlit) |
| `.env.example` | ✅ |
| `requirements.txt` | ✅ |
| `requirements-dev.txt` | ✅ |
| `pytest.ini` | ✅ |
| `.streamlit/config.toml` | ✅ (dark theme) |
| `.gitignore` | ✅ |

### 1.11 Scenarios

- `scenarios/seeds.py` — 7 deterministic demo cases
- `scenarios/run.py` — Runner producing identical output every time (`make scenarios`)

---

## 2. What Has NOT Been Done ❌

### 2.1 Build Plan Phase 0 — Contract Freeze (Partially Done)

| Task | Status | Notes |
|---|---|---|
| Finalize JSON schemas | ✅ Done | 5 schemas in `config/schemas/` |
| Version guardrail ruleset | ✅ Done | `config/guardrail-ruleset.yaml` |
| Freeze recommendation response payload as OpenAPI schema | ❌ Not done | The FastAPI app auto-generates OpenAPI, but it hasn't been explicitly frozen/versioned as a contract |
| Named clinical reviewer sign-off | ❌ Not done | No clinical sign-off documented (Satyansh provided input but no formal sign-off recorded) |
| `ReassessmentTask` schema | ❌ Not done | No JSON schema for this entity exists in `config/schemas/` |
| `OverrideEvent` schema | ❌ Not done | No dedicated JSON schema; overrides are logged via the audit system but not schema'd separately |

### 2.2 Build Plan Phase 1 — Deterministic Core

| Task | Status | Notes |
|---|---|---|
| Layer 0 as pure functions | ✅ Done | |
| Missing-essential-vital abstention | ✅ Done | |
| Age-aware vital interpretation | ✅ Done | |
| Unit tests for SAF-001–008 | ✅ Done | |
| Validate against Yale + MIMIC vitals | ⚠️ Partial | The model trains on Yale, but there's no explicit "sanity fixture" that cross-checks Layer 0 firings against `esi==1` rows |

### 2.3 Build Plan Phase 2 — Queue, Record and Workflow

| Task | Status | Notes |
|---|---|---|
| All PRD §16.2 endpoints | ✅ Done | |
| Blind reveal enforcement | ✅ Done | Server-side, with reveal token |
| Safety-band sorting | ✅ Done | |
| Reassessment scheduler | ✅ Done | Due-time computation, overdue flags |
| REA-008 charge-nurse escalation | ✅ Done | Endpoint exists, audit event logged |
| Configurable grace period for REA-008 | ⚠️ Unclear | The interval config exists but the grace-period escalation logic may not be fully wired |
| Rewire `apps/web` to call APIs | ✅ Done | Both dashboard and Next.js call the API |

### 2.4 Build Plan Phase 3 — Model Baseline

| Task | Status | Notes |
|---|---|---|
| Feature pipeline from Yale | ✅ Done | |
| Exclude race, nurse ESI, post-triage fields | ✅ Done | Explicitly documented |
| Train interpretable baseline | ✅ Done | Gradient-boosted-trees |
| Calibration + abstention | ✅ Done | ML-001–006 |
| Reason-code templating | ✅ Done | Fixed vocabulary |
| Evaluation report | ✅ Done | `docs/results.md` |
| Frozen model artifact | ❌ Not done | `ml/models/` directory is **empty** — model trains on-the-fly at startup rather than loading a frozen artifact |
| Model manifest (`manifest.json`) | ❌ Not done | No `model_version`, training data hash, calibration params, or feature schema recorded |
| Release gates from §20.3 | ❌ Not done | Not formally checked off |
| Failure-mode tests (guardrail-down vs model-down) | ⚠️ Partial | `test_model_unavailable` exists via degraded mode, but `test_guardrail_service_down` as a separate explicit test is not confirmed |

### 2.5 Build Plan Phase 4 — Operations & Flow (Partially Done)

| Task | Status | Notes |
|---|---|---|
| Operational snapshot aggregation | ✅ Done | waiting, inside, nurses, staffed spaces, arrival rate |
| 5-point forecast | ✅ Done | |
| Bounded operational modifier | ✅ Done | With invariant test |
| Degraded-mode per integration | ⚠️ Partial | Toggle exists in Streamlit; `integrations/health` endpoint returns status; but actual degradation behavior per integration (INT-001 through INT-008) is not fully differentiated |

### 2.6 Build Plan Phase 5 — Shadow Validation ❌ Not Done

| Task | Status | Notes |
|---|---|---|
| Real or sandbox FHIR integration | ❌ Not done | `service/fhir.py` exists (mapping logic), but no actual FHIR sandbox connected |
| Shadow mode (log but don't act) | ❌ Not done | |
| Distributed tracing | ❌ Not done | |
| PHI-safe logging | ❌ Not done | |
| Usability pass on 11" tablet | ❌ Not done | |
| Go/no-go review package | ❌ Not done | |

### 2.7 Microservice Decomposition ❌ Not Done

The Build Plan specifies **9 separate services** per PRD §16.1. The current architecture is a **monolith** — everything runs in one Python process. The `docker-compose.yml` creates separate containers, but the `guardrail-service` and `inference-service` containers are stubs that load the module and sleep:

```yaml
# guardrail-service just does:
python -c "from layer0.engine import gate, RuleTable; ... time.sleep(999999)"

# inference-service just does:
python -c "from layer1.model import AcuityScorer; ... time.sleep(999999)"
```

The actual request handling goes through the monolithic `service/app.py`. These are **not** real microservices yet:

| PRD Service | Actual Status |
|---|---|
| Clinical Data Gateway | ❌ Folded into the monolith |
| Guardrail Service | ❌ Stub container, logic runs in-process |
| Inference Service | ❌ Stub container, model runs in-process |
| Assessment Orchestrator | ⚠️ `service/app.py` serves this role but isn't separated |
| Queue Service | ❌ Part of `service/queue.py`, not a separate service |
| Reassessment Scheduler | ❌ Logic is in the queue engine, not a separate service |
| Flow Forecast Service | ❌ Part of `service/forecast.py`, not a separate service |
| Audit Service | ❌ Part of `layer3/audit.py`, in-process |
| Integration Adapters | ❌ Only `service/fhir.py` exists as a mapper, not a real adapter |

### 2.8 Data Persistence ❌ Not Done

| Item | Status | Notes |
|---|---|---|
| **PostgreSQL schema** | ❌ Not done | `docker-compose.yml` defines a Postgres container, but there are **no SQL migrations, no ORM models, no database tables**. All state lives in Python objects in memory. |
| **Redis pub/sub** | ❌ Not done | Redis container defined but **never connected to**. SSE/event streaming is done via WebSocket directly from the monolith. |
| **Immutable snapshots** | ❌ Not done | Snapshots are computed on-the-fly, not persisted to a database. |
| **Durable audit trail** | ❌ Not done | The audit log is in-memory (`layer3/audit.py` uses a Python list). It is hash-chained but not persisted. Restart = gone. |

### 2.9 Authentication & Authorization ❌ Not Done

| Item | Status | Notes |
|---|---|---|
| JWT/session auth | ❌ Not done | `JWT_SECRET` is in the environment but no auth middleware is implemented |
| Role-based access (nurse, charge nurse, clinician, ops, admin, auditor) | ❌ Not done | All endpoints are unauthenticated |
| SEC-002/003 compliance | ❌ Not done | |

### 2.10 Next.js Client — Phase 5 ❌ Not Done

Per `docs/nextjs-migration.md`, Phases 1-4 are built but Phase 5 is not:
- ❌ Virtualised queue (200+ patients at 60fps)
- ❌ Optimistic updates
- ❌ Keyboard-first triage (`1-5` for ESI, `j/k` for navigation)
- ❌ Full WCAG 2.2 AA accessibility
- ❌ Harvey ball SVG indicator

### 2.11 Missing ML Pipeline Components

| Item | Status |
|---|---|
| Training scripts in `ml/training/` | ❌ Directory doesn't exist |
| Evaluation matrix in `ml/evaluation/` | ❌ Directory doesn't exist |
| `ml/models/` artifacts | ❌ Directory exists but is **empty** |
| Model versioning with manifest | ❌ Not done |
| Input/prediction drift monitoring | ❌ Not done |

### 2.12 Acceptance Testing Gaps

The test suite covers most PRD §21 scenarios, but some specific tests are not confirmed as separate entries:
- ⚠️ `test_guardrail_service_down` (distinct from `test_model_unavailable`)
- ⚠️ Named fixtures from PRD Appendix B (Pediatric Control, Arthur Hale, John Doe, Meera Shah, Aarav Kumar) — some may be in `data/synthetic/fixtures.json` but not confirmed as individually named acceptance fixtures

---

## 3. Summary: Where Things Stand

### Build Plan Phase Progress

| Phase | Description | Progress |
|---|---|---|
| **Phase 0** — Contract Freeze | JSON schemas, config | **~85%** (schemas done, formal sign-off missing) |
| **Phase 1** — Deterministic Core | Layer 0 | **~95%** (functional, tested, minor validation gap) |
| **Phase 2** — Queue, Record, Workflow | APIs, blind assessment, queue | **~90%** (all endpoints work, REA-008 done) |
| **Phase 3** — Model Baseline | ML training, evaluation | **~75%** (model works, but no frozen artifact, no manifest, empty `ml/models/`) |
| **Phase 4** — Operations & Flow | Forecast, operational modifiers | **~80%** (forecast works, degradation behavior partial) |
| **Phase 5** — Shadow Validation | FHIR sandbox, shadow mode, observability | **~5%** (FHIR mapper exists, nothing else) |

### Architecture Gap

The system is a **working prototype** with a monolithic architecture. The 9-service microservice decomposition from the Build Plan is **entirely unimplemented** — docker-compose has stub containers but the actual code runs in one process with in-memory state. This means:

- **No database persistence** — restart loses all data
- **No real service boundaries** — can't independently deploy or scale
- **No auth** — all endpoints are open
- **No durable audit trail** — the hash-chain exists in RAM only

### What Actually Works Today

Despite the architecture gaps, the **functional prototype is strong**:

1. `make streamlit` → Working 3-tab triage board on `:8501` with blind workflow, queue, operations forecast, and audit history
2. `make demo` → FastAPI server on `:8000` with WebSocket-driven dashboard
3. `make web` → Next.js client on `:3000` with typed API, FLIP animations, and full assessment flow
4. `make scenarios` → 7 deterministic demo cases with reproducible output
5. `make test` → 156 tests passing
6. `make report` → Auto-generated results with real measured numbers (AUC 0.809, p95 52ms, etc.)
7. Model trains on startup from synthetic data (no external dependencies needed)
8. Deployable to Streamlit Cloud as-is

---

## 4. Key Files Reference

```
Engine:        layer0/engine.py (301L) · layer1/model.py (382L) · layer2/ranking.py (156L) · layer3/workflow.py (222L)
Service:       service/app.py (299L) · service/queue.py (481L) · service/forecast.py (158L)
Frontends:     streamlit_app.py (652L) · dashboard/index.html (22KB) · atria-web/src/ (16 files)
Tests:         tests/ (14 files, 2,023 lines, 156 tests)
Config:        config/ (3 YAML + 5 JSON schemas)
Data:          data/loaders/ (4 source loaders) · data/synthetic/fixtures.json
Eval:          eval/ (6 modules: fairness, cross-site, lead-time, latency, figures, report)
Documentation: docs/ (8 documents + figures) · README.md · Build Plan
```
