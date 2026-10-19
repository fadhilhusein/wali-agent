"""One-time confirmation tokens.

A token lets one authenticated person with the required role confirm exactly one pending item
(a payment proposal or a mandate draft). It is bound to the hash of that item, expires quickly,
and works once. Tokens travel only between the guard and the interface (a button press); they are
never given to the model, never logged, and only their hash is kept here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal

from wali.models import Principal, Role

ConfirmationKind = Literal["payment", "mandate"]
ConfirmationProblem = Literal[
    "CONFIRMATION_INVALID", "CONFIRMATION_EXPIRED", "CONFIRMATION_VOID", "ROLE_NOT_ALLOWED"
]

CONFIRMATION_MESSAGES: dict[str, str] = {
    "CONFIRMATION_INVALID": (
        "This confirmation is not valid or was already used. Nothing was changed."
    ),
    "CONFIRMATION_EXPIRED": (
        "This confirmation has expired. Nothing was changed. Please make the request again."
    ),
    "CONFIRMATION_VOID": (
        "The details changed after this confirmation was requested, so it was cancelled. "
        "Nothing was changed. Please make the request again."
    ),
    "ROLE_NOT_ALLOWED": "Only the owner can confirm this. Nothing was changed.",
}


class ConfirmationError(Exception):
    def __init__(self, code: ConfirmationProblem) -> None:
        super().__init__(code)
        self.code: ConfirmationProblem = code
        self.user_message = CONFIRMATION_MESSAGES[code]


@dataclass(frozen=True)
class PendingConfirmation:
    kind: ConfirmationKind
    subject_id: str
    subject_hash: str
    required_role: Role
    business_id: str
    expires_at: dt.datetime


def _key(token: object) -> str | None:
    if not isinstance(token, str) or not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ConfirmationStore:
    def __init__(self, ttl: dt.timedelta = dt.timedelta(minutes=5)) -> None:
        if ttl <= dt.timedelta(0):
            raise ValueError("ttl must be positive")
        self._ttl = ttl
        self._pending: dict[str, PendingConfirmation] = {}

    def issue(
        self,
        *,
        kind: ConfirmationKind,
        subject_id: str,
        subject_hash: str,
        required_role: Role,
        business_id: str,
        now: dt.datetime,
    ) -> tuple[str, dt.datetime]:
        """Create a token for one pending item. Any earlier token for the same item is voided.
        Returns the token and when it expires."""
        self._pending = {
            key: item
            for key, item in self._pending.items()
            if item.expires_at > now and item.subject_id != subject_id
        }
        token = secrets.token_urlsafe(32)
        expires_at = now + self._ttl
        self._pending[_key(token)] = PendingConfirmation(
            kind, subject_id, subject_hash, required_role, business_id, expires_at
        )
        return token, expires_at

    def redeem(
        self, token: object, principal: Principal, kind: ConfirmationKind, now: dt.datetime
    ) -> PendingConfirmation:
        """Use a token. Raises ``ConfirmationError`` unless it exists, is of the right kind, has
        not expired, and the principal has the required role in the same business.

        A wrong role does not consume the token, so someone else's failed attempt cannot stop
        the owner from confirming. Success and expiry both remove it.
        """
        item = self.check(token, principal, kind, now)
        del self._pending[_key(token)]
        return item

    def check(
        self, token: object, principal: Principal, kind: ConfirmationKind, now: dt.datetime
    ) -> PendingConfirmation:
        """What ``redeem`` checks, without using the token up (an expired one is removed)."""
        key = _key(token)
        item = self._pending.get(key) if key else None
        if item is None or item.kind != kind:
            raise ConfirmationError("CONFIRMATION_INVALID")
        if now >= item.expires_at:
            del self._pending[key]
            raise ConfirmationError("CONFIRMATION_EXPIRED")
        if principal.business_id != item.business_id or principal.role != item.required_role:
            raise ConfirmationError("ROLE_NOT_ALLOWED")
        return item

    def void_subject(self, subject_id: str) -> bool:
        """Cancel any token for an item, for example because the proposal was changed."""
        before = len(self._pending)
        self._pending = {k: v for k, v in self._pending.items() if v.subject_id != subject_id}
        return len(self._pending) != before

    def is_live_token(self, candidate: object) -> bool:
        """Whether this exact string is a token that could still be redeemed. Used to keep a
        token out of a chat reply; it consumes nothing."""
        return _key(candidate) in self._pending

    def has_pending(self, subject_id: str, now: dt.datetime) -> bool:
        return any(
            v.subject_id == subject_id and v.expires_at > now for v in self._pending.values()
        )
