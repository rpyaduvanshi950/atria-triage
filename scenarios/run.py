"""Run every scenario through the real engine and report what happened."""
from __future__ import annotations

from data.loaders.synthetic import generate
from layer1.model import AcuityScorer
from scenarios.seeds import ALL
from service.clock import build_events
from service.queue import QueueEngine


def play(scenario, scorer, *, degraded: bool = False, surge: float = 1.0) -> QueueEngine:
    q = QueueEngine(scorer)
    q.degraded = degraded
    for e in build_events(scenario.build(), surge=surge):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)
    return q


def main() -> None:
    scorer = AcuityScorer().fit(generate(3000, seed=3))

    for s in ALL:
        degraded = s.number == "06"
        surge = 3.0 if s.number == "04" else 1.0
        q = play(s, scorer, degraded=degraded, surge=surge)
        snap = q.snapshot()

        print(f"\n{'=' * 74}\nScenario {s.number} — {s.name}")
        print(f"covers: {s.covers}")
        if degraded:
            print("running with the model service DOWN")
        print("-" * 74)

        for r in snap["rows"][: 6 if s.number == "04" else 3]:
            arrow = f" (from {r['band_before']})" if r["band_before"] else ""
            why = r["red_flag"] or "; ".join(r["reasons"]) or r["needs_measurement"] or "—"
            print(f"  band {r['band']}{arrow:<9} {r['state']:<10} {r['confidence']:<9} {why[:52]}")
            if r["missing"]:
                print(f"       missing: {', '.join(r['missing'])}")

        if s.number == "05" and snap["rows"]:
            sid = snap["rows"][0]["stay_id"]
            entry = q.override(sid, 4, "reassessed_at_bedside", "nurse.demo")
            print(f"\n  clinician override: band {entry['frm']} -> {entry['to']}"
                  f" ({entry['reason_code']}, {entry['clinician']})")
            last = q.audit.entries[-1]
            print(f"  audit seq {last.seq} kind={last.kind} hash={last.hash[:12]}"
                  f" prev={last.prev_hash[:12]}")

        intact, note = q.audit.verify()
        extra = f" | p95 {snap['p95_ms']} ms" if s.number == "04" else ""
        print(f"\n  {len(q.audit)} audit entries, {note}{extra}")
        assert intact, "audit chain broken"


if __name__ == "__main__":
    main()
