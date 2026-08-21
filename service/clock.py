"""
Replay clock — turns a static dataset into a live-feeling ED.

Events (arrivals, vitals readings) are ordered by their real timestamps and
replayed against a virtual clock running `speed` times faster than wall time.
A surge multiplier resamples arrivals to stress the queue without needing more
data. Used by the demo, the surge scenario and the latency measurements.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

import pandas as pd

from contracts.schema import Dataset


@dataclass(frozen=True)
class Event:
    at: pd.Timestamp
    kind: str          # "arrival" | "vitals"
    stay_id: int
    payload: dict


def build_events(ds: Dataset, *, surge: float = 1.0) -> list[Event]:
    """Flatten a dataset into a time-ordered event stream."""
    events: list[Event] = []
    stays = ds.edstays.set_index("stay_id")
    triage = ds.triage.set_index("stay_id")

    for stay_id, row in stays.iterrows():
        tri = triage.loc[stay_id].to_dict() if stay_id in triage.index else {}
        events.append(Event(row["intime"], "arrival", int(stay_id),
                            {**{k: v for k, v in row.items()}, **tri}))

    if ds.vitalsign is not None:
        for _, r in ds.vitalsign.iterrows():
            events.append(Event(r["charttime"], "vitals", int(r["stay_id"]), r.to_dict()))

    events.sort(key=lambda e: (pd.Timestamp(e.at), e.kind != "arrival"))

    if surge != 1.0 and events:
        events = _compress(events, surge)
    return events


def _compress(events: list[Event], surge: float) -> list[Event]:
    """Squeeze the same arrivals into 1/surge of the time — a `surge`x volume spike."""
    t0 = pd.Timestamp(events[0].at)
    out = []
    for e in events:
        offset = (pd.Timestamp(e.at) - t0) / surge
        out.append(Event(t0 + offset, e.kind, e.stay_id, e.payload))
    return out


class ReplayClock:
    def __init__(self, events: Iterable[Event], *, speed: float = 120.0):
        self.events = list(events)
        self.speed = speed
        self.now: pd.Timestamp | None = self.events[0].at if self.events else None

    async def stream(self) -> AsyncIterator[Event]:
        """Yield events, sleeping the scaled gap between them."""
        prev: pd.Timestamp | None = None
        for e in self.events:
            at = pd.Timestamp(e.at)
            if prev is not None:
                gap = (at - prev).total_seconds() / self.speed
                if gap > 0:
                    await asyncio.sleep(min(gap, 2.0))
            prev = at
            self.now = at
            yield e
