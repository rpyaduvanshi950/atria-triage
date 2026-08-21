# The nurse board — design decisions

Day 0 output for W3. Decisions recorded here so W2 can build the API against them
before any pixel exists.

## What this screen is

A **live queue**, not a form. The nurse does not come here to enter data — that
happens in the EHR they already use. They come here to answer one question:
*who should I see next, and has that changed since I last looked?*

Everything below serves that question. Anything that does not, is not on this
screen.

## Three row states

Exactly three, because a fatigued nurse mid-shift can hold three states, not
seven. Encoded in **form as well as colour** so the board survives a projector, a
bad monitor, and colour-blind users.

| State | Means | Visual | Sort |
|---|---|---|---|
| `STABLE` | Nothing has changed since sign-off | No stripe, normal weight | By priority, then wait time |
| `ESCALATED` | A machine raised this patient's priority | Left stripe + upward arrow + "↑ from N" | Pinned above their band |
| `AWAITING` | A recommendation needs a human decision | Left stripe + pulsing dot, action buttons live | Top of the board |

A **red flag** (Layer 0) is not a fourth state — it is an overlay on `ESCALATED`,
because a red flag *is* an escalation and treating it separately would let it be
sorted below one. Red-flag rows carry the rule ID and its plain-language reason.

## Every row shows, always

- Priority band (1–5) and, if escalated, what it was before
- **A confidence indicator** — never a bare score. The brief requires this and it
  is on the never-cut list
- The two-line reason (from SHAP or the fired rule)
- Time waiting, and time to re-assessment timer breach
- **Which vitals are missing**, if any — because a score built on assumed-worst
  values must say so

## What the nurse can do

One action per row: **Accept** or **Override**. Override opens a modal requiring a
structured reason code — free text alone is not auditable, and the reason codes
are what make the Layer 3 log analysable later.

Downgrades are visually distinct from accepts. The nurse is doing something the
machine is not permitted to do, and the interface should reflect the weight of
that.

## Board sketch

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ATRIA · Bay A          12 waiting · 3 escalated        [ ● live ] 14:23   │
├────────────────────────────────────────────────────────────────────────────┤
│▌1  RED FLAG   Ahmadi, F.  58F   waited 12m                    ↑ from 3     │
│    RF02 Critical hypoxaemia (on assumed-worst o2sat)                       │
│    confidence: HIGH · missing: SpO2, temp          [ Accept ] [ Override ] │
├────────────────────────────────────────────────────────────────────────────┤
│▌2  ESCALATED  Okafor, D.  71M   waited 48m                    ↑ from 3     │
│    HR 88→112 over 30m · shock index 0.94 rising                            │
│    confidence: MODERATE                            [ Accept ] [ Override ] │
├────────────────────────────────────────────────────────────────────────────┤
│ 3             Silva, M.   34F   waited 22m           re-assess in 8m       │
│    abdominal pain · vitals stable                                          │
├────────────────────────────────────────────────────────────────────────────┤
│ 3             Chen, W.    29M   waited 1h 51m        ⚠ re-assess OVERDUE   │
│    queue-aged: held past safe threshold for band 3                         │
└────────────────────────────────────────────────────────────────────────────┘
```

## Degraded mode

When the model service is down the board **says so**, in the header, and keeps
running on Layer 0 alone. It does not go blank and it does not silently serve
stale scores. Scenario 06 records this happening.

## Deliberately not on this screen

Diagnosis suggestions. Treatment recommendations. Bed assignment. ATRIA changes
the order of attention, not clinical care — and that boundary is what makes it
deployable. If a reviewer asks for any of these, the answer is no.
