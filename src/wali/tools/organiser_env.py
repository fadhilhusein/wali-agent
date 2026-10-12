"""Slot for the organisers' simulated environment.

We do not yet know whether the organisers provide an environment or what its API looks like
(see docs/assumptions.md, U1). When that is known, implement the ``FinancialEnvironment``
protocol here. Nothing else in the code base needs to change.
"""

from __future__ import annotations

from datetime import date
from typing import NoReturn

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

_MESSAGE = (
    "The organisers' environment is not implemented yet because its API is unknown. "
    "Use wali.tools.sim_env.SimEnvironment, or implement this adapter once the details arrive."
)


def _not_implemented() -> NoReturn:
    raise NotImplementedError(_MESSAGE)


class OrganiserEnvironment:
    def get_balance(self, p: Principal) -> Money:
        _not_implemented()

    def list_transactions(
        self, p: Principal, start: date, end: date, limit: int = 200
    ) -> list[BankTransaction]:
        _not_implemented()

    def list_invoices(
        self,
        p: Principal,
        kind: str,
        status: str | None = None,
        due_before: date | None = None,
    ) -> list[Invoice]:
        _not_implemented()

    def get_supplier(self, p: Principal, supplier_id: str) -> Supplier:
        _not_implemented()

    def get_book_entries(self, p: Principal, start: date, end: date) -> list[BookEntry]:
        _not_implemented()

    def record_book_entry(self, p: Principal, entry: NewBookEntry) -> BookEntry:
        _not_implemented()

    def execute_payment(self, approval: GuardApproval) -> PaymentResult:
        _not_implemented()
