"""冷存台账：独立于在线库的 SQLite，在线记录被清理后台账仍保留。"""

import sqlite3
from contextlib import closing, contextmanager
from typing import List

from app.errors import DomainError

SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_ledger (
    run_id TEXT PRIMARY KEY,
    sample TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('FROZEN','PURGED','RESTORED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    frozen_at TEXT,
    purged_at TEXT,
    restored_at TEXT,
    result_sha256 TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    package_sha256 TEXT NOT NULL,
    hmac_algorithm TEXT,
    train_count INTEGER NOT NULL,
    review_count INTEGER NOT NULL,
    online_bytes INTEGER NOT NULL,
    reclaim_bytes INTEGER NOT NULL DEFAULT 0,
    restore_count INTEGER NOT NULL DEFAULT 0,
    manifest TEXT NOT NULL,
    train_summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_holds (
    hold_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    released_at TEXT,
    UNIQUE(run_id, subject)
);
CREATE INDEX IF NOT EXISTS holds_run ON audit_holds(run_id);
CREATE TABLE IF NOT EXISTS archive_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    time TEXT NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS archive_events_run ON archive_events(run_id, seq);
"""

STATES = ("FROZEN", "PURGED", "RESTORED")


class ArchiveStore:
    def __init__(self, path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        try:
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        except sqlite3.OperationalError as exc:
            if (getattr(exc, "sqlite_errorcode", 0) & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise DomainError("STORE_BUSY", 503) from exc
            raise

    def get(self, run_id: str) -> sqlite3.Row | None:
        with closing(self.connect()) as db:
            return db.execute("SELECT * FROM archive_ledger WHERE run_id = ?", (run_id,)).fetchone()

    def require(self, run_id: str) -> sqlite3.Row:
        row = self.get(run_id)
        if row is None:
            raise DomainError("ARCHIVE_UNKNOWN", 404)
        return row

    def list(self) -> List[sqlite3.Row]:
        with closing(self.connect()) as db:
            return list(db.execute("SELECT * FROM archive_ledger ORDER BY created_at, run_id"))

    def active_holds(self, run_id: str) -> List[sqlite3.Row]:
        with closing(self.connect()) as db:
            return list(db.execute(
                "SELECT * FROM audit_holds WHERE run_id = ? AND released_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at",
                (run_id, _now()),
            ))

    def holds(self, run_id: str | None = None, *, include_released: bool = False) -> List[sqlite3.Row]:
        sql = "SELECT * FROM audit_holds"
        clauses, params = [], []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if not include_released:
            clauses.append("released_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at"
        with closing(self.connect()) as db:
            return list(db.execute(sql, params))

    def events(self, run_id: str | None = None, after: int = 0, limit: int = 100) -> List[sqlite3.Row]:
        if run_id is None:
            sql = "SELECT * FROM archive_events WHERE seq > ? ORDER BY seq LIMIT ?"
            params = (after, limit)
        else:
            sql = "SELECT * FROM archive_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?"
            params = (run_id, after, limit)
        with closing(self.connect()) as db:
            return list(db.execute(sql, params))


def add_event(db, run_id, time, level, code, message, detail=None):
    db.execute(
        "INSERT INTO archive_events (run_id,time,level,code,message,detail) VALUES (?,?,?,?,?,?)",
        (run_id, time, level, code, message, detail),
    )


def _now() -> str:
    from app.manifest import clock

    return clock()
