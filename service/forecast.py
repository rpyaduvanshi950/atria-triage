"""
Operations & Flow — PRD section 13.

Demand against staffed capacity for the next hour, in one glance.

Two rules keep this honest. Treatment is **capped at staffed spaces**, because
you cannot treat more people than you have places and staff for. Waiting is
**not capped**, because a queue can grow past capacity and pretending otherwise
would hide the exact condition worth seeing.

A staffed space is a treatment space that is both physically available and
safely staffed. It is not a licensed bed, and conflating the two is how capacity
dashboards end up lying.

This informs ordering *within* an ESI band only. It can never move a patient
across one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HORIZON_MINUTES = 60
STEP_MINUTES = 15

#: Treatment spaces one nurse can safely cover. Site-configurable.
SPACES_PER_NURSE = 3

#: Applied when an integration is down, so we plan for less than we think we have.
ROSTER_DOWN_MARGIN = 0.8
BEDS_DOWN_MARGIN = 0.85


@dataclass
class FlowInputs:
    waiting: int
    inside: int
    nurses: int
    arrival_rate_per_hour: float
    physical_spaces: int
    records_connected: bool = True
    beds_connected: bool = True
    roster_connected: bool = True
    vitals_connected: bool = True
    #: fraction of assessed patients recently sent inside
    decision_rate: float = 0.45


@dataclass
class ForecastPoint:
    minute: int
    in_treatment: int
    waiting: int


@dataclass
class Forecast:
    points: list[ForecastPoint]
    staffed_spaces: int
    open_spaces: int
    arrivals_next_hour: int
    wait_buffer_minutes: float
    state: str                      # Steady | Busy | Surge
    explanation: str
    assumptions: list[str] = field(default_factory=list)
    version: str = "forecast-0.1.0"

    def as_dict(self) -> dict:
        return dict(
            points=[p.__dict__ for p in self.points],
            staffed_spaces=self.staffed_spaces, open_spaces=self.open_spaces,
            arrivals_next_hour=self.arrivals_next_hour,
            wait_buffer_minutes=round(self.wait_buffer_minutes, 1),
            state=self.state, explanation=self.explanation,
            assumptions=list(self.assumptions), version=self.version)


def staffed_spaces(f: FlowInputs) -> tuple[int, list[str]]:
    """Capacity, reduced conservatively wherever we cannot see clearly."""
    notes: list[str] = []
    capacity = float(min(f.physical_spaces, f.nurses * SPACES_PER_NURSE))
    if not f.roster_connected:
        capacity *= ROSTER_DOWN_MARGIN
        notes.append(f"roster offline — staffing reduced by "
                     f"{(1 - ROSTER_DOWN_MARGIN):.0%} as a safety margin")
    if not f.beds_connected:
        capacity *= BEDS_DOWN_MARGIN
        notes.append(f"bed feed offline — spaces reduced by "
                     f"{(1 - BEDS_DOWN_MARGIN):.0%}")
    return max(0, int(capacity)), notes


def flow_state(waiting: int, capacity: int) -> str:
    if capacity <= 0:
        return "Surge"
    ratio = waiting / capacity
    if ratio < 1.0:
        return "Steady"
    return "Busy" if ratio < 2.0 else "Surge"


def project(f: FlowInputs) -> Forecast:
    capacity, notes = staffed_spaces(f)
    if not f.records_connected:
        notes.append("records offline — history gaps flagged, nothing invented")
    if not f.vitals_connected:
        notes.append("vitals feed offline — manual verification, missing "
                     "essentials abstain")

    inside, waiting = f.inside, f.waiting
    points = [ForecastPoint(0, min(inside, capacity), waiting)]

    per_step_arrivals = f.arrival_rate_per_hour * (STEP_MINUTES / 60)
    for minute in range(STEP_MINUTES, HORIZON_MINUTES + 1, STEP_MINUTES):
        waiting += per_step_arrivals
        # patients move inside only where there is a staffed space to take them
        room = max(0, capacity - inside)
        moved = min(room, waiting * f.decision_rate)
        inside += moved
        waiting -= moved
        # and some finish and leave
        inside = max(0, inside - capacity * 0.18)
        points.append(ForecastPoint(minute, int(min(inside, capacity)),
                                    int(max(0, waiting))))

    open_spaces = max(0, capacity - f.inside)
    state = flow_state(f.waiting, capacity)
    ends_waiting = points[-1].waiting
    growing = ends_waiting > points[0].waiting

    if open_spaces == 0 and growing:
        explanation = (f"All {capacity} staffed spaces are full and the queue is "
                       f"projected to grow to {ends_waiting} within the hour.")
    elif open_spaces == 0:
        explanation = (f"All {capacity} staffed spaces are full, but the queue is "
                       f"projected to hold near {ends_waiting}.")
    elif growing:
        explanation = (f"{open_spaces} staffed spaces open now, and the queue is "
                       f"still projected to grow to {ends_waiting} within the hour.")
    else:
        explanation = (f"{open_spaces} staffed spaces open and the queue is "
                       f"projected to fall to {ends_waiting} within the hour.")

    return Forecast(points=points, staffed_spaces=capacity, open_spaces=open_spaces,
                    arrivals_next_hour=int(round(f.arrival_rate_per_hour)),
                    wait_buffer_minutes=_wait_buffer(f, capacity),
                    state=state, explanation=explanation, assumptions=notes)


def _wait_buffer(f: FlowInputs, capacity: int) -> float:
    """
    Median remaining minutes before non-critical waiting patients cross the
    site wait threshold. A planning signal; it says nothing clinical.
    """
    threshold = 120.0
    if capacity <= 0:
        return 0.0
    throughput_per_min = (capacity * 0.18) / STEP_MINUTES or 0.01
    return max(0.0, threshold - (f.waiting / throughput_per_min))
