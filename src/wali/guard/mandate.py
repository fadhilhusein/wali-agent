"""The spending mandate: the owner's signed standing instructions to the guard.

A mandate is drafted from the owner's request, confirmed by the owner, then signed. Only a signed
mandate is ever used, and its signature, expiry, and business are checked on every use.

Two limits on authority are fixed here and cannot be granted by any mandate, because they come
from the role definitions of the business, not from the owner's preferences:

- only the owner can confirm;
- staff can never propose payments.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Literal, Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import AwareDatetime, Field, model_validator

from wali.guard.signing import canonical_json, sign_payload, verify_payload
from wali.models import Model, Money, NonEmptyStr, PositiveAmount, Role

MandateAction = Literal["pay_invoice", "record_book_entry"]
EscalationTrigger = Literal[
    "supplier_account_mismatch",
    "duplicate_invoice",
    "amount_over_30_percent_of_supplier_average",
    "new_supplier",
]
ALL_ESCALATIONS: list[EscalationTrigger] = [
    "supplier_account_mismatch",
    "duplicate_invoice",
    "amount_over_30_percent_of_supplier_average",
    "new_supplier",
]
MandateProblem = Literal["MANDATE_INVALID", "MANDATE_EXPIRED"]


class Limits(Model):
    per_payment: Money
    per_week: Money


class RoleAuthority(Model):
    can_propose: bool = False
    can_confirm: bool = False
    # Largest single payment this role may propose. None means no limit of its own.
    max_propose: PositiveAmount | None = None


class MandateTerms(Model):
    """Everything in a mandate except the signature."""

    mandate_id: NonEmptyStr
    business_id: NonEmptyStr
    issued_by: NonEmptyStr
    expires_at: AwareDatetime
    allowed_actions: list[MandateAction]
    limits: Limits
    allowed_suppliers: list[NonEmptyStr]
    role_authority: dict[Role, RoleAuthority]
    confirm_above: Money
    min_cash_buffer: Money
    # Recorded for transparency. The guard always applies all four checks.
    escalate_if: list[EscalationTrigger] = Field(default_factory=lambda: list(ALL_ESCALATIONS))

    @model_validator(mode="after")
    def _reject_nonsense(self) -> Self:
        per_payment, per_week = self.limits.per_payment, self.limits.per_week
        amounts = (per_payment, per_week, self.confirm_above, self.min_cash_buffer)
        if len({money.currency for money in amounts}) != 1:
            raise ValueError("all amounts must use one currency")
        if per_payment.amount <= 0 or per_week.amount <= 0:
            raise ValueError("limits must be greater than zero")
        if per_payment.amount > per_week.amount:
            raise ValueError("the per-payment limit cannot exceed the weekly limit")
        if self.confirm_above.amount < 0 or self.min_cash_buffer.amount < 0:
            raise ValueError("confirm_above and min_cash_buffer cannot be negative")
        for name in ("allowed_actions", "allowed_suppliers", "escalate_if"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates")

        owner = self.role_authority.get("owner")
        if owner is None or not (owner.can_propose and owner.can_confirm):
            raise ValueError("the owner must be able to propose and confirm")
        for role, authority in self.role_authority.items():
            if authority.can_confirm and role != "owner":
                raise ValueError("only the owner can confirm")
            if authority.can_propose and role == "staff":
                raise ValueError("staff cannot propose payments")
            if authority.max_propose is not None and authority.max_propose > per_payment.amount:
                raise ValueError("a role's limit cannot exceed the per-payment limit")
        return self

    @property
    def currency(self) -> str:
        return self.limits.per_payment.currency

    def signing_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"signature"})

    def digest(self) -> str:
        """Hash of the terms. A confirmation is bound to this value."""
        return hashlib.sha256(canonical_json(self.signing_payload())).hexdigest()


class Mandate(MandateTerms):
    signature: str


def sign_mandate(terms: MandateTerms, private_key: Ed25519PrivateKey) -> Mandate:
    payload = terms.signing_payload()
    return Mandate(**terms.model_dump(), signature=sign_payload(private_key, payload))


def mandate_problem(
    mandate: Mandate | None,
    public_key: Ed25519PublicKey,
    business_id: str,
    now: dt.datetime,
) -> MandateProblem | None:
    """Why this mandate cannot be used right now, or None when it can."""
    if mandate is None or not isinstance(mandate, Mandate):
        return "MANDATE_INVALID"
    if not verify_payload(public_key, mandate.signing_payload(), mandate.signature):
        return "MANDATE_INVALID"
    if mandate.business_id != business_id:
        return "MANDATE_INVALID"
    if now >= mandate.expires_at:
        return "MANDATE_EXPIRED"
    return None
