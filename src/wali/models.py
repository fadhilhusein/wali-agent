"""Pydantic models shared across modules. All money is ``Decimal``; amounts are always positive
and the direction says which way the money moves.

Text fields that come from outside the business (counterparty names, memos, descriptions,
invoice document text) are untrusted data and must never be treated as instructions.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Role = Literal["owner", "bookkeeper", "staff"]
Direction = Literal["in", "out"]
InvoiceKind = Literal["payable", "receivable"]
InvoiceStatus = Literal["open", "paid", "void"]
PaymentStatus = Literal["success", "rejected"]

PositiveAmount = Annotated[Decimal, Field(gt=0)]
NonNegativeAmount = Annotated[Decimal, Field(ge=0)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Principal(Model):
    """Who is acting. Set by the interface, never by the model."""

    user_id: NonEmptyStr
    role: Role
    business_id: NonEmptyStr


class Money(Model):
    amount: Decimal
    currency: Currency


class BankTransaction(Model):
    id: NonEmptyStr
    date: dt.date
    amount: PositiveAmount
    direction: Direction
    counterparty: str
    memo: str
    reference: str


class BookEntry(Model):
    id: NonEmptyStr
    date: dt.date
    amount: PositiveAmount
    direction: Direction
    category: NonEmptyStr
    description: str
    invoice_id: str | None = None
    reconciled: bool = False


class NewBookEntry(Model):
    """A books entry to be recorded. The environment assigns the id."""

    date: dt.date
    amount: PositiveAmount
    direction: Direction
    category: NonEmptyStr
    description: str
    invoice_id: str | None = None


class Invoice(Model):
    id: NonEmptyStr
    kind: InvoiceKind
    counterparty_id: NonEmptyStr
    counterparty_name: str
    number: NonEmptyStr
    amount: PositiveAmount
    currency: Currency
    issue_date: dt.date
    due_date: dt.date
    status: InvoiceStatus
    late_fee_bearing: bool = False
    # What the invoice document itself claims. Untrusted: never used as a payment destination.
    stated_account: str | None = None
    document_text: str | None = None


class Supplier(Model):
    id: NonEmptyStr
    name: str
    verified_account: NonEmptyStr
    account_verified: bool
    avg_invoice_amount: NonNegativeAmount


class MatchedPair(Model):
    bank_id: str
    book_id: str


class AmountMismatch(Model):
    bank_id: str
    book_id: str
    bank_amount: Decimal
    book_amount: Decimal
    difference: Decimal


class DuplicateGroup(Model):
    source: Literal["bank", "books"]
    ids: list[str]


class ReconciliationReport(Model):
    matched: list[MatchedPair]
    unmatched_bank: list[BankTransaction]
    unmatched_books: list[BookEntry]
    amount_mismatches: list[AmountMismatch]
    suspected_duplicates: list[DuplicateGroup]


class DailyBalance(Model):
    date: dt.date
    balance: Decimal


class CashflowForecast(Model):
    horizon_days: int = Field(ge=1)
    daily_balance: list[DailyBalance]
    lowest_balance: Decimal
    lowest_date: dt.date
    shortfall_days: list[dt.date]


class GuardApproval(Model):
    """A signed permission to pay one invoice. Only the guard can create a valid one."""

    approval_id: NonEmptyStr
    proposal_hash: NonEmptyStr
    business_id: NonEmptyStr
    invoice_id: NonEmptyStr
    supplier_id: NonEmptyStr
    amount: PositiveAmount
    currency: Currency
    destination_account: NonEmptyStr
    expires_at: AwareDatetime
    signature: str

    def signing_payload(self) -> dict[str, Any]:
        """Everything the signature covers: every field except the signature itself."""
        return self.model_dump(mode="json", exclude={"signature"})


class PaymentResult(Model):
    status: PaymentStatus
    transaction_id: str | None = None
    message: str


class PaymentRecord(Model):
    """One executed payment in the simulated ledger. Used for inspection and evaluation."""

    approval_id: str
    invoice_id: str
    supplier_id: str
    amount: Decimal
    currency: Currency
    destination_account: str
    transaction_id: str
    executed_at: AwareDatetime
