# ATRIA — web client

A Next.js client over the Python engine. It renders; it does not decide.

```bash
# terminal 1 — the engine
cd .. && make demo

# terminal 2 — this
npm install
npm run dev            # http://localhost:3000
```

Point it elsewhere with `NEXT_PUBLIC_ATRIA_API`. The engine must allow this
origin — set `ATRIA_ALLOWED_ORIGINS` on the Python side if it is not
`localhost:3000`.

## What lives where

| | |
|---|---|
| `src/types/atria.ts` | Domain types, hand-written against real payloads |
| `src/lib/api.ts` | The only module that talks to the engine |
| `src/lib/queue-context.tsx` | One websocket, broadcast through context |
| `src/lib/useFlip.ts` | FLIP animation for queue reordering |
| `src/components/BlindAssessment.tsx` | The three-step blind cycle |
| `src/app/page.tsx` | Assessment — queue, assessment, record |
| `src/app/operations/` | Flow forecast against staffed capacity |
| `src/app/history/` | Audit trail and chain integrity |

## Two rules for anyone working on this

**No clinical logic in TypeScript.** Bands, thresholds, outcomes and whether a
reason is required are all decided server-side and read from the response. The
moment a threshold appears in this codebase there are two sources of truth, and
they will diverge.

**The blind guarantee stays on the server.** Before the nurse commits, the
assessment payload contains no recommendation field at all and `/reveal` returns
409. Do not "improve" this by fetching the recommendation early and hiding it in
the client — a hidden field is one devtools panel away from being visible.

## Why the generated OpenAPI types are not used

`src/types/api.ts` is generated from the schema and kept for reference, but the
FastAPI endpoints return bare `JSONResponse`, so every body types as `unknown`.
The hand-written types in `atria.ts` are the real contract, verified against a
live `/v1/queue`. Adding `response_model=` on the Python side would let the
generated types replace them.
