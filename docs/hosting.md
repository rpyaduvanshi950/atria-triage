# Hosting ATRIA

Three pieces, and they cannot all live on the same host.

| Piece | Host | Why |
|---|---|---|
| **FastAPI engine** | Render / Fly.io / Railway | Needs a long-running process, WebSockets, and a disk for the audit trail |
| **Next.js board** | Vercel | It is a Next app |
| **Streamlit board** | Streamlit Community Cloud | Optional second client |

Vercel cannot host the engine: serverless functions do not hold a WebSocket open
or keep a SQLite file. Streamlit Cloud cannot host FastAPI.

---

## 1. The engine, on Render

**New → Web Service** (Blueprints also work and read [`render.yaml`](../render.yaml)).

| Field | Value |
|---|---|
| Repository | your fork |
| Branch | `main` |
| **Language** | **Docker** (not Python) |
| Dockerfile Path | `./Dockerfile` |
| Health Check Path | `/v1/auth/mode` |

Leave build and start commands empty. The image binds `$PORT`, which Render
injects and which every platform ignores `EXPOSE` in favour of.

### Environment

```
ATRIA_SECRET           <click Generate>
ATRIA_ALLOWED_ORIGINS  http://localhost:3000
ATRIA_USERS            <JSON of real accounts, hashes only>
```

**`ATRIA_SECRET` matters more than it looks.** Unset, the app generates a random
one per process, so every deploy and restart signs everyone out and the
WebSocket starts rejecting tokens that were valid a moment ago.

Generate account hashes locally — never put a plaintext password in an
environment variable, where it lands in a process listing and a deploy log:

```bash
.venv/bin/python -c "
from service.auth import hash_password; import json
print(json.dumps({
  'you':   {'role':'admin','display':'Your Name','password_hash': hash_password('...')},
  'nurse': {'role':'nurse','display':'Triage Nurse','password_hash': hash_password('...')},
}))"
```

Leave `ATRIA_USERS` unset and the seeded demo accounts are live, each password
equal to its username. Fine for synthetic data on a private URL, not otherwise.

### The audit trail

**Render only offers persistent disks on paid instance types.**

- **Free:** leave `ATRIA_DB` unset. The trail runs in memory and resets whenever
  the service sleeps or redeploys. Everything works; the chain just does not
  span restarts. Do not claim durability while demonstrating on this.
- **Starter:** add a disk at `/data`, 1 GB, and set
  `ATRIA_DB=/data/atria_audit.db`.

### Verify

```bash
curl https://<service>.onrender.com/v1/auth/mode
# {"auth_enabled":true,"demo_accounts":false}
```

The startup log states what is running:

```
ATRIA: auth on, N accounts from ATRIA_USERS
ATRIA: audit trail -> /data/atria_audit.db     (or "in memory only")
ATRIA: demo shift = 100 patients over 3h at 30x (~6 min real), 5 bays, seed 7
```

---

## 2. The board, on Vercel

**Import project** → your fork.

| Field | Value |
|---|---|
| **Root Directory** | **`atria-web`** |
| Framework | Next.js (auto-detected) |
| Environment variable | `NEXT_PUBLIC_ATRIA_API` = your engine URL |

**Set the variable before the first build.** Next inlines `NEXT_PUBLIC_*` at
build time, both into the rewrite config and the WebSocket URL. Setting it
afterwards requires a redeploy with the build cache cleared, or the page will
keep calling `127.0.0.1:8000`.

**No change is needed on the engine.** HTTP calls are proxied through the board
itself (`next.config.ts` rewrites), so the browser only ever talks to its own
origin and CORS never applies. That keeps the engine's allow-list narrow — Vercel
mints a new URL for every preview deployment, and a list that grows a line per
deploy stops being a control worth having.

The WebSocket connects to the engine directly. WebSockets are not subject to
CORS, which was verified against the deployed service before being relied on.

---

## 3. Free-tier behaviour

Render free spins down after ~15 minutes idle and takes ~50 seconds to wake, and
the replay restarts on wake, so the board opens empty. **Wake it and let a queue
build before presenting.**

## Troubleshooting

| Symptom | Cause |
|---|---|
| "Incorrect username or password" on a fresh deploy | `ATRIA_USERS` is set, so the demo accounts do not exist. Use your own |
| Board loads, calls 404 | `NEXT_PUBLIC_ATRIA_API` was missing at build time. Redeploy without cache |
| Board loads, calls fail with CORS | An old bundle that calls the engine directly. Redeploy |
| WebSocket 403 after a redeploy | `ATRIA_SECRET` changed, so old tokens are invalid. Sign in again |
| First request hangs ~50s | The engine is asleep. Expected on free tier |
