# Demo video script

**Target: 4 minutes.** Timings are cumulative. Every claim in here is one the
repo can back up; nothing is asserted that a judge could not check.

## Before you record

1. **Wake the hosted engine.** Open https://atria-triage.onrender.com/docs and
   wait for it to answer. Free tier sleeps after ~15 minutes and takes ~50s to
   wake. Do this five minutes before recording, not at the moment you start.
2. **Sign in and leave the board running for two minutes** so a queue has built
   and some patients are in bays. A board with four patients on it does not
   demonstrate a queue.
3. Record at **1920×1080**. Browser zoom 100%. Close other tabs.
4. Have a second tab open on the **Logs** page.

> The demo shift is 100 patients over three simulated hours, replayed in about
> six minutes from a **fixed seed** — the same patients in the same order every
> run. You can rehearse against it.

---

## 0:00 — The problem (25s)

> "Triage happens once, at the door. A nurse gives you a number from 1 to 5, and
> that number follows you into the waiting room and stays there. Your condition
> doesn't.
>
> Across five million encounters, that first judgement is wrong about a third of
> the time. And delay turns the error into deaths: one extra death for every 82
> patients held six to eight hours."

*On screen: the board, queue visibly long.*

## 0:25 — What ATRIA is (20s)

> "ATRIA is a live queue instead of a label. It watches vitals as they're
> re-taken and reorders who should be seen next. It never diagnoses, never
> prescribes, and it cannot lower anyone's priority on its own."

*Point at the counters: Waiting, Treated, Waiting for a bay, Moved up.*

> "Thirty-six patients have been moved up since this shift started. Nobody moved
> down without a human doing it."

## 0:45 — The blind assessment (60s) — **the centrepiece**

*Click a patient. Pause on the assessment column.*

> "This is the part that matters. I'm about to triage this patient, and there is
> **nothing from ATRIA on this screen.** Not greyed out — not sent. If I open
> devtools, the recommendation isn't in the response."

*Optional, if the audience is technical: devtools → Network → the
nurse-assessment response. It has no `atria_esi` field.*

> "The reason is anchoring. Show a clinician a number first and they converge on
> it. That's not carelessness, it's how attention works under load."

*Press `3`.*

> "Now it speaks — and it says 2, more urgent than me. It tells me why:
> respiratory failure at 56%, from a respiratory rate of 25 and a heart rate of
> 111. And it says which readings it was judging **without**."

*Point at the outcome banner.*

> "I went less urgent than ATRIA, so it won't let me sign off until I say why.
> If I'd gone **more** urgent, it would let me straight through and never ask. A
> nurse raising urgency is never questioned."

*Pick a reason, sign off.*

## 1:45 — What it costs (20s)

> "The model is not allowed to see the nurse's own ESI. A model told the answer
> can't meaningfully disagree with it. That costs us 0.05 AUC — we score 0.809
> where the published benchmark is 0.87, and the benchmark uses the nurse's
> answer and the patient's race. We exclude both, and we put the price on the
> slide."

## 2:05 — When it refuses (30s)

*Find a patient tagged "Needs you to decide", or check one in with only two
vitals via **Add a patient**.*

> "This patient has two vitals recorded. ATRIA will not give a score at all —
> it says so, names the vitals to go and take, and hands the patient to a
> clinician.
>
> And refusing is an **escalation**, not a shrug. They go to priority 2, ahead
> of everyone we've already cleared. A system that always produces a number is
> lying some of the time."

## 2:35 — Degraded mode (20s)

*Click **Turn suggestions off**.*

> "That's the model gone. The eleven safety rules keep running — oxygen below
> 90, age-banded blood pressure, stroke signs in the window — and they still
> flag critical patients. The safety layer doesn't depend on the model being up."

*Turn it back on.*

## 2:55 — The record (35s)

*Open the **Logs** tab.*

> "Every decision is here, in two views. What ATRIA did on its own — what it
> scored, what it refused to score, what a trajectory escalated. And what people
> did about it: the blind choice, the sign-off, the reason, and the name it was
> made under.
>
> Each entry seals the one before it. Change any past record and the chain
> breaks — the header would say ALTERED instead of *complete and unaltered*."

*Point at the integrity line.*

## 3:30 — What we found by building it (25s)

> "Three things we didn't expect.
>
> One dataset had **zero recorded vitals for every one of its most critical
> patients** — the sickest bypass the form. Train on that and the model learns
> that an empty form means a dying patient. We excluded it.
>
> Our model was reading a **missing** heart rate as reassuring — a silent
> undertriage path aimed at the patient nobody has measured yet.
>
> And our own safety rules fired hypotension on a three-year-old at a blood
> pressure that's normal for a three-year-old. The layer built to protect people
> was wrong about children."

## 3:55 — Close (15s)

> "263 tests. A frozen, versioned model. Shadow mode, so a department can watch
> what it *would* have done before it's allowed to do anything.
>
> ATRIA isn't a system that decides who's sick. It makes sure nobody is
> forgotten while they wait, and that every decision about them has a name
> attached."

---

## If you have 6 minutes instead of 4

Add these:

- **Open a bay** (sign in as `charge.demo`) and watch the queue drain — the
  clearest demonstration that the ordering is doing work.
- **Report a change** on a signed-off patient: the decision reopens and asks for
  a fresh blind ESI, and ATRIA's earlier suggestion is *thrown away* rather than
  shown again, so it cannot anchor the second decision.
- **Shadow mode** (`admin.demo`): every layer runs, nothing moves, and the report
  lists the specific patients to chart-review.
- **The ranking explanation** on the patient record — why this patient is in this
  position, in the order the sort applies.

## Do not claim

- That the audit trail survives a restart **on the hosted demo** — it is in
  memory there. It does with a disk configured; the code and the tests are real.
- That any hospital feed is connected. FHIR is verified against a public sandbox.
- Any clinical validation. Every threshold is a prototype default.
