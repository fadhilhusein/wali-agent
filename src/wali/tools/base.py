"""The single interface through which Wali reaches any financial environment."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from wali.models import (
    BankTransaction,
    BookEntry,
    GuardApproval,
    Invoice,
    Money,
    NewBookEntry,
    PaymentResult,
    Principal,
    Supplier,
)


class AccessDenied(PermissionError):
    """The principal's role or business does not allow this call."""


class NotFound(LookupError):
    """The requested record does not exist."""


class ToolFailure(RuntimeError):
    """The environment failed to answer. Nothing was changed; the call may be retried."""


class ToolTimeout(ToolFailure):
    """The environment did not answer in time. Nothing was changed."""


@runtime_checkable
class FinancialEnvironment(Protocol):
    """Every read enforces the principal's role scope. Only ``execute_payment`` moves money,
    and only when given an approval signed by the guard."""

    def get_balance(self, p: Principal) -> Money: ...

    def list_transactions(
        self, p: Principal, start: date, end: date, limit: int = 200
    ) -> list[BankTransaction]: ...

    def list_invoices(
        self,
        p: Principal,
        kind: str,
        status: str | None = None,
        due_before: date | None = None,
    ) -> list[Invoice]: ...

    def get_supplier(self, p: Principal, supplier_id: str) -> Supplier: ...

    def get_book_entries(self, p: Principal, start: date, end: date) -> list[BookEntry]: ...

    def record_book_entry(self, p: Principal, entry: NewBookEntry) -> BookEntry: ...

    def execute_payment(self, approval: GuardApproval) -> PaymentResult: ...
