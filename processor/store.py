"""Small durable store. API keys are encrypted and excluded from API responses."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        key = self.directory / "secrets.key"
        if not key.exists():
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / "golden.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS entities (kind TEXT, id TEXT PRIMARY KEY, payload TEXT)")
        self.db.commit()

    def put(self, kind, value):
        value = dict(value)
        value.setdefault("id", uid())
        value.setdefault("created_at", now())
        value["updated_at"] = now()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO entities VALUES (?, ?, ?)",
                            (kind, value["id"], json.dumps(value)))
            self.db.commit()
        return value

    def get(self, kind, identity):
        with self.lock:
            row = self.db.execute("SELECT payload FROM entities WHERE kind=? AND id=?", (kind, identity)).fetchone()
        if row is None:
            raise KeyError(f"{kind.rstrip('s').title()} not found")
        return json.loads(row[0])

    def list(self, kind):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM entities WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind, identity):
        self.delete_many([(kind, identity)])

    def delete_many(self, entries):
        """Delete related records together, rolling back the group on failure."""
        with self.lock, self.db:
            self.db.executemany("DELETE FROM entities WHERE kind=? AND id=?", entries)

    def secret(self, connection):
        return self.cipher.decrypt(connection["secret"].encode()).decode() if connection.get("secret") else ""

    def seal(self, key):
        return self.cipher.encrypt(key.encode()).decode() if key else ""

    @staticmethod
    def public(connection):
        return {**{k: v for k, v in connection.items() if k != "secret"}, "has_key": bool(connection.get("secret"))}
