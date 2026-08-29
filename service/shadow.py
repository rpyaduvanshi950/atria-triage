"""
Shadow mode — ATRIA computes, and changes nothing.

Phase 1 of the deployment roadmap, and the only honest way to earn the right to
run live. Every layer runs exactly as it would in production; the difference is
that the result is written to the audit trail instead of to the board. Nobody's
queue position moves. Nobody is asked to justify anything.

What comes out is the evidence the department needs before switching it on: how
often ATRIA would have escalated somebody the current process left waiting, how
often it would have moved somebody down, and — the number that decides it — what
happened to the patients where the two disagreed.

Turning it on:

    ATRIA_SHADOW=1 make api          # or POST /v1/shadow/1 as an admin
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any

#: The band every patient sits at while ATRIA is shadowing: the default a
#: department without decision support gives someone who is not visibly dying.
#: Layer 0 red flags are the exception — see `baseline_band`.
SHADOW_BASELINE = 3

ENABLED_BY_DEFAULT = os.environ.get("ATRIA_SHADOW", "").lower() in ("1", "on", "true")


def baseline_band(red_flag: str | None) -> int:
    """
    What happens to the patient while ATRIA is only watching.

    A Layer 0 red flag still acts. It is not a model output — it is eleven cited
    thresholds any triage protocol already applies, and suppressing it to keep
    the experiment clean would mean deliberately not acting on a measured SpO2 of
    84%. Shadow mode withholds the *recommendation*, not the standard of care.
    """
    return 1 if red_flag else SHADOW_BASELINE


def compare(audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Summarise the disagreements from what shadow mode logged.

    Reads the audit trail rather than live objects, so the report is reproducible
    from the record and can be regenerated months later from the database alone.
    """
    rows = [r for r in audit_rows if r.get("kind") == "shadow_recommendation"]
    if not rows:
        return {"n": 0, "note": "shadow mode has not recorded anything yet"}

    agree = would_escalate = would_lower = 0
    deltas: Counter[int] = Counter()
    escalations: list[dict[str, Any]] = []

    for r in rows:
        p = r.get("payload", r)
        acted, shadow = p.get("acted_band"), p.get("shadow_band")
        if acted is None or shadow is None:
            continue
        deltas[acted - shadow] += 1
        if shadow == acted:
            agree += 1
        elif shadow < acted:                      # lower number = more urgent
            would_escalate += 1
            escalations.append({"stay_id": r.get("stay_id"), "at": r.get("at"),
                                "from": acted, "to": shadow,
                                "reasons": p.get("reasons", [])})
        else:
            would_lower += 1

    n = agree + would_escalate + would_lower
    return {
        "n": n,
        "agreement_rate": round(agree / n, 3) if n else 0.0,
        "would_have_escalated": would_escalate,
        "would_have_escalated_rate": round(would_escalate / n, 3) if n else 0.0,
        "would_have_lowered": would_lower,
        "band_delta_histogram": dict(sorted(deltas.items())),
        # The cases worth a chart review. That review, not this number, is what
        # tells the department whether ATRIA was right to disagree.
        "escalations_for_review": escalations[-25:],
        "note": ("ATRIA did not act on any of these. Bands on the board came "
                 "from the existing process."),
    }
