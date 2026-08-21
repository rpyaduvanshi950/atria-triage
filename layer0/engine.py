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


def tachycardia_threshold(patient: dict) -> float:
    """Age-banded tachycardia, PALS reference ranges."""
    age = patient.get("age")
    if age is None or age >= 12:
        return 130.0
    if age < 1:
        return 180.0
    if age < 5:
        return 160.0
    return 140.0


THRESHOLD_FNS = {
    "sbp_hypotension": sbp_hypotension_threshold,
    "tachycardia": tachycardia_threshold,
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
        if self.unresolved:
            return 2
        return 5

    def explain(self) -> str:
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
                needs = {c["field"] for c in rule["all_of"]}
                if not needs <= available:
                    skipped.append(rule["id"])
                    continue
            policy = rule.get("missing_policy", "absent")
            imputed: list[str] = []
            ok = True

            for cond in rule["all_of"]:
                value, was_imputed = self._resolve(patient, cond["field"], policy)
                if value is None:
                    ok = False
                    break
                if was_imputed:
                    imputed.append(cond["field"])
                limit = cond.get("value")
                if "value_fn" in cond:
                    limit = THRESHOLD_FNS[cond["value_fn"]](patient)
                if not OPS[cond["op"]](value, limit):
                    ok = False
                    break

            if ok:
                hit = FiredRule(rule["id"], rule["name"], rule["citation"], tuple(imputed))
                if imputed:
                    unresolved.append(hit)
                    all_imputed.update(imputed)
                else:
                    fired.append(hit)

        return GateResult(tuple(fired), tuple(unresolved), tuple(sorted(all_imputed)),
                          tuple(skipped), self.version)


_default: RuleTable | None = None


def gate(patient: dict, available: set[str] | None = None) -> GateResult:
    """Evaluate the shared rule table. Safe to call from anywhere, including offline."""
    global _default
    if _default is None:
        _default = RuleTable()
    return _default.evaluate(patient, available)
