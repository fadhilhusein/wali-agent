"""The guard's own durable records, in SQLite.

Kept apart from the environment on purpose: the guard must not depend on what an environment
says it has paid. Holds the active mandate (signed, and re-verified on every use), the ledger of
payments the guard executed (for the weekly limit and the double-payment check), proposal
timestamps (for the rate limit), and review items for the owner.

Pending proposals and confirmation tokens are NOT stored here. They live in memory only, so a
restart cancels every open confirmation.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path

from pydantic import AwareDatetime

from wali.models import Model

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id TEXT PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL,
    activated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS executions (
    approval_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL UNIQUE, supplier_id TEXT NOT NULL,
    amount TEXT NOT NULL, currency TEXT NOT NULL, proposed_by TEXT NOT NULL,
    executed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT NOT NULL, reason_code TEXT NOT NULL,
    reason TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


class ReviewItem(Model):
    id: int
    invoice_id: str
    reason_code: str
    reason: str
    created_by: str
    created_at: AwareDatetime
    status: str


def _stamp(moment: dt.datetime) -> str:
    """UTC with fixed precision, so stored timestamps compare correctly as text."""
    if moment.tzinfo is None:
        raise ValueError("Timestamps must be timezone-aware")
    return moment.astimezone(dt.UTC).isoformat(timespec="microseconds")


class GuardStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    # --- Mandates ------------------------------------------------------------------------

    def next_mandate_id(self) -> str:
        with self._lock:
            self._conn.execute(
                "INSERT INTO counters VALUES ('mandate', 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1"
            )
            value = self._conn.execute(
                "SELECT value FROM counters WHERE name = 'mandate'"
            ).fetchone()[0]
            return f"m-{value:03d}"

    def activate_mandate(self, mandate_id: str, payload: str, now: dt.datetime) -> None:
        """Store a signed mandate as the only active one."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("UPDATE mandates SET active = 0")
                self._conn.execute(
                    "INSERT INTO mandates VALUES (?, ?, 1, ?)", (mandate_id, payload, _stamp(now))
                )
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def active_mandate_payload(self) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM mandates WHERE active = 1").fetchone()
            return None if row is None else row["payload"]

    # --- Executed payments ---------------------------------------------------------------

    def record_execution(
        self,
        *,
        approval_id: str,
        invoice_id: str,
        supplier_id: str,
        amount: Decimal,
        currency: str,
        proposed_by: str,
        now: dt.datetime,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (approval_id, invoice_id, supplier_id, str(amount), currency, proposed_by,
                 _stamp(now)),
            )  # fmt: skip

    def paid_since(self, since: dt.datetime) -> Decimal:
        with self._lock:
            rows = self._conn.execute(
                "SELECT amount FROM executions WHERE executed_at > ?", (_stamp(since),)
            )
            return sum((Decimal(row["amount"]) for row in rows), Decimal("0"))

    def invoice_paid(self, invoice_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM executions WHERE invoice_id = ?", (invoice_id,)
            ).fetchone()
            return row is not None

    # --- Rate limit ----------------------------------------------------------------------

    def record_proposal(self, user_id: str, now: dt.datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO proposal_events (user_id, at) VALUES (?, ?)", (user_id, _stamp(now))
            )

    def proposals_since(self, user_id: str, since: dt.datetime) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM proposal_events WHERE user_id = ? AND at > ?",
                (user_id, _stamp(since)),
            ).fetchone()[0]

    # --- Review items --------------------------------------------------------------------

    def add_review_item(
        self, *, invoice_id: str, reason_code: str, reason: str, created_by: str, now: dt.datetime
    ) -> ReviewItem:
        """Add an open review item, or return the existing open one for the same invoice and
        reason so that repeated attempts do not flood the owner."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM review_items WHERE invoice_id = ? AND reason_code = ? "
                "AND status = 'open'",
                (invoice_id, reason_code),
            ).fetchone()
            if row is None:
                cursor = self._conn.execute(
                    "INSERT INTO review_items (invoice_id, reason_code, reason, created_by, "
                    "created_at, status) VALUES (?, ?, ?, ?, ?, 'open')",
                    (invoice_id, reason_code, reason, created_by, _stamp(now)),
                )
                row = self._conn.execute(
                    "SELECT * FROM review_items WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            return ReviewItem.model_validate(dict(row))

    def review_items(self) -> list[ReviewItem]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM review_items ORDER BY id")
            return [ReviewItem.model_validate(dict(row)) for row in rows]
