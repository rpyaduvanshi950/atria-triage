"""
Durable storage for the audit trail.

SQLite, not Postgres. The trail must survive a restart or the hash chain proves
nothing — but a triage prototype should not need a database server running
beside it to be trustworthy, and SQLite gives durability, transactions and a
single portable file. Swapping in Postgres later means changing this module and
nothing else.

The chain is verified against what is *on disk*, not against what the process
remembers. That distinction is the whole point: an auditor checks the file.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq        INTEGER PRIMARY KEY,
    at         TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    stay_id    INTEGER NOT NULL,
    prev_hash  TEXT    NOT NULL,
    payload    TEXT    NOT NULL,
    hash       TEXT    NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_stay ON audit(stay_id);
CREATE INDEX IF NOT EXISTS audit_kind ON audit(kind);

-- Append-only, enforced by the database rather than by convention. An UPDATE or
-- DELETE raises, so tampering fails at the point of writing instead of being
-- detected later by a hash check nobody ran.
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit entries cannot be modified'); END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit entries cannot be deleted'); END;
"""


class AuditStore:
    """A durable, append-only home for audit entries."""

    def __init__(self, path: str | Path = "data/atria_audit.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # WAL so a reader (an auditor, the History tab) never blocks a writer.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")   # durability over speed
        self._db.executescript(SCHEMA)
        self._db.commit()

    # --- writing -------------------------------------------------------------

    def append(self, entry: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO audit (seq, at, kind, stay_id, prev_hash, payload, hash)"
            " VALUES (?,?,?,?,?,?,?)",
            (entry["seq"], str(entry["at"]), entry["kind"], int(entry["stay_id"]),
             entry["prev_hash"], json.dumps(entry["payload"], default=str),
             entry["hash"]),
        )
        self._db.commit()

    # --- reading -------------------------------------------------------------

    def __len__(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]

    def last(self) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        return self._row(row) if row else None

    def all(self) -> Iterator[dict[str, Any]]:
        for row in self._db.execute("SELECT * FROM audit ORDER BY seq"):
            yield self._row(row)

    def for_stay(self, stay_id: int) -> list[dict[str, Any]]:
        return [self._row(r) for r in self._db.execute(
            "SELECT * FROM audit WHERE stay_id = ? ORDER BY seq", (stay_id,))]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {"seq": row["seq"], "at": row["at"], "kind": row["kind"],
                "stay_id": row["stay_id"], "prev_hash": row["prev_hash"],
                "payload": json.loads(row["payload"]), "hash": row["hash"]}

    def close(self) -> None:
        self._db.close()
