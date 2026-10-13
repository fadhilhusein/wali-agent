"""The deterministic payment policy. Plain code decides; the model has no say here.

``evaluate`` is a pure function of its arguments. It never reads the environment, the clock, or
any key except the public key it is handed. Rules run in a fixed order and the first failure
wins. Any exception becomes ``Deny(INTERNAL_ERROR)``: when in doubt, nothing is paid.

Order of the rules:

 1. The mandate is validly signed, not expired, for this business, and allows payments.
 2. The principal's role may propose (and, once the amount is known, may propose that much).
 3. The invoice exists, is a payable, is open, and was not already paid.
 4. The supplier is named in the mandate.
 5. The supplier's registered account is verified, and the invoice does not ask for another one.
 6. The invoice is not a duplicate of another invoice from the same supplier.
 7. The amount is within the per-payment limit, and the last 7 days plus this amount are within
    the weekly limit (this is what stops a large payment being split into small ones).
 8. The balance covers the payment. Dropping below the cash buffer needs the owner.
 9. An amount more than 30 percent above the supplier's average needs the owner.
10. The principal has not made too many proposals in the last hour.
11. An amount above ``confirm_above``, any warning above, or suspected injected instructions
    means the owner must confirm. Otherwise the payment is allowed.

Rules 4, 5 and 6 are hard denials that also raise a review item for the owner. No confirmation
can override them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from wali.guard.mandate import Mandate, mandate_problem
from wali.guard.signing import canonical_json
from wali.models import Currency, Invoice, Model, Money, NonEmptyStr, Principal, Role, Supplier

ReasonCode = Literal[
    "MANDATE_INVALID",
    "MANDATE_EXPIRED",
    "ROLE_NOT_ALLOWED",
    "INVOICE_INVALID",
    "DUPLICATE_PAYMENT",
    "DUPLICATE_INVOICE",
    "NEW_SUPPLIER",
    "SUPPLIER_ACCOUNT_MISMATCH",
    "OVER_PAYMENT_LIMIT",
    "OVER_WEEK_LIMIT",
    "BELOW_CASH_BUFFER",
    "RATE_LIMITED",
    "INJECTION_SUSPECTED",
    "INTERNAL_ERROR",
]
WarningCode = Literal[
    "ABOVE_CONFIRM_THRESHOLD",
    "BELOW_CASH_BUFFER",
    "AMOUNT_ABOVE_SUPPLIER_AVERAGE",
    "NO_SUPPLIER_HISTORY",
    "INJECTION_SUSPECTED",
]

ANOMALY_RATIO = Decimal("1.3")
SPENDING_WINDOW = dt.timedelta(days=7)
RATE_WINDOW = dt.timedelta(hours=1)

_MESSAGES: dict[str, str] = {
    "MANDATE_INVALID": (
        "There is no valid spending mandate, so nothing can be paid. "
        "The owner needs to set one up and confirm it."
    ),
    "MANDATE_EXPIRED": (
        "The spending mandate has expired, so nothing can be paid. "
        "The owner needs to confirm a new one."
    ),
    "ROLE_NOT_ALLOWED": "Your role is not allowed to propose this payment. Please ask the owner.",
    "INVOICE_INVALID": (
        "I could not find an open supplier invoice with that id. "
        "Please check the invoice and try again."
    ),
    "DUPLICATE_PAYMENT": "This invoice has already been paid, so I will not pay it again.",
    "DUPLICATE_INVOICE": (
        "This invoice looks like a duplicate of another invoice from the same supplier. "
        "I did not pay it and flagged it for the owner to review."
    ),
    "NEW_SUPPLIER": (
        "This supplier is not in the spending mandate. I did not pay it and flagged it for the "
        "owner, who can add the supplier to the mandate."
    ),
    "SUPPLIER_ACCOUNT_MISMATCH": (
        "The bank account for this payment does not match the supplier's registered, verified "
        "account. I did not pay it and flagged it for the owner. Please confirm the account "
        "with the supplier through a contact you already trust."
    ),
    "OVER_PAYMENT_LIMIT": (
        "This amount is above the per-payment limit in the mandate. "
        "The owner can raise the limit by confirming a new mandate."
    ),
    "OVER_WEEK_LIMIT": (
        "With this payment, the total paid in the last 7 days would go over the weekly limit. "
        "Wait until earlier payments fall outside the week, or ask the owner to change the limit."
    ),
    "BELOW_CASH_BUFFER": "The balance is not enough to cover this payment.",
    "RATE_LIMITED": (
        "Too many payment proposals in the last hour. Please wait a while and try again."
    ),
    "INTERNAL_ERROR": (
        "Something went wrong while checking this payment, so nothing was paid. Please try again."
    ),
}
_OVER_ROLE_LIMIT = (
    "This amount is above what your role may propose. Please ask the owner to propose it."
)
_PAYMENTS_NOT_ALLOWED = "The current mandate does not allow payments. The owner can change it."


class PaymentProposal(Model):
    """A request to pay one invoice. It carries no amount or account: those are always taken
    from the environment's records, never from the request."""

    proposal_id: NonEmptyStr
    business_id: NonEmptyStr
    invoice_id: NonEmptyStr
    proposed_by: NonEmptyStr


class PaymentTerms(Model):
    """Exactly what would be paid. Approvals and confirmations are bound to its digest."""

    business_id: NonEmptyStr
    mandate_id: NonEmptyStr
    invoice_id: NonEmptyStr
    supplier_id: NonEmptyStr
    amount: Decimal
    currency: Currency
    destination_account: NonEmptyStr
    proposed_by: NonEmptyStr

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        # Normalise so that 100 and 100.00 give the same digest.
        payload["amount"] = format(self.amount.normalize(), "f")
        return hashlib.sha256(canonical_json(payload)).hexdigest()


class RiskWarning(Model):
    code: WarningCode
    message: str


class Allow(Model):
    terms: PaymentTerms
    balance_after: Decimal


class NeedsConfirmation(Model):
    terms: PaymentTerms
    balance_after: Decimal
    risk_warnings: list[RiskWarning]
    required_role: Role = "owner"


class Deny(Model):
    reason_code: ReasonCode
    user_message: str
    flag_for_review: bool = False


Decision = Allow | NeedsConfirmation | Deny


@dataclass(frozen=True)
class PolicyView:
    """A snapshot of everything the policy may look at, gathered by the guard service."""

    public_key: Ed25519PublicKey
    business_id: str
    invoice: Invoice | None
    supplier: Supplier | None
    # Other payable invoices of the same supplier, for the duplicate check.
    supplier_invoices: tuple[Invoice, ...]
    balance: Money
    # Total the guard has paid in the last 7 days.
    paid_last_7_days: Decimal
    # True when the guard's own ledger shows this invoice as paid.
    already_paid: bool
    proposals_last_hour: int
    proposals_per_hour: int
    # True when untrusted text looked like injected instructions: in this conversation
    # turn, or in the invoice or supplier record being paid.
    suspicious: bool = False


def _deny(code: ReasonCode, message: str | None = None, *, flag: bool = False) -> Deny:
    return Deny(reason_code=code, user_message=message or _MESSAGES[code], flag_for_review=flag)


def _normalised_number(number: str) -> str:
    return "".join(ch for ch in number.casefold() if ch.isalnum())


def find_duplicate(invoice: Invoice, others: tuple[Invoice, ...]) -> Invoice | None:
    """Another invoice of the same supplier with the same number, or the same amount and date."""
    number = _normalised_number(invoice.number)
    for other in others:
        if other.id == invoice.id or other.kind != "payable" or other.status == "void":
            continue
        if other.counterparty_id != invoice.counterparty_id:
            continue
        same_number = _normalised_number(other.number) == number
        same_amount_and_date = (
            other.amount == invoice.amount and other.issue_date == invoice.issue_date
        )
        if same_number or same_amount_and_date:
            return other
    return None


def _check_authority(
    proposal: PaymentProposal,
    mandate: Mandate | None,
    principal: Principal,
    public_key: Ed25519PublicKey,
    business_id: str,
    now: dt.datetime,
) -> Deny | None:
    """Rules 1 and 2 (role part). These need nothing from the environment."""
    problem = mandate_problem(mandate, public_key, business_id, now)
    if problem is not None:
        return _deny(problem)
    if "pay_invoice" not in mandate.allowed_actions:
        return _deny("MANDATE_INVALID", _PAYMENTS_NOT_ALLOWED)
    if not (principal.business_id == proposal.business_id == mandate.business_id):
        return _deny("ROLE_NOT_ALLOWED")
    if proposal.proposed_by != principal.user_id:
        return _deny("ROLE_NOT_ALLOWED")
    authority = mandate.role_authority.get(principal.role)
    if authority is None or not authority.can_propose:
        return _deny("ROLE_NOT_ALLOWED")
    return None


def check_authority(
    proposal: PaymentProposal,
    mandate: Mandate | None,
    principal: Principal,
    public_key: Ed25519PublicKey,
    business_id: str,
    now: dt.datetime,
) -> Deny | None:
    """Decide from the mandate and role alone whether a proposal is refused outright.

    The guard service calls this before reading anything from the environment, so a principal
    who may not propose learns nothing about invoices or balances.
    """
    try:
        return _check_authority(proposal, mandate, principal, public_key, business_id, now)
    except Exception:
        return _deny("INTERNAL_ERROR")


def _evaluate(
    proposal: PaymentProposal,
    mandate: Mandate | None,
    principal: Principal,
    view: PolicyView,
    now: dt.datetime,
) -> Decision:
    refused = _check_authority(proposal, mandate, principal, view.public_key, view.business_id, now)
    if refused is not None:
        return refused
    authority = mandate.role_authority[principal.role]

    # 3. The invoice.
    invoice = view.invoice
    if invoice is None or invoice.id != proposal.invoice_id or invoice.kind != "payable":
        return _deny("INVOICE_INVALID")
    if invoice.status == "paid" or view.already_paid:
        return _deny("DUPLICATE_PAYMENT")
    if invoice.status != "open" or invoice.currency != mandate.currency:
        return _deny("INVOICE_INVALID")

    # 2. The amount this role may propose.
    if authority.max_propose is not None and invoice.amount > authority.max_propose:
        return _deny("ROLE_NOT_ALLOWED", _OVER_ROLE_LIMIT)

    # 4. The supplier is in the mandate.
    supplier = view.supplier
    if (
        supplier is None
        or supplier.id != invoice.counterparty_id
        or supplier.id not in mandate.allowed_suppliers
    ):
        return _deny("NEW_SUPPLIER", flag=True)

    # 5. Only the registered, verified account. An account written on the invoice is never
    #    used, and one that differs from the registered account is a red flag.
    stated = invoice.stated_account
    if not supplier.account_verified or (
        stated is not None and stated.strip() != supplier.verified_account
    ):
        return _deny("SUPPLIER_ACCOUNT_MISMATCH", flag=True)

    # 6. Duplicate invoice.
    if find_duplicate(invoice, view.supplier_invoices) is not None:
        return _deny("DUPLICATE_INVOICE", flag=True)

    # 7. Limits.
    amount = invoice.amount
    if amount > mandate.limits.per_payment.amount:
        return _deny("OVER_PAYMENT_LIMIT")
    if view.paid_last_7_days + amount > mandate.limits.per_week.amount:
        return _deny("OVER_WEEK_LIMIT")

    # 8. Balance and cash buffer.
    if view.balance.currency != mandate.currency:
        raise ValueError("balance currency differs from the mandate currency")
    balance_after = view.balance.amount - amount
    if balance_after < 0:
        return _deny("BELOW_CASH_BUFFER")
    warnings: list[RiskWarning] = []
    if balance_after < mandate.min_cash_buffer.amount:
        warnings.append(
            RiskWarning(
                code="BELOW_CASH_BUFFER",
                message="After this payment the balance would be below your cash buffer.",
            )
        )

    # 9. Unusual amount for this supplier.
    average = supplier.avg_invoice_amount
    if average <= 0:
        warnings.append(
            RiskWarning(
                code="NO_SUPPLIER_HISTORY",
                message="There is no payment history for this supplier to compare against.",
            )
        )
    elif amount > average * ANOMALY_RATIO:
        warnings.append(
            RiskWarning(
                code="AMOUNT_ABOVE_SUPPLIER_AVERAGE",
                message="This amount is more than 30 percent above this supplier's average.",
            )
        )

    # 10. Rate limit.
    if view.proposals_last_hour >= view.proposals_per_hour:
        return _deny("RATE_LIMITED")

    # 11. Does the owner have to confirm?
    if view.suspicious:
        warnings.append(
            RiskWarning(
                code="INJECTION_SUSPECTED",
                message=(
                    "Text in this conversation or on this invoice looked like an attempt to "
                    "give the assistant instructions. Check this payment carefully."
                ),
            )
        )
    if amount > mandate.confirm_above.amount:
        warnings.append(
            RiskWarning(
                code="ABOVE_CONFIRM_THRESHOLD",
                message="This amount is above the level that always needs your confirmation.",
            )
        )

    terms = PaymentTerms(
        business_id=mandate.business_id,
        mandate_id=mandate.mandate_id,
        invoice_id=invoice.id,
        supplier_id=supplier.id,
        amount=amount,
        currency=invoice.currency,
        destination_account=supplier.verified_account,
        proposed_by=principal.user_id,
    )
    if warnings:
        return NeedsConfirmation(terms=terms, balance_after=balance_after, risk_warnings=warnings)
    return Allow(terms=terms, balance_after=balance_after)


def evaluate(
    proposal: PaymentProposal,
    mandate: Mandate | None,
    principal: Principal,
    view: PolicyView,
    now: dt.datetime,
) -> Decision:
    """Apply the policy to one proposal. Never raises: any error is a denial."""
    try:
        return _evaluate(proposal, mandate, principal, view, now)
    except Exception:
        return _deny("INTERNAL_ERROR")
