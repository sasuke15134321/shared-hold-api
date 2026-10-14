import hashlib
import hmac
import secrets
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class HoldReceipt:
    hold_id: str
    content_hash: str
    size: int
    created_at: str
    created_by: str
    access_token: str


class SharedHold:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._init()

    def _con(self):
        c = sqlite3.connect(self.db_path, timeout=5)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _init(self):
        with closing(self._con()) as c:
            with c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS holds (
                        hold_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        payload BLOB NOT NULL,
                        access_token_hash TEXT
                    )
                """)
                columns = {
                    row[1] for row in c.execute("PRAGMA table_info(holds)")
                }
                if "access_token_hash" not in columns:
                    c.execute(
                        "ALTER TABLE holds ADD COLUMN access_token_hash TEXT"
                    )

    def hold(self, payload, *, created_by):
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(created_by, str) or not created_by.strip():
            raise ValueError("created_by required")

        content_hash = hashlib.sha256(payload).hexdigest()
        hold_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        access_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(
            access_token.encode("utf-8")
        ).hexdigest()

        with closing(self._con()) as c:
            with c:
                c.execute(
                    """
                    INSERT INTO holds (
                        hold_id, created_at, created_by,
                        content_hash, size, payload, access_token_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hold_id, created_at, created_by,
                        content_hash, len(payload), payload, token_hash
                    ),
                )

        return HoldReceipt(
            hold_id, content_hash, len(payload),
            created_at, created_by, access_token
        )

    def get(self, hold_id, *, access_token=None):
        if not isinstance(access_token, str) or not access_token:
            raise KeyError(hold_id)

        with closing(self._con()) as c:
            row = c.execute(
                """
                SELECT content_hash, size, payload, access_token_hash
                FROM holds WHERE hold_id = ?
                """,
                (hold_id,),
            ).fetchone()

        if row is None:
            raise KeyError(hold_id)

        content_hash, size, payload, token_hash = row

        if token_hash is None:
            raise KeyError(hold_id)

        supplied_hash = hashlib.sha256(
            access_token.encode("utf-8")
        ).hexdigest()

        if not hmac.compare_digest(supplied_hash, token_hash):
            raise KeyError(hold_id)

        payload = bytes(payload)
        if (
            len(payload) != size
            or hashlib.sha256(payload).hexdigest() != content_hash
        ):
            raise RuntimeError("integrity failure")

        return payload

    def discover(self):
        with closing(self._con()) as c:
            return c.execute(
                """
                SELECT hold_id, created_at, created_by,
                       content_hash, size
                FROM holds ORDER BY created_at, hold_id
                """
            ).fetchall()

    def discover_page(self, *, limit=100, offset=0):
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer in [1, 100]")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        with closing(self._con()) as c:
            return c.execute(
                """
                SELECT hold_id, created_at, created_by,
                       content_hash, size
                FROM holds ORDER BY created_at, hold_id
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    def count(self):
        with closing(self._con()) as c:
            return c.execute(
                "SELECT COUNT(*) FROM holds"
            ).fetchone()[0]
