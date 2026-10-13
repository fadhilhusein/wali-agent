"""Simulated financial environment backed by SQLite.

SIMULATION ONLY. There is no real bank, no real money, and no real data behind this class.

Role scopes enforced here (in addition to anything the guard checks):

- owner and bookkeeper: balance, bank feed, invoices, suppliers, books; may record book entries.
- staff: sales book entries and receivable invoices only. No balance, bank feed, payables,
  suppliers, or payroll.

``execute_payment`` is the only method that moves money. It trusts nothing but the guard's
signature: it checks the signature, expiry, single use, and that the destination is the
supplier's registered and verified account.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from wali.guard.keys import load_public_key
from wali.guard.signing import verify_payload
from wali.models import (
    BankTransaction,
    BookEntry,
    Currency,
    GuardApproval,
    Invoice,
    Model,
    Money,
    NewBookEntry,
    NonEmptyStr,
    PaymentRecord,
    PaymentResult,
    Principal,
    Role,
    Supplier,
)
from wali.tools.base import AccessDenied, NotFound, ToolFailure, ToolTimeout

MAX_TRANSACTION_LIMIT = 1000
INVOICE_KINDS = ("payable", "receivable")
INVOICE_STATUSES = ("open", "paid", "void")
PROTOCOL_METHODS = (
    "get_balance",
    "list_transactions",
    "list_invoices",
    "get_supplier",
    "get_book_entries",
    "record_book_entry",
    "execute_payment",
)

_SCHEMA = """
CREATE TABLE business (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL,
    opening_balance TEXT NOT NULL, opening_date TEXT NOT NULL, as_of_date TEXT NOT NULL
);
CREATE TABLE users (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, business_id TEXT NOT NULL
);
CREATE TABLE suppliers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, verified_account TEXT NOT NULL,
    account_verified INTEGER NOT NULL, avg_invoice_amount TEXT NOT NULL
);
CREATE TABLE bank_transactions (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, amount TEXT NOT NULL, direction TEXT NOT NULL,
    counterparty TEXT NOT NULL, memo TEXT NOT NULL, reference TEXT NOT NULL
);
CREATE TABLE book_entries (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, amount TEXT NOT NULL, direction TEXT NOT NULL,
    category TEXT NOT NULL, description TEXT NOT NULL, invoice_id TEXT,
    reconciled INTEGER NOT NULL, created_by TEXT
);
CREATE TABLE invoices (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, counterparty_id TEXT NOT NULL,
    counterparty_name TEXT NOT NULL, number TEXT NOT NULL, amount TEXT NOT NULL,
    currency TEXT NOT NULL, issue_date TEXT NOT NULL, due_date TEXT NOT NULL,
    status TEXT NOT NULL, late_fee_bearing INTEGER NOT NULL,
    stated_account TEXT, document_text TEXT
);
CREATE TABLE payments (
    approval_id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL UNIQUE, supplier_id TEXT NOT NULL,
    amount TEXT NOT NULL, currency TEXT NOT NULL, destination_account TEXT NOT NULL,
    transaction_id TEXT NOT NULL, executed_at TEXT NOT NULL
);
"""


class SeedDataError(ValueError):
    """Raised when a seed file is missing or malformed."""


class _Business(Model):
    id: NonEmptyStr
    name: str
    currency: Currency
    opening_balance: Decimal
    opening_date: dt.date
    as_of_date: dt.date


class _User(Model):
    id: NonEmptyStr
    name: str
    role: Role
    business_id: NonEmptyStr


def _read_rows(seed_dir: Path, name: str, model: type[Model]) -> list[Model]:
    """Read ``name``.csv and validate every row. Columns the model does not know are ignored;
    an empty cell in an optional column counts as missing."""
    path = seed_dir / f"{name}.csv"
    if not path.is_file():
        raise SeedDataError(f"Seed file not found: {path}")
    fields = model.model_fields
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line, raw in enumerate(csv.DictReader(handle), start=2):
            known = {
                k: v for k, v in raw.items() if k in fields and (v != "" or fields[k].is_required())
            }
            try:
                rows.append(model.model_validate(known))
            except ValidationError as exc:
                bad = ", ".join(str(err["loc"][0]) for err in exc.errors())
                raise SeedDataError(f"{path.name} line {line}: invalid {bad}") from None
    return rows


def _load_seed(conn: sqlite3.Connection, seed_dir: Path) -> None:
    businesses = _read_rows(seed_dir, "business", _Business)
    if len(businesses) != 1:
        raise SeedDataError("business.csv must contain exactly one business")
    b = businesses[0]
    conn.execute(
        "INSERT INTO business VALUES (?, ?, ?, ?, ?, ?)",
        (b.id, b.name, b.currency, str(b.opening_balance), b.opening_date.isoformat(),
         b.as_of_date.isoformat()),
    )  # fmt: skip
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, ?, ?)",
        [(u.id, u.name, u.role, u.business_id) for u in _read_rows(seed_dir, "users", _User)],
    )
    conn.executemany(
        "INSERT INTO suppliers VALUES (?, ?, ?, ?, ?)",
        [
            (s.id, s.name, s.verified_account, int(s.account_verified), str(s.avg_invoice_amount))
            for s in _read_rows(seed_dir, "suppliers", Supplier)
        ],
    )
    conn.executemany(
        "INSERT INTO bank_transactions VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (t.id, t.date.isoformat(), str(t.amount), t.direction, t.counterparty, t.memo,
             t.reference)
            for t in _read_rows(seed_dir, "bank_transactions", BankTransaction)
        ],
    )  # fmt: skip
    conn.executemany(
        "INSERT INTO book_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        [
            (e.id, e.date.isoformat(), str(e.amount), e.direction, e.category, e.description,
             e.invoice_id, int(e.reconciled))
            for e in _read_rows(seed_dir, "books", BookEntry)
        ],
    )  # fmt: skip
    conn.executemany(
        "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (i.id, i.kind, i.counterparty_id, i.counterparty_name, i.number, str(i.amount),
             i.currency, i.issue_date.isoformat(), i.due_date.isoformat(), i.status,
             int(i.late_fee_bearing), i.stated_account, i.document_text)
            for i in _read_rows(seed_dir, "invoices", Invoice)
        ],
    )  # fmt: skip


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _rejected(message: str) -> PaymentResult:
    return PaymentResult(status="rejected", message=message)


class SimEnvironment:
    """A ``FinancialEnvironment`` for exactly one synthetic business."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        guard_public_key: str,
        *,
        fail_rate: float = 0.0,
        seed: int = 42,
        clock: Callable[[], dt.datetime] = _utc_now,
        staff_book_categories: frozenset[str] = frozenset({"sales"}),
    ) -> None:
        if not 0.0 <= fail_rate <= 1.0:
            raise ValueError("fail_rate must be between 0 and 1")
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._public_key = load_public_key(guard_public_key)
        self._fail_rate = fail_rate
        self._rng = random.Random(seed)
        self._forced_failures: dict[str, list[type[ToolFailure]]] = {}
        self._clock = clock
        self._staff_book_categories = staff_book_categories

        row = self._conn.execute("SELECT * FROM business").fetchone()
        if row is None:
            raise SeedDataError("The database holds no business")
        self._business = _Business.model_validate(dict(row))

    @classmethod
    def create(
        cls, seed_dir: Path, guard_public_key: str, *, db_path: Path | str = ":memory:", **options
    ) -> SimEnvironment:
        """Build a fresh database from the seed files. Refuses to overwrite an existing file."""
        if db_path != ":memory:":
            if Path(db_path).exists():
                raise FileExistsError(f"{db_path} already exists. Use SimEnvironment.open().")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        try:
            conn.executescript(_SCHEMA)
            conn.execute("BEGIN")
            _load_seed(conn, Path(seed_dir))
            conn.execute("COMMIT")
            return cls(conn, guard_public_key, **options)
        except BaseException:
            conn.close()
            if db_path != ":memory:":
                Path(db_path).unlink(missing_ok=True)
            raise

    @classmethod
    def open(cls, db_path: Path | str, guard_public_key: str, **options) -> SimEnvironment:
        """Open a database created earlier by ``create``."""
        if not Path(db_path).is_file():
            raise FileNotFoundError(f"{db_path} does not exist. Use SimEnvironment.create().")
        conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        try:
            return cls(conn, guard_public_key, **options)
        except BaseException:
            conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def use_clock(self, clock: Callable[[], dt.datetime]) -> None:
        """Replace the clock, for an application that derives its clock from the seed data."""
        self._clock = clock

    @property
    def business_id(self) -> str:
        return self._business.id

    @property
    def currency(self) -> str:
        return self._business.currency

    @property
    def as_of_date(self) -> dt.date:
        """The last day covered by the seed data."""
        return self._business.as_of_date

    # --- Failure injection ---------------------------------------------------------------

    def inject_failure(self, method: str, times: int = 1, *, timeout: bool = False) -> None:
        """Make the next ``times`` calls of ``method`` fail. For tests and scripted dialogues."""
        if method not in PROTOCOL_METHODS:
            raise ValueError(f"Unknown method: {method}")
        kind = ToolTimeout if timeout else ToolFailure
        self._forced_failures.setdefault(method, []).extend([kind] * times)

    def clear_failures(self) -> None:
        """Drop any targeted failures that were injected but not used up."""
        self._forced_failures.clear()

    def _maybe_fail(self, method: str) -> None:
        """Runs before any state is read or changed, so a failed call never has side effects."""
        forced = self._forced_failures.get(method)
        if forced:
            raise forced.pop(0)(f"Simulated failure in {method}. Nothing was changed.")
        if self._fail_rate and self._rng.random() < self._fail_rate:
            kind = ToolTimeout if self._rng.random() < 0.5 else ToolFailure
            raise kind(f"Simulated failure in {method}. Nothing was changed.")

    # --- Access control ------------------------------------------------------------------

    def _authorize(self, p: Principal, *allowed: str) -> None:
        """The principal must be a known user of this business whose stored role matches the
        claimed one, and that role must be allowed. A claimed role alone is never enough."""
        if p.business_id != self._business.id:
            raise AccessDenied("This business is not available to you.")
        row = self._conn.execute(
            "SELECT role, business_id FROM users WHERE id = ?", (p.user_id,)
        ).fetchone()
        if row is None or row["role"] != p.role or row["business_id"] != p.business_id:
            raise AccessDenied("Your identity could not be verified.")
        if p.role not in allowed:
            raise AccessDenied("Your role does not allow this.")

    # --- Reads ---------------------------------------------------------------------------

    def _balance(self) -> Decimal:
        total = self._business.opening_balance
        for row in self._conn.execute("SELECT amount, direction FROM bank_transactions"):
            amount = Decimal(row["amount"])
            total += amount if row["direction"] == "in" else -amount
        return total

    def get_balance(self, p: Principal) -> Money:
        with self._lock:
            self._authorize(p, "owner", "bookkeeper")
            self._maybe_fail("get_balance")
            return Money(amount=self._balance(), currency=self._business.currency)

    def list_transactions(
        self, p: Principal, start: dt.date, end: dt.date, limit: int = 200
    ) -> list[BankTransaction]:
        with self._lock:
            self._authorize(p, "owner", "bookkeeper")
            self._maybe_fail("list_transactions")
            if start > end:
                raise ValueError("start must not be after end")
            if not 1 <= limit <= MAX_TRANSACTION_LIMIT:
                raise ValueError(f"limit must be between 1 and {MAX_TRANSACTION_LIMIT}")
            rows = self._conn.execute(
                "SELECT * FROM bank_transactions WHERE date BETWEEN ? AND ? "
                "ORDER BY date, id LIMIT ?",
                (start.isoformat(), end.isoformat(), limit),
            )
            return [BankTransaction.model_validate(dict(row)) for row in rows]

    def list_invoices(
        self,
        p: Principal,
        kind: str,
        status: str | None = None,
        due_before: dt.date | None = None,
    ) -> list[Invoice]:
        with self._lock:
            if kind not in INVOICE_KINDS:
                raise ValueError(f"kind must be one of {INVOICE_KINDS}")
            if status is not None and status not in INVOICE_STATUSES:
                raise ValueError(f"status must be one of {INVOICE_STATUSES}")
            if kind == "payable":
                self._authorize(p, "owner", "bookkeeper")
            else:
                self._authorize(p, "owner", "bookkeeper", "staff")
            self._maybe_fail("list_invoices")
            query, params = "SELECT * FROM invoices WHERE kind = ?", [kind]
            if status is not None:
                query += " AND status = ?"
                params.append(status)
            if due_before is not None:
                query += " AND due_date < ?"
                params.append(due_before.isoformat())
            rows = self._conn.execute(query + " ORDER BY due_date, id", params)
            return [Invoice.model_validate(dict(row)) for row in rows]

    def _supplier(self, supplier_id: str) -> Supplier | None:
        row = self._conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        return None if row is None else Supplier.model_validate(dict(row))

    def get_supplier(self, p: Principal, supplier_id: str) -> Supplier:
        with self._lock:
            self._authorize(p, "owner", "bookkeeper")
            self._maybe_fail("get_supplier")
            supplier = self._supplier(supplier_id)
            if supplier is None:
                raise NotFound("No supplier with that id.")
            return supplier

    def get_book_entries(self, p: Principal, start: dt.date, end: dt.date) -> list[BookEntry]:
        with self._lock:
            self._authorize(p, "owner", "bookkeeper", "staff")
            self._maybe_fail("get_book_entries")
            if start > end:
                raise ValueError("start must not be after end")
            rows = self._conn.execute(
                "SELECT id, date, amount, direction, category, description, invoice_id, "
                "reconciled FROM book_entries WHERE date BETWEEN ? AND ? ORDER BY date, id",
                (start.isoformat(), end.isoformat()),
            )
            entries = [BookEntry.model_validate(dict(row)) for row in rows]
            if p.role == "staff":
                entries = [e for e in entries if e.category in self._staff_book_categories]
            return entries

    # --- Writes --------------------------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def record_book_entry(self, p: Principal, entry: NewBookEntry) -> BookEntry:
        """Add a books entry. This never touches the bank balance."""
        with self._lock:
            self._authorize(p, "owner", "bookkeeper")
            self._maybe_fail("record_book_entry")
            with self._transaction():
                if entry.invoice_id is not None:
                    found = self._conn.execute(
                        "SELECT 1 FROM invoices WHERE id = ?", (entry.invoice_id,)
                    ).fetchone()
                    if found is None:
                        raise NotFound("No invoice with that id.")
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM book_entries WHERE created_by IS NOT NULL"
                ).fetchone()[0]
                recorded = BookEntry(id=f"be-new-{count + 1:04d}", **entry.model_dump())
                self._conn.execute(
                    "INSERT INTO book_entries VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (recorded.id, recorded.date.isoformat(), str(recorded.amount),
                     recorded.direction, recorded.category, recorded.description,
                     recorded.invoice_id, p.user_id),
                )  # fmt: skip
                return recorded

    def execute_payment(self, approval: GuardApproval) -> PaymentResult:
        """Pay one invoice, but only with a valid, unexpired, unused approval from the guard,
        and only to the supplier's registered and verified account."""
        with self._lock:
            self._maybe_fail("execute_payment")
            if not isinstance(approval, GuardApproval):
                return _rejected("No valid approval was provided.")
            if not verify_payload(self._public_key, approval.signing_payload(), approval.signature):
                return _rejected("The approval signature is not valid.")
            now = self._clock()
            if now.tzinfo is None:
                raise ValueError("The environment clock must return a timezone-aware datetime.")
            if now >= approval.expires_at:
                return _rejected("The approval has expired.")
            if approval.business_id != self._business.id:
                return _rejected("The approval is for a different business.")

            with self._transaction():
                used = self._conn.execute(
                    "SELECT 1 FROM payments WHERE approval_id = ?", (approval.approval_id,)
                ).fetchone()
                if used is not None:
                    return _rejected("The approval was already used.")

                row = self._conn.execute(
                    "SELECT * FROM invoices WHERE id = ?", (approval.invoice_id,)
                ).fetchone()
                if row is None:
                    return _rejected("The invoice does not exist.")
                invoice = Invoice.model_validate(dict(row))
                if invoice.kind != "payable":
                    return _rejected("The invoice is not a payable.")
                if invoice.status != "open":
                    return _rejected("The invoice is not open. It may already be paid.")
                if (
                    invoice.counterparty_id != approval.supplier_id
                    or invoice.amount != approval.amount
                    or invoice.currency != approval.currency
                ):
                    return _rejected("The approval does not match the invoice.")

                supplier = self._supplier(approval.supplier_id)
                if supplier is None:
                    return _rejected("The supplier does not exist.")
                if not supplier.account_verified:
                    return _rejected("The supplier's account is not verified.")
                if approval.destination_account != supplier.verified_account:
                    return _rejected("The destination is not the supplier's registered account.")

                if self._balance() < approval.amount:
                    return _rejected("The balance is not sufficient.")

                count = self._conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
                transaction_id = f"bt-pay-{count + 1:04d}"
                self._conn.execute(
                    "INSERT INTO bank_transactions VALUES (?, ?, ?, 'out', ?, ?, ?)",
                    (transaction_id, now.date().isoformat(), str(approval.amount), supplier.name,
                     f"Payment {invoice.number}", invoice.number),
                )  # fmt: skip
                self._conn.execute(
                    "UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice.id,)
                )
                self._conn.execute(
                    "INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (approval.approval_id, invoice.id, supplier.id, str(approval.amount),
                     approval.currency, supplier.verified_account, transaction_id,
                     now.isoformat()),
                )  # fmt: skip
                return PaymentResult(
                    status="success",
                    transaction_id=transaction_id,
                    message=f"Paid invoice {invoice.number} to the registered account.",
                )

    # --- Inspection (not part of the protocol, never exposed to the model) ---------------

    def list_payments(self) -> list[PaymentRecord]:
        """Every payment executed in this simulation. For tests and evaluation only."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM payments ORDER BY executed_at, approval_id")
            return [PaymentRecord.model_validate(dict(row)) for row in rows]

    def principals(self) -> dict[str, Principal]:
        """One principal per role, taken from the stored users. For interfaces that let a demo
        user pick a role; a real interface maps its own authenticated users instead."""
        with self._lock:
            rows = self._conn.execute("SELECT id, role, business_id FROM users ORDER BY id")
            found: dict[str, Principal] = {}
            for row in rows:
                found.setdefault(
                    row["role"],
                    Principal(user_id=row["id"], role=row["role"], business_id=row["business_id"]),
                )
            return found
