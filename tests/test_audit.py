"""Layer 3: the audit trail must be append-only and tamper-evident."""
from dataclasses import asdict

from layer3.audit import GENESIS, AuditLog, Entry


def _log():
    log = AuditLog()
    log.append("arrival", 1, "09:00", band=3)
    log.append("escalation", 1, "09:31", frm=3, to=1, reasons=["SpO2 falling"])
    log.append("override", 1, "09:33", frm=1, to=3, reason_code="reassessed")
    return log


def test_chain_starts_from_genesis():
    assert _log().entries[0].prev_hash == GENESIS


def test_each_entry_embeds_its_predecessor():
    entries = _log().entries
    for a, b in zip(entries, entries[1:]):
        assert b.prev_hash == a.hash


def test_an_intact_chain_verifies():
    intact, note = _log().verify()
    assert intact and "intact" in note


def test_editing_a_record_is_detected():
    log = _log()
    old = log.entries[1]
    log.entries[1] = Entry(**{**asdict(old), "payload": {**old.payload, "to": 5}})
    intact, note = log.verify()
    assert not intact and "modified" in note


def test_deleting_a_record_is_detected():
    log = _log()
    del log.entries[1]
    intact, note = log.verify()
    assert not intact and "chain broken" in note


def test_an_override_records_who_and_why():
    log = _log()
    entry = log.for_stay(1)[-1]
    assert entry.kind == "override"
    assert entry.payload["reason_code"] == "reassessed"


def test_queue_writes_every_decision_to_the_log():
    from data.loaders.synthetic import generate
    from layer1.model import AcuityScorer
    from service.clock import build_events
    from service.queue import QueueEngine

    q = QueueEngine(AcuityScorer().fit(generate(900, seed=3)))
    for e in build_events(generate(15, seed=42)):
        q.on_arrival(e) if e.kind == "arrival" else q.on_vitals(e)

    assert len(q.audit) >= 15                      # at least one per arrival
    assert q.audit.verify()[0]
    assert q.snapshot()["audit_intact"]
