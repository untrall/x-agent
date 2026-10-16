"""One-agent durable SQLite records, inbox, outbox and event log."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS inbox (message_id TEXT PRIMARY KEY, sender TEXT NOT NULL, session_id TEXT NOT NULL, envelope TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox (message_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, envelope TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, type TEXT NOT NULL, session_id TEXT, peer_id TEXT, summary TEXT NOT NULL, payload TEXT NOT NULL);
        """)

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def get(self, kind: str, key: str) -> dict | None:
        row = self.connection.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row["data"]) if row else None

    def all(self, kind: str) -> list[dict]:
        rows = self.connection.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def put(self, kind: str, key: str, data: dict, db=None):
        (db or self.connection).execute("INSERT INTO records(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, key, json.dumps(data, ensure_ascii=False)))

    def event(self, timestamp: str, event_type: str, session_id: str | None, peer_id: str | None, summary: str, payload: dict | None = None, db=None):
        (db or self.connection).execute("INSERT INTO events(timestamp,type,session_id,peer_id,summary,payload) VALUES(?,?,?,?,?,?)", (timestamp, event_type, session_id, peer_id, summary, json.dumps(payload or {}, ensure_ascii=False)))

    def events(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def receive(self, envelope: dict) -> bool:
        with self.transaction() as db:
            cursor = db.execute("INSERT OR IGNORE INTO inbox(message_id,sender,session_id,envelope) VALUES(?,?,?,?)", (envelope["message_id"], envelope["sender_agent_id"], envelope["session_id"], json.dumps(envelope, ensure_ascii=False)))
            return cursor.rowcount == 1

    def pending_inbox(self) -> list[dict]:
        rows = self.connection.execute("""
            SELECT current.envelope FROM inbox AS current
            WHERE current.processed=0
              AND NOT EXISTS (
                SELECT 1 FROM inbox AS earlier
                WHERE earlier.session_id=current.session_id
                  AND earlier.rowid<current.rowid
                  AND earlier.processed<>1
              )
            ORDER BY current.rowid
        """).fetchall()
        return [json.loads(row["envelope"]) for row in rows]

    def blocked_inbox(self) -> list[str]:
        rows = self.connection.execute("SELECT message_id FROM inbox WHERE processed=2 ORDER BY rowid").fetchall()
        return [row["message_id"] for row in rows]

    def block(self, message_id: str, db=None):
        (db or self.connection).execute("UPDATE inbox SET processed=2 WHERE message_id=? AND processed=0", (message_id,))

    def retry_blocked(self, message_id: str) -> bool:
        cursor = self.connection.execute("UPDATE inbox SET processed=0 WHERE message_id=? AND processed=2", (message_id,))
        return cursor.rowcount == 1

    def session_binding(self, session_id: str) -> tuple[str, str] | None:
        row = self.connection.execute("SELECT sender,envelope FROM inbox WHERE session_id=? AND json_extract(envelope,'$.type')='REQUEST' LIMIT 1", (session_id,)).fetchone()
        if row is None:
            return None
        envelope = json.loads(row["envelope"])
        return row["sender"], envelope["request_id"]

    def mark_processed(self, message_id: str, db=None):
        (db or self.connection).execute("UPDATE inbox SET processed=1 WHERE message_id=?", (message_id,))

    def enqueue(self, envelope: dict, db=None):
        (db or self.connection).execute("INSERT OR IGNORE INTO outbox(message_id,recipient,envelope) VALUES(?,?,?)", (envelope["message_id"], envelope["recipient_agent_id"], json.dumps(envelope, ensure_ascii=False)))

    def pending_outbox(self) -> list[dict]:
        rows = self.connection.execute("""
            SELECT current.* FROM outbox AS current
            WHERE current.delivered=0
              AND NOT EXISTS (
                SELECT 1 FROM outbox AS earlier
                WHERE json_extract(earlier.envelope,'$.session_id')=json_extract(current.envelope,'$.session_id')
                  AND earlier.rowid<current.rowid
                  AND earlier.delivered=0
              )
            ORDER BY current.rowid
        """).fetchall()
        return [{**dict(row), "type": json.loads(row["envelope"])["type"], "envelope": json.loads(row["envelope"])} for row in rows]

    def queued_outbox(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid").fetchall()
        return [{**dict(row), "type": json.loads(row["envelope"])["type"], "envelope": json.loads(row["envelope"])} for row in rows]

    def delivered(self, message_id: str):
        self.connection.execute("UPDATE outbox SET delivered=1 WHERE message_id=?", (message_id,))

    def retry(self, message_id: str, at: float):
        self.connection.execute("UPDATE outbox SET attempts=attempts+1,next_attempt=? WHERE message_id=?", (at, message_id))
