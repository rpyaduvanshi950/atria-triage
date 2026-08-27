# Migrating the interface to Next.js

**Do this after the pitch, not before it.** The Streamlit board works, is
deployed, and has 163 tests behind the engine it drives. Rebuilding the shell in
the days before a submission risks arriving with a half-finished interface, and
the part judges actually score — clinical guardrails and decision logic — is
already done.

What follows is the plan for when there is time.

---

## Why it is worth doing at all

The PRD assumes React and Tailwind, and it is right to. Streamlit's rerun model
fights three things this product needs:

- **A live queue.** Streamlit redraws the whole fragment every two seconds.
  Twelve rows is fine; two hundred is not, and a real department is two hundred.
- **The blind workflow.** Widget state replays on fragment reruns, which is what
  produced the double-submit crash. React's state model makes that class of bug
  structurally impossible rather than something to guard against.
- **Design control.** The current board is CSS injected through
  `st.markdown(unsafe_allow_html=True)`. It works, and it is a ceiling.

## Why it is not a rewrite

**Nothing in `layer0`–`layer3` changes.** The engine is UI-agnostic by design and
the FastAPI service already exposes the whole surface. This is a new client over
an existing contract, not a re-implementation.

The Streamlit app stays in the repo. Two clients over one engine is a feature:
it proves the separation is real, and it keeps a working demo while the new one
is unfinished.

---

## The contract that already exists

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/queue` | Ranked attention list + counters + lanes |
| `POST` | `/v1/encounters/{id}/nurse-assessments?esi=` | Blind ESI. Returns **no** recommendation |
| `POST` | `/v1/assessments/{id}/reveal` | Reveal ATRIA, resolve the comparison |
| `POST` | `/v1/assessments/{id}/finalize?reason_code=` | Sign off; 422 if a reason is required |
| `POST` | `/v1/encounters/{id}/worsening` | Clear sign-off, start a fresh blind cycle |
| `GET` | `/v1/operations/forecast?nurses=&spaces=` | One-hour projection + explanation |
| `GET` | `/v1/history?mode=audit\|general` | Audit trail + chain integrity |
| `GET` | `/v1/integrations/health` | Per-integration freshness |
| `POST` | `/api/degraded/{0\|1}` | Kill or restore the model service |
| `WS` | `/ws` | Snapshot per event |

The blind-assessment guarantee is enforced **server-side**: before the nurse
commits, the reveal endpoint returns 409 and the assessment payload contains no
recommendation field at all. A React client cannot leak what it is never sent —
which is the point, and worth saying in the pitch.

---

## Stack

| Choice | Why |
|---|---|
| **Next.js 15, App Router, TypeScript** | The PRD names it; typed API responses catch contract drift at build time |
| **Tailwind + shadcn/ui** | Accessible primitives out of the box — dialog, select, tooltip — which matters because the PRD demands WCAG 2.2 AA |
| **TanStack Query** | Server state with cache invalidation. The queue is server state, not client state, and treating it as such removes most of the bugs |
| **WebSocket via a provider** | One connection, broadcast through context. Reconnect with the stream cursor per PRD 16.3 |
| **Recharts** | The flow forecast. Small, composable, no licence question |

Deploy on Vercel. The Python service goes to Fly.io or Render — Streamlit
Community Cloud cannot host FastAPI.

---

## Phases

Each phase leaves something demonstrable. Do not start the next until the
current one runs.

### Phase 1 — the contract, typed (half a day)

- `npx create-next-app@latest atria-web --typescript --tailwind --app`
- Generate types from the FastAPI OpenAPI schema:
  `npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts`
- A thin `lib/api.ts` wrapping fetch with the base URL and error handling
- **Add CORS to `service/app.py`** — the one backend change this needs

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN],
                   allow_methods=["*"], allow_headers=["*"])
```

**Done when** a page renders the live queue as an unstyled list.

### Phase 2 — the queue (one day)

- `QueueProvider` holding the websocket, exposing snapshot + connection state
- `<QueueRow>` — band, ticket, lane, reasons, tags, wait
- **Animate rank changes with a FLIP transition** (PRD QUE-003). This is the one
  thing Streamlit genuinely cannot do, and it is what makes "the queue moves"
  visible rather than asserted. Respect `prefers-reduced-motion`.

**Done when** a patient visibly slides up the board on escalation.

### Phase 3 — the blind workflow (one day)

- `/assessment/[stayId]` route
- Three-step machine mirroring `layer3/workflow.py`: assess → compare → sign off
- ESI picker: five controls, ≥56px high per PRD ASS-003
- Comparison cards, outcome banner, reason select gated on `needs_reason`
- **A test asserting the recommendation is absent from the DOM pre-reveal** —
  Playwright, checking the accessibility tree, not just visibility

**Done when** the five comparison outcomes each render correctly and finalize is
blocked without a reason where required.

### Phase 4 — operations and history (one day)

- Forecast chart with the capacity ceiling and the two explanatory captions
- Staffing slider and integration toggles, debounced
- History table with hash/prev columns and the integrity indicator

### Phase 5 — the parts Streamlit could not do (one to two days)

This is where the rebuild earns itself:

- **Virtualised queue** — `@tanstack/react-virtual`, 200+ patients at 60fps
- **Optimistic updates** — the board responds to a click immediately and
  reconciles with the server, instead of waiting for a round trip
- **Keyboard-first triage** — `1`–`5` to select ESI, `Enter` to confirm, `j`/`k`
  to move through the queue. A nurse under load does not want a mouse
- **Real accessibility** — focus management, live regions announcing escalations,
  200% zoom without loss of function
- **The Harvey ball** — an SVG arc rather than a caption

---

## What to be careful about

**Do not let the client re-implement clinical logic.** Bands, thresholds,
reasons and outcomes all come from the server. The moment a threshold appears in
TypeScript there are two sources of truth and they will diverge. If the client
needs to know something, add it to the payload.

**Keep the blind guarantee server-side.** It is currently enforced by the API
returning 409 and omitting the field. Do not "improve" this by sending the
recommendation and hiding it client-side.

**Websocket reconnection needs the cursor**, not a full refetch (PRD 16.3).
Events must be idempotent and ordered by a monotonic version.

**The Streamlit app must keep working** throughout. If a backend change breaks
it, that change is wrong — it means the contract moved without the other client
being told.

---

## Effort

Four to five focused days for parity, plus one to two for the parts that justify
the move. Phases 1–3 alone give a better demo than the current board.

## What does not change

`contracts/` · `data/` · `layer0/` · `layer1/` · `layer2/` · `layer3/` ·
`eval/` · `scenarios/` · all 163 tests. The engine has never known what is
drawing it, and that was deliberate.
