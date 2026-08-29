# Running ATRIA somewhere that matters

Four things separate the demo from something a department could pilot. All four
are now built. This is what each one does, how to switch it on, and what it
deliberately still does not claim.

---

## 1. The audit trail survives a restart

A hash-chained log that lives in Python objects proves nothing. Restart the
process and the chain — the whole basis of "nothing was rewritten" — is gone,
and a fresh one verifies perfectly while attesting to nothing.

```bash
ATRIA_DB=data/atria_audit.db make demo    # `make demo` sets this already
```

**SQLite, not Postgres.** A triage prototype should not need a database server
running beside it to be trustworthy, and one portable file is easier for an
auditor to take away and check. Swapping in Postgres later means changing
`layer3/store.py` and nothing else.

Two independent defences, because they fail differently:

| | |
|---|---|
| **The database refuses** | `UPDATE` and `DELETE` triggers abort. Tampering fails when it is attempted, not when someone remembers to check |
| **The chain notices** | If a row is changed anyway — a copy with the triggers dropped, a direct file edit — `verify()` names the entry and the seq it broke at |

On startup the chain is rebuilt from disk, so the process continues the same
chain rather than quietly beginning a new one.

**A bug worth recording.** `QueueEngine` did `self.audit = audit or AuditLog()`.
`AuditLog` defines `__len__`, so a *fresh durable log is falsy* — the engine
threw it away, substituted an in-memory one, and the service printed that it was
writing to disk while writing nothing. It was found end to end and never by a
unit test, because every unit test passed no log at all. There is a regression
test now.

---

## 2. Everyone signs in, and the record says who they were

Eighteen endpoints were open. The data was the smaller problem: an override
recorded against a hardcoded `nurse.demo` is not evidence of anything.

```bash
make demo          # auth on, seeded demo accounts
ATRIA_AUTH=off make demo    # projector demo only
```

Bearer tokens (JWT, HS256), PBKDF2-SHA256 passwords, and **six roles**:

| Role | May |
|---|---|
| Triage nurse | read the queue, assess, sign off, report a change |
| Charge nurse | the above, plus acknowledgements, flow and history |
| Clinician | the above, plus **lowering a priority** |
| Flow coordinator | the department view. Not the board, not overrides |
| Clinical governance | the decision history, read-only |
| Administrator | everything, including shadow mode |

Two decisions worth defending:

**The auditor cannot write.** The person checking the chain should not be able
to add to it.

**Ops cannot lower a priority.** Downgrading is a clinical act, and the role
that owns bed pressure is exactly the one that should not be able to relieve it
by moving somebody down the list.

Identity comes from the signed token, never from a query parameter. `clinician=`
is gone from every route.

Demo accounts have the password equal to the username and exist only because a
judge has thirty seconds. Set `ATRIA_USERS` — a JSON map of *hashes*, never
plaintext — and they are replaced.

---

## 3. The model is frozen, and the manifest says what it is

The service used to train at startup. No two deployments were provably the same
model, which makes the `model_version` in an audit entry meaningless.

```bash
make freeze     # trains once, writes ml/models/acuity.pkl + manifest.json
```

The manifest matters more than the pickle. It records the model version, what it
was trained on and the SHA-256 of that data, the full feature list, the
operating point and band cuts, the conformal alpha, and the measured metrics.
A decision logged six months ago can be traced to the exact model that made it —
and `model_version` is now stamped on every sign-off.

**An artifact whose bytes do not match its manifest is not loaded.** The service
trains from scratch instead. A slow start is a much smaller problem than running
a model nobody reviewed.

---

## 4. Shadow mode — Phase 1, and the only honest way to go live

Every layer runs. Nothing acts.

```bash
make shadow                        # or POST /v1/shadow/1 as an administrator
GET /v1/shadow                     # the report
```

Bands on the board come from the existing process; ATRIA's recommendation goes
to the audit trail as `shadow_recommendation`. Nobody's queue position moves and
nobody is asked to justify anything.

**One exception: a Layer 0 red flag still acts.** It is eleven cited thresholds
any triage protocol already applies, not a model output. Suppressing it would
mean deliberately not acting on a measured SpO₂ of 84% in order to keep an
experiment clean. Shadow mode withholds the recommendation, not the standard of
care.

The report answers the question a department actually asks: how often would
ATRIA have escalated someone the current process left waiting? It is computed
from the audit trail rather than from live objects, so it is reproducible from
the record months later. And it ends in `escalations_for_review` — the cases to
chart-review, because the rate alone does not tell anyone whether ATRIA was
right to disagree.

---

## 5. FHIR — a real connection, read-only

`service/fhir.py` maps ATRIA outwards. `service/fhir_client.py` reads inwards:
given a patient on a FHIR R4 server, pull their vital-sign Observations and turn
them into the row the engine already understands.

```bash
ATRIA_FHIR_BASE=https://hapi.fhir.org/baseR4 make demo
GET /v1/integrations/fhir/{patient_id}
```

Verified against the public HAPI R4 sandbox: `fhirVersion 4.0.1`, Observations
resolved by LOINC code, latest reading per vital.

Three constraints:

- **Read-only.** ATRIA never writes to the record, and there is no code here
  that could.
- **Missingness is returned explicitly.** "Nobody measured SpO₂" and "SpO₂ is
  fine" are different facts, and the safety layers depend on the difference.
- **Bounded by a short timeout.** A slow hospital interface must never hold up a
  triage decision. A failure degrades to "vitals not retrieved" and Layer 0
  carries on with what was measured at the bedside.

---

## What this still does not claim

- No hospital has connected a real feed. The sandbox is a public test server.
- Shadow mode has been exercised against simulated patients only. Its value is
  entirely in what it would produce during a real pilot.
- Demo accounts are not an identity system. A pilot means SSO, and the roles
  above mapped onto whatever the hospital already uses.
- Nothing here has been through clinical governance, and none of the thresholds
  should be used on a real patient.
