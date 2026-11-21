import json
import sqlite3
from contextlib import closing, contextmanager

from app.errors import DomainError
from app.manifest import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    manifest TEXT NOT NULL,
    results TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    time TEXT NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_time TEXT
);
CREATE INDEX IF NOT EXISTS run_history ON runs(created_at DESC, id DESC);
"""


class Store:
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

    def read(self, run_id):
        with closing(self.connect()) as db:
            result = find(db, run_id)
        if result is None:
            raise DomainError("RUN_UNKNOWN", 404)
        return result

    def history(self):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT manifest FROM runs ORDER BY created_at DESC, id DESC LIMIT 50")
            return [json.loads(row["manifest"]) for row in rows]

    def events(self, after, limit):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after, limit))
            return [dict(row) for row in rows]


def find(db, run_id):
    row = db.execute("SELECT manifest, results FROM runs WHERE id = ?", (run_id,)).fetchone()
    return (json.loads(row["manifest"]), json.loads(row["results"])) if row else None


def add_run(db, manifest, results):
    db.execute("INSERT INTO runs VALUES (?, ?, ?, ?)", (
        manifest["run_id"], manifest["created_at"], canonical(manifest), canonical(results),
    ))


def add_events(db, run_id, events):
    db.executemany("""INSERT INTO events (run_id,time,level,code,message,source_time)
                    VALUES (?, ?, ?, ?, ?, ?)""", ((run_id, *event) for event in events))
