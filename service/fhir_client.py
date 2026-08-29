"""
Reading from a FHIR R4 server.

`service/fhir.py` maps ATRIA outwards. This reads inwards: given a patient on a
FHIR endpoint, pull their Observations and turn them into the vitals row the
engine already understands. That is the whole of the integration surface — ATRIA
never writes to the record, and this module has no code that could.

Point it at a sandbox with:

    ATRIA_FHIR_BASE=https://hapi.fhir.org/baseR4

No base URL configured means the integration reports itself as not connected,
which is the correct answer rather than a crash. Every call is bounded by a
short timeout: a slow hospital interface must never hold up a triage decision,
so a failure here degrades to "vitals not retrieved" and Layer 0 carries on with
what was measured at the bedside.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from service.fhir import LOINC

BASE = os.environ.get("ATRIA_FHIR_BASE", "").rstrip("/")
TIMEOUT = float(os.environ.get("ATRIA_FHIR_TIMEOUT", "4.0"))

#: LOINC code -> the field name ATRIA uses internally.
BY_LOINC = {code: field for field, (code, _d, _u) in LOINC.items()}


class FHIRUnavailable(RuntimeError):
    """The server did not answer usefully. Never raised into a triage path."""


def configured() -> bool:
    return bool(BASE)


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not BASE:
        raise FHIRUnavailable("ATRIA_FHIR_BASE is not set")
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/fhir+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise FHIRUnavailable(str(exc)) from exc


def _entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [e.get("resource", {}) for e in bundle.get("entry", []) or []]


def vitals_for(patient_id: str, *, count: int = 40) -> dict[str, Any]:
    """
    The latest value of each vital ATRIA scores, plus what could not be found.

    Missingness is returned explicitly rather than as an absent key. A vital the
    remote server does not have is a fact the safety layers need — it is the
    difference between "SpO2 is fine" and "nobody has measured SpO2".
    """
    bundle = _get("Observation", {
        "patient": patient_id, "category": "vital-signs",
        "_sort": "-date", "_count": count,
    })
    return parse_observations(_entries(bundle))


def parse_observations(resources: list[dict[str, Any]]) -> dict[str, Any]:
    """Split out from `vitals_for` so it can be tested without a network."""
    out: dict[str, Any] = {}
    at: dict[str, str] = {}
    for res in resources:
        if res.get("resourceType") != "Observation":
            continue
        for coding in res.get("code", {}).get("coding", []):
            field = BY_LOINC.get(coding.get("code"))
            if field is None or field in out:
                continue  # sorted newest first, so the first hit is the latest
            value = res.get("valueQuantity", {}).get("value")
            if value is None:
                continue
            out[field] = float(value)
            at[field] = res.get("effectiveDateTime", "")
    return {
        "vitals": out,
        "observed_at": at,
        "missing": sorted(set(LOINC) - set(out)),
        "n_resources": len(resources),
    }


def patient(patient_id: str) -> dict[str, Any]:
    """Demographics ATRIA actually uses: age band and nothing more."""
    res = _get(f"Patient/{patient_id}")
    return {"id": res.get("id"), "birth_date": res.get("birthDate"),
            "gender": res.get("gender")}


def health() -> dict[str, Any]:
    """For the integrations panel. Never raises."""
    if not configured():
        return {"connected": False, "base": None,
                "note": "no FHIR server configured (set ATRIA_FHIR_BASE)"}
    try:
        meta = _get("metadata", {"_summary": "true"})
        return {"connected": True, "base": BASE,
                "fhir_version": meta.get("fhirVersion"),
                "software": (meta.get("software") or {}).get("name")}
    except FHIRUnavailable as exc:
        return {"connected": False, "base": BASE, "error": str(exc)}
