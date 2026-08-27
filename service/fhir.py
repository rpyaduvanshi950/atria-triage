"""
FHIR R4 mapping — PRD section 15.4.

ATRIA keeps its own native record regardless of what it exports. A hospital
integration is a projection of our data, never the source of truth for it: if
the mapping loses provenance or a missingness flag, that loss must not reach the
safety layers.

`RiskAssessment` and `GuidanceResponse` are deliberately *not* emitted by
default. Publishing a machine recommendation as a FHIR resource makes it look
like a clinical finding in the receiving system, and that needs integration
governance review first.
"""
from __future__ import annotations

from typing import Any

#: LOINC codes for the vitals we carry.
LOINC = {
    "heartrate": ("8867-4", "Heart rate", "/min"),
    "resprate": ("9279-1", "Respiratory rate", "/min"),
    "o2sat": ("59408-5", "Oxygen saturation", "%"),
    "sbp": ("8480-6", "Systolic blood pressure", "mm[Hg]"),
    "dbp": ("8462-4", "Diastolic blood pressure", "mm[Hg]"),
    "temperature": ("8310-5", "Body temperature", "Cel"),
}

RESOURCE_MAP = {
    "patient identity": "Patient",
    "ed arrival and status": "Encounter",
    "vitals and point-in-time findings": "Observation",
    "problem list / history": "Condition",
    "medicines": "MedicationStatement | MedicationRequest",
    "allergies": "AllergyIntolerance",
    "clinical task / reassessment": "Task",
    "assessment output": "RiskAssessment | GuidanceResponse (governance review required)",
}


def observation(stay_id: int, field: str, value: float | None,
                observed_at: str, source: str = "device") -> dict[str, Any]:
    """One vital as a FHIR R4 Observation, with missingness made explicit."""
    code, display, unit = LOINC[field]
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final" if value is not None else "registered",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org",
                             "code": code, "display": display}]},
        "subject": {"reference": f"Patient/{stay_id}"},
        "encounter": {"reference": f"Encounter/{stay_id}"},
        "effectiveDateTime": observed_at,
        "performer": [{"display": source}],
    }
    if value is None:
        # Absent is recorded as absent. It is never rendered as a normal value,
        # and never omitted in a way a consumer could read as normal.
        resource["dataAbsentReason"] = {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
            "code": "not-performed", "display": "Not Performed"}]}
    else:
        resource["valueQuantity"] = {"value": value, "unit": unit,
                                     "system": "http://unitsofmeasure.org",
                                     "code": unit}
    return resource


def encounter(stay_id: int, arrived_at: str, status: str = "in-progress") -> dict[str, Any]:
    return {
        "resourceType": "Encounter", "status": status,
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": "EMER", "display": "emergency"},
        "subject": {"reference": f"Patient/{stay_id}"},
        "period": {"start": arrived_at},
    }


def reassessment_task(stay_id: int, due_at: str, esi: int) -> dict[str, Any]:
    return {
        "resourceType": "Task", "status": "requested", "intent": "order",
        "priority": "urgent" if esi <= 2 else "routine",
        "description": f"Reassess waiting patient (ESI {esi})",
        "for": {"reference": f"Patient/{stay_id}"},
        "encounter": {"reference": f"Encounter/{stay_id}"},
        "restriction": {"period": {"end": due_at}},
    }
