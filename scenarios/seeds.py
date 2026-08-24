"""
The six demo scenarios, as a runnable seed file.

Never click through a live demo you cannot reproduce. Each scenario builds a
deterministic patient (or shift) and asserts what the system should do, so the
video can be recorded against a script and re-recorded identically.

Run:  .venv/bin/python -m scenarios.seeds
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from contracts.schema import Dataset, EDSTAYS_COLS, TRIAGE_COLS, VITALSIGN_COLS, conform

T0 = pd.Timestamp("2026-03-14 09:00:00")


def _patient(stay_id: int, *, age: float, gender: str, complaint: str,
             vitals: dict, acuity: int = 3, transport: str = "walk-in",
             trajectory: list[dict] | None = None, arrive_offset: int = 0) -> dict:
    arrived = T0 + pd.Timedelta(minutes=arrive_offset)
    stay = dict(subject_id=stay_id, stay_id=stay_id, intime=arrived, outtime=pd.NaT,
                gender=gender, age=age, race=None, arrival_transport=transport,
                disposition=None)
    triage = dict(subject_id=stay_id, stay_id=stay_id, acuity=acuity,
                  chiefcomplaint=complaint, pain=vitals.pop("pain", 4), **vitals)
    rows = []
    for i, step in enumerate(trajectory or [], start=1):
        rows.append(dict(subject_id=stay_id, stay_id=stay_id,
                         charttime=arrived + pd.Timedelta(minutes=15 * i),
                         rhythm=None, pain=None, **step))
    return dict(stay=stay, triage=triage, vitals=rows)


def _dataset(parts: list[dict], name: str) -> Dataset:
    return Dataset(
        source=f"scenario:{name}",
        edstays=conform(pd.DataFrame([p["stay"] for p in parts]), EDSTAYS_COLS),
        triage=conform(pd.DataFrame([p["triage"] for p in parts]), TRIAGE_COLS),
        vitalsign=conform(pd.DataFrame([r for p in parts for r in p["vitals"]]), VITALSIGN_COLS),
        trainable=False,
        not_trainable_reason="scenario fixtures are for demonstration, not fitting",
    )


# --- 01 the quiet one -------------------------------------------------------

def quiet_one() -> Dataset:
    """
    58F, atypical presentation, no chest pain, borderline vitals. Static triage
    puts her at 3. Her trajectory escalates her before anyone re-checked.
    Concretises the 12.7% silent-MI statistic on the problem slide.
    """
    return _dataset([_patient(
        901001, age=58, gender="F", complaint="nausea and fatigue", acuity=3,
        vitals=dict(heartrate=88, resprate=18, o2sat=97, sbp=128, dbp=78, temperature=98.4, pain=2),
        trajectory=[
            dict(heartrate=94, resprate=19, o2sat=96, sbp=122, dbp=74, temperature=98.4),
            dict(heartrate=106, resprate=22, o2sat=94, sbp=112, dbp=68, temperature=98.5),
            dict(heartrate=118, resprate=25, o2sat=92, sbp=100, dbp=62, temperature=98.6),
        ])], "quiet_one")


# --- 02 paediatric threshold ------------------------------------------------

def paediatric() -> Dataset:
    """
    A 3-year-old at 38.5 C — the exact example the brief names. Adult-calibrated
    thresholds read these vitals as normal; the age-banded path does not.
    """
    return _dataset([_patient(
        901002, age=3, gender="M", complaint="fever and fast breathing", acuity=4,
        vitals=dict(heartrate=148, resprate=36, o2sat=95, sbp=88, dbp=52, temperature=101.3, pain=3),
        trajectory=[
            dict(heartrate=156, resprate=40, o2sat=93, sbp=84, dbp=50, temperature=101.7),
            dict(heartrate=164, resprate=44, o2sat=91, sbp=80, dbp=48, temperature=102.0),
        ])], "paediatric")


# --- 03 zero history --------------------------------------------------------

def zero_history() -> Dataset:
    """First presentation, no record, two vitals never taken."""
    return _dataset([_patient(
        901003, age=44, gender="M", complaint="flank pain", acuity=3,
        vitals=dict(heartrate=None, resprate=None, o2sat=96, sbp=134, dbp=82, temperature=98.9, pain=8),
        trajectory=[dict(heartrate=None, resprate=None, o2sat=96, sbp=132, dbp=80, temperature=98.8)],
    )], "zero_history")


# --- 04 surge ---------------------------------------------------------------

def surge(n: int = 45) -> Dataset:
    """Three times normal arrival rate. Built from the calibrated generator."""
    from data.loaders.synthetic import generate
    return generate(n, seed=404, hours=1.4)


# --- 05 the nurse disagrees -------------------------------------------------

def override_case() -> Dataset:
    """An escalation a clinician will downgrade, to exercise the audit trail."""
    return _dataset([_patient(
        901005, age=67, gender="F", complaint="dizziness", acuity=3,
        vitals=dict(heartrate=104, resprate=20, o2sat=95, sbp=104, dbp=64, temperature=98.2, pain=3),
        trajectory=[
            dict(heartrate=118, resprate=23, o2sat=93, sbp=92, dbp=58, temperature=98.3),
            dict(heartrate=124, resprate=24, o2sat=92, sbp=88, dbp=56, temperature=98.4),
        ])], "override")


# --- 06 lights out ----------------------------------------------------------

def lights_out() -> Dataset:
    """
    A confirmed red-flag patient, to be run with the model service killed.
    Layer 0 must still gate.
    """
    return _dataset([_patient(
        901006, age=71, gender="M", complaint="collapse", acuity=2, transport="ambulance",
        vitals=dict(heartrate=126, resprate=28, o2sat=86, sbp=84, dbp=50, temperature=97.1, pain=0),
        trajectory=[dict(heartrate=132, resprate=30, o2sat=84, sbp=78, dbp=46, temperature=97.0)],
    )], "lights_out")


# --- 07 the ambiguous one ---------------------------------------------------

def ambiguous() -> Dataset:
    """
    Hypothermia and trauma together — the case clinical review raised.

    Two gates are closing at once and the treatments conflict: a vasopressor for
    the shock constricts already-vasoconstricted peripheral vessels and drives
    necrosis. The system should be *certain* this patient is critical and
    *honest* that it cannot say which pathway is killing them.
    """
    return _dataset([_patient(
        901007, age=41, gender="M", complaint="found collapsed outdoors", acuity=2,
        transport="ambulance",
        vitals=dict(heartrate=132, resprate=26, o2sat=92, sbp=82, dbp=60,
                    temperature=92.5, pain=5),
        trajectory=[
            dict(heartrate=138, resprate=28, o2sat=90, sbp=78, dbp=56, temperature=92.0),
            dict(heartrate=141, resprate=30, o2sat=89, sbp=74, dbp=52, temperature=91.6),
        ])], "ambiguous")


@dataclass(frozen=True)
class Scenario:
    number: str
    name: str
    build: Callable[[], Dataset]
    covers: str


ALL = [
    Scenario("01", "The quiet one", quiet_one,
             "ambiguous presentation; escalation from trajectory, not snapshot"),
    Scenario("02", "Paediatric threshold", paediatric,
             "paediatric case; age-banded vs adult-calibrated scoring"),
    Scenario("03", "Zero history", zero_history,
             "no prior record; uncertainty surfaced; unknown is not normal"),
    Scenario("04", "Three times normal", surge,
             "surge behaviour; latency and queue aging under load"),
    Scenario("05", "The nurse disagrees", override_case,
             "clinician override; what the audit log records"),
    Scenario("06", "Lights out", lights_out,
             "degraded mode; Layer 0 gates with no model"),
    Scenario("07", "The ambiguous one", ambiguous,
             "RF12 abstention; diagnostic uncertainty separate from triage uncertainty; "
             "competing pathologies with conflicting treatment"),
]
