"""
Latency, measured rather than claimed.

The solution slide already promises sub-400 ms. This reports p50/p95/p99 for the
full arrival path (Layer 0 gate + Layer 1 score + conformal set) and the vitals
path (Layer 2 trajectory + ratchet), under normal load and a 3x surge.
"""
from __future__ import annotations

import numpy as np

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from service.clock import build_events
from service.queue import QueueEngine

BUDGET_MS = 400


def measure(scorer: AcuityScorer, *, n: int = 120, surge: float = 1.0) -> dict:
    q = QueueEngine(scorer)
    arrivals: list[float] = []
    vitals: list[float] = []
    for e in build_events(generate(n, seed=77), surge=surge):
        before = len(q.latencies)
        if e.kind == "arrival":
            q.on_arrival(e)
            arrivals.extend(q.latencies[before:])
        else:
            q.on_vitals(e)
            vitals.extend(q.latencies[before:])

    def pct(xs):
        if not xs:
            return {}
        a = np.asarray(xs)
        return {"n": len(a), "p50": round(float(np.percentile(a, 50)), 2),
                "p95": round(float(np.percentile(a, 95)), 2),
                "p99": round(float(np.percentile(a, 99)), 2),
                "max": round(float(a.max()), 2)}

    return {"surge": surge, "arrival_ms": pct(arrivals), "vitals_ms": pct(vitals)}


def main() -> None:
    scorer = AcuityScorer().fit(generate(3000, seed=3))
    print(f"{'load':<10} {'path':<10} {'n':>6} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}")
    print("-" * 62)
    worst = 0.0
    for surge in (1.0, 3.0):
        r = measure(scorer, surge=surge)
        label = "normal" if surge == 1.0 else "3x surge"
        for path in ("arrival_ms", "vitals_ms"):
            s = r[path]
            if not s:
                continue
            worst = max(worst, s["p95"])
            print(f"{label:<10} {path[:-3]:<10} {s['n']:>6} {s['p50']:>8.2f} "
                  f"{s['p95']:>8.2f} {s['p99']:>8.2f} {s['max']:>8.2f}")
    print("-" * 62)
    verdict = "within" if worst < BUDGET_MS else "OVER"
    print(f"worst p95 {worst:.1f} ms — {verdict} the {BUDGET_MS} ms budget")


if __name__ == "__main__":
    main()
