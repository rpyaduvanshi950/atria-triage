"""
Blind nurse-first assessment.

The nurse commits to an ESI *before* ATRIA's recommendation exists on their
screen. Only then is it revealed, and the two are compared.

This is an anti-anchoring mechanism. Show a clinician a number first and they
will converge on it — automation bias is not a failure of diligence, it is how
attention works under load. Hiding the recommendation until the human has
committed is the cheapest known defence, and it has a second benefit: every
encounter produces an independent human label, which is the only way to measure
whether the model is actually adding anything.

It is also why the model may not use the nurse's ESI as a feature. A model that
reads the answer cannot disagree with it, and the comparison would be theatre.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum


class Stage(Enum):
    AWAITING_NURSE = "awaiting_nurse"   # ATRIA locked; nurse must choose
    COMPARED = "compared"               # revealed; outcome resolved
    SIGNED = "signed"                   # final ESI recorded


class Outcome(Enum):
    MATCH = "match"
    NURSE_ESCALATION = "nurse_escalation"   # nurse more urgent than ATRIA
    NURSE_DOWNGRADE = "nurse_downgrade"     # nurse less urgent — reason required
    GUARDRAIL = "guardrail"                 # Layer 0 critical — reason to go lower
    UNCERTAIN = "uncertain"                 # ATRIA abstained


#: Outcomes where the nurse must justify themselves before the encounter closes.
NEEDS_REASON = {Outcome.NURSE_DOWNGRADE, Outcome.GUARDRAIL, Outcome.UNCERTAIN}


class BlindAssessmentError(RuntimeError):
    """Raised when a caller tries to skip or reorder the workflow."""


@dataclass
class Assessment:
    """One blind assessment cycle for one patient."""

    stay_id: int
    stage: Stage = Stage.AWAITING_NURSE
    nurse_esi: int | None = None
    atria_esi: int | None = None
    atria_abstained: bool = False
    guardrail: bool = False
    outcome: Outcome | None = None
    reason_code: str = ""
    final_esi: int | None = None
    clinician: str = ""
    #: how many times this patient has been re-assessed from scratch
    cycle: int = 1
    #: Issued only once a nurse ESI is durably stored, and required by reveal.
    #: This makes the ordering a server-enforced invariant rather than something
    #: the client merely happens to call in the right sequence: no token exists
    #: until the assessment is recorded, so a reveal cannot be forged by
    #: replaying requests or by a client that skips a step. (Build plan §6.2.)
    reveal_token: str = ""

    # --- what the nurse is allowed to see -----------------------------------

    @property
    def revealed(self) -> bool:
        return self.stage is not Stage.AWAITING_NURSE

    def visible_to_nurse(self) -> dict:
        """
        The only view the UI may render. Before the nurse commits, this carries
        no recommendation at all — not hidden by CSS, absent from the payload,
        so it cannot leak through the DOM or a network tab.
        """
        base = dict(stay_id=self.stay_id, stage=self.stage.value, cycle=self.cycle,
                    nurse_esi=self.nurse_esi, revealed=self.revealed,
                    guardrail=self.guardrail)
        # the token is returned once, by the endpoint that mints it — never
        # again in a general view payload
        if not self.revealed:
            return base
        return dict(base, atria_esi=self.atria_esi,
                    atria_abstained=self.atria_abstained,
                    outcome=self.outcome.value if self.outcome else None,
                    needs_reason=self.needs_reason,
                    final_esi=self.final_esi, reason_code=self.reason_code)

    @property
    def needs_reason(self) -> bool:
        return self.outcome in NEEDS_REASON

    # --- transitions ---------------------------------------------------------

    def submit_nurse_esi(self, esi: int) -> str:
        if self.stage is not Stage.AWAITING_NURSE:
            raise BlindAssessmentError(
                f"stay {self.stay_id} is already at {self.stage.value}; "
                "call reopen() to start a fresh blind cycle")
        if not 1 <= esi <= 5:
            raise ValueError(f"ESI must be 1-5, got {esi}")
        self.nurse_esi = esi
        # a fresh token per submission, so an earlier one cannot be replayed
        self.reveal_token = secrets.token_urlsafe(16)
        return self.reveal_token

    def reveal(self, atria_esi: int | None, *, abstained: bool = False,
               guardrail: bool = False, token: str | None = None) -> Outcome:
        """
        Reveal ATRIA and resolve the comparison.

        Requires the token issued when the nurse's ESI was stored. Callers inside
        the process may omit it; anything reaching this over HTTP must present it.
        """
        if self.nurse_esi is None:
            raise BlindAssessmentError(
                f"stay {self.stay_id}: cannot reveal before the nurse has chosen")
        # Revealing twice is refused outright. The comparison is the record of
        # what the nurse thought before seeing ATRIA; letting it be recomputed
        # would let a second call quietly overwrite that with a different
        # outcome, and the audit entry alongside it.
        if self.stage is not Stage.AWAITING_NURSE:
            raise BlindAssessmentError(
                f"stay {self.stay_id}: already revealed — reveal is once per cycle")
        if token is not None and token != self.reveal_token:
            raise BlindAssessmentError(
                f"stay {self.stay_id}: reveal token does not match the stored "
                f"assessment")
        # Spend the token. Holding it open would make it a password rather than
        # a one-time proof that the nurse's answer was stored first.
        self.reveal_token = ""
        self.atria_esi = atria_esi
        self.atria_abstained = abstained
        self.guardrail = guardrail
        self.stage = Stage.COMPARED
        self.outcome = self._compare()
        return self.outcome

    def _compare(self) -> Outcome:
        # A fired guardrail outranks everything: the nurse may still go less
        # urgent, but they own that in writing.
        if self.guardrail and self.nurse_esi > 1:
            return Outcome.GUARDRAIL
        if self.atria_abstained or self.atria_esi is None:
            return Outcome.UNCERTAIN
        if self.nurse_esi == self.atria_esi:
            return Outcome.MATCH
        # lower number is more urgent
        return (Outcome.NURSE_ESCALATION if self.nurse_esi < self.atria_esi
                else Outcome.NURSE_DOWNGRADE)

    def finalise(self, *, clinician: str, reason_code: str = "") -> int:
        if self.stage is not Stage.COMPARED:
            raise BlindAssessmentError(
                f"stay {self.stay_id}: cannot finalise from {self.stage.value}")
        if self.needs_reason and not reason_code:
            raise BlindAssessmentError(
                f"stay {self.stay_id}: {self.outcome.value} requires a reason code")
        self.reason_code = reason_code
        self.clinician = clinician
        self.final_esi = self.nurse_esi
        self.stage = Stage.SIGNED
        return self.final_esi

    def reopen(self, why: str) -> None:
        """
        New clinical evidence clears the sign-off and forces a fresh blind cycle.

        The previous ATRIA recommendation is discarded rather than carried over —
        showing it would anchor the very decision this workflow exists to keep
        independent. (PRD REA-004, REA-006.)
        """
        self.stage = Stage.AWAITING_NURSE
        self.nurse_esi = None
        self.atria_esi = None
        self.atria_abstained = False
        self.outcome = None
        self.reason_code = ""
        self.final_esi = None
        self.reveal_token = ""      # a new cycle needs a new token
        self.cycle += 1
        self.reopened_because = why


@dataclass
class Workflow:
    """All in-flight assessments, keyed by stay."""

    assessments: dict[int, Assessment] = field(default_factory=dict)

    def open(self, stay_id: int) -> Assessment:
        a = self.assessments.get(stay_id)
        if a is None:
            a = self.assessments[stay_id] = Assessment(stay_id=stay_id)
        return a

    def get(self, stay_id: int) -> Assessment | None:
        return self.assessments.get(stay_id)

    def signed(self) -> dict[int, int]:
        return {s: a.final_esi for s, a in self.assessments.items()
                if a.stage is Stage.SIGNED and a.final_esi is not None}
