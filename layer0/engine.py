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
    fired: tuple[FiredRule, ...] = ()
    imputed_fields: tuple[str, ...] = ()
    rules_version: str = ""

    @property
    def is_red(self) -> bool:
        return bool(self.fired)

    @property
    def priority(self) -> int:
        """Any fired flag forces the most urgent band."""
        return 1 if self.fired else 5

    def explain(self) -> str:
        if not self.fired:
            return "no red flags"
        return "; ".join(r.reason() for r in self.fired)


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

    def evaluate(self, patient: dict) -> GateResult:
        fired: list[FiredRule] = []
        all_imputed: set[str] = set()

        for rule in self.rules:
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
                if not OPS[cond["op"]](value, cond.get("value")):
                    ok = False
                    break

            if ok:
                fired.append(FiredRule(rule["id"], rule["name"], rule["citation"], tuple(imputed)))
                all_imputed.update(imputed)

        return GateResult(tuple(fired), tuple(sorted(all_imputed)), self.version)


_default: RuleTable | None = None


def gate(patient: dict) -> GateResult:
    """Evaluate the shared rule table. Safe to call from anywhere, including offline."""
    global _default
    if _default is None:
        _default = RuleTable()
    return _default.evaluate(patient)
