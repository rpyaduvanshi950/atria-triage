"""
Layer 0 — deterministic red-flag gate.

Pure functions over a plain dict. No model, no network, no dataframe. That is the
point: this layer keeps working when everything else is down, which is what makes
the degraded-mode demo honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")

#: Vitals that count toward the floor below which we refuse to score at all.
TRIAGEABLE_FIELDS = ("o2sat", "sbp", "heartrate", "resprate", "temperature", "gcs")

#: RF11. Fewer recorded than this and the system produces no score. A chief
#: complaint on its own is never enough — you cannot triage a sentence.
MIN_FIELDS_TO_TRIAGE = 3

#: RF12. How close the second pathway must come to the first before the picture
#: counts as genuinely ambiguous rather than merely complicated.
AMBIGUITY_THRESHOLD = 0.75

def sbp_hypotension_threshold(patient: dict) -> float:
    """
    Age-banded systolic hypotension, PALS. A systolic of 88 is shock in an adult
    and entirely normal in a three-year-old; a single adult-calibrated number is
    the silent safety risk the brief calls out by name.
    """
    age = patient.get("age")
    if age is None:
        return 90.0                       # unknown age: assume the adult threshold
    if age < 1 / 12:
        return 60.0
    if age < 1:
        return 70.0
    if age < 10:
        return 70.0 + 2.0 * age
    return 90.0


#: Age-banded reference ranges (low, high). Prototype defaults from the PRD's
#: Appendix A; must be externalised and clinically approved before real use.
HR_RANGES = ((5, 70, 140), (8, 65, 130), (12, 60, 120), (15, 55, 115), (999, 50, 110))
RR_RANGES = ((5, 18, 34), (12, 14, 30), (15, 12, 26), (999, 10, 30))


def _range_for(age: float | None, table) -> tuple[float, float]:
    if age is None:
        age = 99                       # unknown age is assessed as an adult
    for upper, lo, hi in table:
        if age < upper:
            return float(lo), float(hi)
    return float(table[-1][1]), float(table[-1][2])


def tachycardia_threshold(patient: dict) -> float:
    """Upper bound of the age-appropriate heart-rate range."""
    return _range_for(patient.get("age"), HR_RANGES)[1]


def bradycardia_threshold(patient: dict) -> float:
    """Lower bound of the age-appropriate heart-rate range."""
    return _range_for(patient.get("age"), HR_RANGES)[0]


def resprate_high_threshold(patient: dict) -> float:
    return _range_for(patient.get("age"), RR_RANGES)[1]


def resprate_low_threshold(patient: dict) -> float:
    return _range_for(patient.get("age"), RR_RANGES)[0]


THRESHOLD_FNS = {
    "sbp_hypotension": sbp_hypotension_threshold,
    "tachycardia": tachycardia_threshold,
    "bradycardia": bradycardia_threshold,
    "resprate_high": resprate_high_threshold,
    "resprate_low": resprate_low_threshold,
}

OPS = {
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "is_true": lambda a, _b: bool(a),
}


@dataclass(frozen=True)
class FiredRule:
    id: str
    name: str
    citation: str
    #: fields that were missing and gated on a worst-case substitution
    imputed: tuple[str, ...] = ()

    def reason(self) -> str:
        base = f"{self.id} {self.name}"
        if self.imputed:
            base += f" (on assumed-worst {', '.join(self.imputed)})"
        return base


@dataclass(frozen=True)
class GateResult:
    #: rules that fired on *observed* values — a confirmed emergency
    fired: tuple[FiredRule, ...] = ()
    #: rules that fired only because a missing vital was assumed worst-case.
    #: Not an emergency, but not safe to ignore: the vital must be measured.
    unresolved: tuple[FiredRule, ...] = ()
    imputed_fields: tuple[str, ...] = ()
    #: RF11 — too few observations to answer. No score is produced at all.
    hard_stop: bool = False
    #: RF12 — the picture is consistent with more than one gate closing.
    ambiguous: bool = False
    #: plain-language reason for a hard stop or an abstention
    abstain_reason: str = ""
    #: how many of the triageable vitals were actually recorded
    observed_fields: int = 0
    #: rules skipped because the data source does not carry the field at all.
    #: An uncollected field is not a missing measurement: treating it as one
    #: fires the rule on every patient and makes the gate meaningless.
    not_evaluable: tuple[str, ...] = ()
    rules_version: str = ""

    @property
    def is_red(self) -> bool:
        """A confirmed red flag, on values someone actually recorded."""
        return bool(self.fired)

    @property
    def needs_measurement(self) -> bool:
        """An emergency that cannot be ruled out because the vital is missing."""
        return bool(self.unresolved) and not self.fired

    @property
    def abstains(self) -> bool:
        """True when the system is declining to produce a ranked score."""
        return self.hard_stop or self.ambiguous

    @property
    def priority(self) -> int:
        """
        Unknown is not normal — but it is also not the same as critical.

        A confirmed flag takes the most urgent band. An unresolvable one takes
        band 2 and an instruction to measure: treating every blank field as a
        crashing patient floods the queue and trains staff to ignore the board,
        which is the failure this system exists to prevent.
        """
        if self.fired:
            return 1
        # An abstention is not a low-acuity finding. We do not know what this
        # patient is, so they go in front of everyone we have already cleared.
        if self.hard_stop or self.ambiguous:
            return 2
        if self.unresolved:
            return 2
        return 5

    def explain(self) -> str:
        if self.abstain_reason:
            return self.abstain_reason
        if self.fired:
            return "; ".join(r.reason() for r in self.fired)
        if self.unresolved:
            fields = ", ".join(self.imputed_fields)
            return f"cannot rule out {self.unresolved[0].name.lower()} — measure {fields}"
        return "no red flags"


class RuleTable:
    def __init__(self, path: Path | str = RULES_PATH):
        spec = yaml.safe_load(Path(path).read_text())
        self.version: str = spec["version"]
        self.worst_case: dict[str, Any] = spec["worst_case"]
        self.rules: list[dict] = spec["rules"]

    def ids(self) -> list[str]:
        return [r["id"] for r in self.rules]

    def _resolve(self, patient: dict, fieldname: str, policy: str) -> tuple[Any, bool]:
        """Return (value, was_imputed) applying the rule's missing policy."""
        value = patient.get(fieldname)
        if value is not None:
            return value, False
        if policy == "worst_case" and fieldname in self.worst_case:
            return self.worst_case[fieldname], True
        return None, False

    @staticmethod
    def observed(patient: dict) -> int:
        """How many of the triageable vitals this patient actually has."""
        return sum(1 for f in TRIAGEABLE_FIELDS
                   if patient.get(f) is not None and patient.get(f) == patient.get(f))

    def _branch(self, patient: dict, conds: list[dict], policy: str
                ) -> tuple[bool, list[str]]:
        """Evaluate one conjunction of conditions."""
        imputed: list[str] = []
        for cond in conds:
            value, was_imputed = self._resolve(patient, cond["field"], policy)
            if value is None:
                return False, []
            if was_imputed:
                imputed.append(cond["field"])
            limit = cond.get("value")
            if "value_fn" in cond:
                limit = THRESHOLD_FNS[cond["value_fn"]](patient)
            if not OPS[cond["op"]](value, limit):
                return False, []
        return True, imputed

    def evaluate(self, patient: dict, available: set[str] | None = None) -> GateResult:
        """
        `available` names the fields the data source can supply at all. Rules
        depending on anything outside it are reported as not evaluable rather
        than gated on an assumed-worst value.
        """
        fired: list[FiredRule] = []
        unresolved: list[FiredRule] = []
        all_imputed: set[str] = set()
        skipped: list[str] = []

        for rule in self.rules:
            if available is not None:
                branches_f = ([b["all_of"] for b in rule["any_of"]] if "any_of" in rule
                              else [rule["all_of"]])
                needs = {c["field"] for br in branches_f for c in br}
                if not needs <= available:
                    skipped.append(rule["id"])
                    continue
            policy = rule.get("missing_policy", "absent")
            imputed: list[str] = []

            # a rule is either one conjunction, or several any of which fire
            branches = ([b["all_of"] for b in rule["any_of"]] if "any_of" in rule
                        else [rule["all_of"]])
            ok = False
            for branch in branches:
                ok, imputed = self._branch(patient, branch, policy)
                if ok:
                    break

            if ok:
                hit = FiredRule(rule["id"], rule["name"], rule["citation"], tuple(imputed))
                if imputed:
                    unresolved.append(hit)
                    all_imputed.update(imputed)
                else:
                    fired.append(hit)

        seen = self.observed(patient)

        # RF11 — hard stop. Note the ordering: a confirmed red flag still stands,
        # because a recorded SpO2 of 82 does not become uncertain just because
        # the rest of the form is blank.
        hard_stop = seen < MIN_FIELDS_TO_TRIAGE and not fired
        reason = ""
        if hard_stop:
            # Two different kinds of absent, and a nurse can only act on one of
            # them. A vital nobody has measured yet is a task. A vital this data
            # source does not carry at all is not — telling someone to "go and
            # record" a field the system can never receive wastes the one
            # instruction we get to give them.
            # `available` is None when the caller makes no claim about the
            # source, in which case every field counts as measurable.
            supplies = set(TRIAGEABLE_FIELDS) if available is None else available
            unmeasured = [f for f in TRIAGEABLE_FIELDS
                          if patient.get(f) is None and f in supplies]
            uncollected = [f for f in TRIAGEABLE_FIELDS if f not in supplies]

            # "2 of 3" read as a fraction: three is the minimum, not the total.
            reason = (f"RF11 insufficient data to triage — only {seen} vital"
                      f"{'' if seen == 1 else 's'} recorded of the "
                      f"{len(TRIAGEABLE_FIELDS)} ATRIA uses, and at least "
                      f"{MIN_FIELDS_TO_TRIAGE} are needed.")
            if unmeasured:
                reason += f" Please record: {', '.join(unmeasured)}."
            if uncollected:
                reason += (f" Not available from this source: "
                           f"{', '.join(uncollected)}.")
            reason += " Clinician assessment required"

        # RF12 — ambiguity across the three gates, supplied by the caller because
        # it needs the pathway model. Layer 0 stays free of it by taking a number.
        ambiguity = patient.get("_pathway_ambiguity")
        severity = patient.get("_pathway_severity", 0.0) or 0.0
        ambiguous = bool(
            ambiguity is not None and ambiguity >= AMBIGUITY_THRESHOLD
            and severity >= 0.5 and not hard_stop
        )
        if ambiguous and not reason:
            reason = (f"RF12 ambiguous presentation — {ambiguity:.0%} overlap between "
                      f"pathways at {severity:.0%} severity; cannot classify. "
                      f"Urgent clinician review")

        return GateResult(tuple(fired), tuple(unresolved), tuple(sorted(all_imputed)),
                          hard_stop, ambiguous, reason, seen,
                          tuple(skipped), self.version)


_default: RuleTable | None = None


def gate(patient: dict, available: set[str] | None = None) -> GateResult:
    """Evaluate the shared rule table. Safe to call from anywhere, including offline."""
    global _default
    if _default is None:
        _default = RuleTable()
    return _default.evaluate(patient, available)
