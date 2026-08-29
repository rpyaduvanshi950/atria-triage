"""
Layer 3 — the audit trail.

Append-only and hash-chained: every record embeds the hash of its predecessor,
so any later edit or deletion breaks the chain and is detectable. This is the
answer to clinical accountability, and it is cheap.

Each entry carries enough to reconstruct why the system said what it said:
model version, rule-table version, the input snapshot, the score, the conformal
interval, the recommendation, the human decision and a structured reason code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from layer3.store import AuditStore

GENESIS = "0" * 64


@dataclass(frozen=True)
class Entry:
    seq: int
    at: str
    kind: str                       # arrival | escalation | override | signoff | degraded
    stay_id: int
    prev_hash: str
    payload: dict[str, Any] = field(default_factory=dict)
    hash: str = ""

    def digest(self) -> str:
        body = {k: v for k, v in asdict(self).items() if k != "hash"}
        blob = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class AuditLog:
    """
    The chain, optionally backed by durable storage.

    Without a store this is in-memory and dies with the process, which is fine
    for a test. With one, entries are written to SQLite as they are appended and
    reloaded on startup — so the chain a restart inherits is the chain an auditor
    would read off the disk.
    """

    def __init__(self, path: Path | str | None = None, store: "AuditStore | None" = None):
        self.entries: list[Entry] = []
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store = store
        if store is not None:
            # Rebuild from disk so a restart continues the same chain rather
            # than silently starting a new one that verifies fine and proves
            # nothing about what came before it.
            self.entries = [Entry(seq=r["seq"], at=r["at"], kind=r["kind"],
                                  stay_id=r["stay_id"], prev_hash=r["prev_hash"],
                                  payload=r["payload"], hash=r["hash"])
                            for r in store.all()]

    # --- writing -----------------------------------------------------------

    def append(self, kind: str, stay_id: int, at: str, **payload: Any) -> Entry:
        prev = self.entries[-1].hash if self.entries else GENESIS
        draft = Entry(seq=len(self.entries), at=str(at), kind=kind,
                      stay_id=int(stay_id), prev_hash=prev, payload=payload)
        entry = Entry(**{**asdict(draft), "hash": draft.digest()})
        self.entries.append(entry)
        if self.store is not None:
            self.store.append(asdict(entry))
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(asdict(entry), default=str) + "\n")
        return entry

    # --- reading -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)

    def for_stay(self, stay_id: int) -> list[Entry]:
        return [e for e in self.entries if e.stay_id == stay_id]

    def verify(self) -> tuple[bool, str]:
        """Walk the chain. Returns (intact, explanation)."""
        prev = GENESIS
        for e in self.entries:
            if e.prev_hash != prev:
                return False, f"chain broken at seq {e.seq}: predecessor hash does not match"
            if e.digest() != e.hash:
                return False, f"entry {e.seq} has been modified since it was written"
            prev = e.hash
        return True, f"chain intact across {len(self.entries)} entries"

    def as_rows(self, limit: int = 50) -> list[dict]:
        return [
            dict(seq=e.seq, at=e.at, kind=e.kind, stay_id=e.stay_id,
                 hash=e.hash[:12], prev=e.prev_hash[:12], **e.payload)
            for e in self.entries[-limit:]
        ]
