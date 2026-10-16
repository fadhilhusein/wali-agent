"""GuardService: the only door between the agent's tools and anything that matters.

The service owns the signing key. Tools hand it a request and get back a plain decision; they
never receive an approval, a signature, or a confirmation token. Tokens leave only through
``collect_confirmation_requests``, which the interface (not the model) calls to show buttons.

Flow of a payment:

    propose_payment -> policy -> Deny              -> refused (and maybe flagged for review)
                              -> NeedsConfirmation -> a token goes to the interface
                              -> Allow             -> signed approval -> environment pays

    confirm_payment(owner, token) -> the policy runs AGAIN on fresh data -> signed approval
                                     -> environment pays

Every public method fails closed: an unexpected error is logged and reported as a refusal.

The service also runs the sentinel. ``screen_records`` and ``screen_untrusted`` look at text from
outside the business before a model sees it; ``screen_outgoing`` looks at a reply before a person
sees it. A screening result can make the guard more careful. It can never make it less so.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from wali.guard.audit import AuditLog
from wali.guard.confirm import (
    CONFIRMATION_MESSAGES,
    ConfirmationError,
    ConfirmationKind,
    ConfirmationStore,
)
from wali.guard.keys import encode_public_key, load_private_key
from wali.guard.mandate import (
    Limits,
    Mandate,
    MandateAction,
    MandateTerms,
    RoleAuthority,
    mandate_problem,
    sign_mandate,
)
from wali.guard.policy import (
    RATE_WINDOW,
    SPENDING_WINDOW,
    Decision,
    Deny,
    NeedsConfirmation,
    PaymentProposal,
    PaymentTerms,
    PolicyView,
    RiskWarning,
    check_authority,
    evaluate,
)
from wali.guard.sentinel import (
    BLOCKED_REPLY,
    SCREENING_FAILED,
    WITHHELD_TEXT,
    OutgoingScreen,
    Sentinel,
    Source,
    Verdict,
)
from wali.guard.signing import sign_payload
from wali.guard.store import GuardStore, ReviewItem
from wali.models import (
    BookEntry,
    Currency,
    GuardApproval,
    Invoice,
    Model,
    Money,
    NewBookEntry,
    NonEmptyStr,
    NonNegativeAmount,
    PaymentResult,
    PositiveAmount,
    Principal,
    Role,
    Supplier,
)
from wali.tools.base import AccessDenied, FinancialEnvironment, NotFound, ToolFailure

MAX_REVIEW_REASON_LENGTH = 500
MAX_AUDIT_EXCERPT_CHARS = 160
# Fields that identify or classify a record. Every other text field of a record read from the
# environment is free text from outside the business and gets screened, so a field added to a
# model later is covered without anyone remembering to list it.
STRUCTURAL_FIELDS = frozenset(
    {
        "id",
        "business_id",
        "invoice_id",
        "counterparty_id",
        "currency",
        "kind",
        "status",
        "direction",
        "verified_account",
        "stated_account",
        "registered_account",
    }
)
ACCOUNT_FIELDS = ("verified_account", "stated_account")
# What an identifier looks like. A structural field holding anything else (spaces, a sentence)
# is treated as free text after all.
_IDENTIFIER = re.compile(r"[\w.:/#*+-]{1,64}")
_DIGIT = re.compile(r"\d")
BOOK_CATEGORY_FOR_PAYMENTS = "supplier_payment"

_INTERNAL_ERROR = (
    "Something went wrong while handling this request, so nothing was changed. Please try again."
)
_UNREACHABLE = (
    "I could not reach the financial system to check this, so nothing was changed. "
    "Please try again in a moment."
)


class PaymentSummary(Model):
    supplier_name: str
    invoice_number: str
    amount: Decimal
    currency: Currency
    due_date: dt.date
    registered_account: str  # masked
    balance_after: Decimal


class PaymentDecision(Model):
    """What a tool gets back. It holds no approval, signature, or token."""

    status: Literal["executed", "needs_confirmation", "denied", "failed"]
    proposal_id: str | None = None
    reason_code: str | None = None
    user_message: str
    summary: PaymentSummary | None = None
    risk_warnings: list[RiskWarning] = Field(default_factory=list)
    required_role: Role | None = None
    transaction_id: str | None = None


class MandateRequest(Model):
    """What the owner asks for. Roles are not negotiable here: the owner proposes and confirms,
    staff never propose, and nobody else confirms."""

    per_payment: PositiveAmount
    per_week: PositiveAmount
    confirm_above: NonNegativeAmount
    min_cash_buffer: NonNegativeAmount
    allowed_suppliers: list[NonEmptyStr]
    valid_days: int = Field(default=30, ge=1, le=366)
    bookkeeper_can_propose: bool = True
    bookkeeper_max_propose: PositiveAmount | None = None
    allowed_actions: list[MandateAction] = Field(
        default_factory=lambda: ["pay_invoice", "record_book_entry"]
    )


class MandateDecision(Model):
    status: Literal["needs_confirmation", "active", "denied"]
    mandate_id: str | None = None
    reason_code: str | None = None
    user_message: str
    changes: list[str] = Field(default_factory=list)
    raises_authority: bool = False
    required_role: Role | None = None


class ReviewDecision(Model):
    status: Literal["flagged", "denied"]
    review_id: int | None = None
    reason_code: str | None = None
    user_message: str


class BookEntryDecision(Model):
    status: Literal["recorded", "denied"]
    entry: BookEntry | None = None
    reason_code: str | None = None
    user_message: str


class ConfirmationRequest(Model):
    """For the interface only: what to show next to a confirm button. Never give this to the
    model, because it carries the token."""

    token: str = Field(repr=False)
    kind: ConfirmationKind
    subject_id: str
    business_id: str
    required_role: Role
    requested_by: str
    expires_at: AwareDatetime
    summary: PaymentSummary | None = None
    changes: list[str] = Field(default_factory=list)
    risk_warnings: list[RiskWarning] = Field(default_factory=list)


@dataclass(frozen=True)
class ScreenedRecords:
    """Records after screening. ``value`` has the same shape as what went in, with flagged
    text replaced by a placeholder."""

    value: Any
    # Fields whose text was replaced.
    withheld: int = 0
    # True when some text could not be screened by the model layer. It is passed on, but the
    # turn then counts as suspicious.
    unscreened: bool = False
    categories: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        return self.withheld > 0 or self.unscreened


class OutgoingResult(Model):
    """A reply after the outgoing check: the text to show, which is a fixed safe message when
    the original was blocked."""

    text: str
    blocked: bool = False
    categories: tuple[str, ...] = ()


@dataclass
class _PendingPayment:
    proposal: PaymentProposal
    proposer: Principal
    warning_codes: frozenset[str]
    suspicious: bool
    session_id: str


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def mask_account(account: str) -> str:
    """Show only the last four characters of an account number."""
    return "***" + account[-4:] if len(account) > 4 else "***"


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:,} {currency}"


class GuardService:
    def __init__(
        self,
        env: FinancialEnvironment,
        private_key: str,
        audit: AuditLog,
        *,
        business_id: str,
        currency: str,
        store: GuardStore | None = None,
        clock: Callable[[], dt.datetime] = _utc_now,
        confirm_ttl_seconds: int = 300,
        approval_ttl_seconds: int = 60,
        proposals_per_hour: int = 10,
        sentinel: Sentinel | None = None,
        secrets: Iterable[str] = (),
        protected_texts: Iterable[str] = (),
    ) -> None:
        """``sentinel`` screens untrusted text; without one, only the built-in rules run.
        ``secrets`` are values that must never appear in a reply (API keys and the like; the
        signing key is always included). ``protected_texts`` are prompts that must not be
        repeated to a user."""
        self._env = env
        self._sentinel = sentinel or Sentinel()
        self._outgoing = OutgoingScreen(
            secrets=[private_key, *secrets], protected_texts=protected_texts
        )
        self._logged_verdicts: set[tuple[str, str]] = set()
        self._private_key = load_private_key(private_key)
        self._public_key = self._private_key.public_key()
        self._audit_log = audit
        self._business_id = business_id
        self._currency = currency
        self._store = store or GuardStore()
        self._clock = clock
        self._approval_ttl = dt.timedelta(seconds=approval_ttl_seconds)
        self._proposals_per_hour = proposals_per_hour
        self._confirmations = ConfirmationStore(dt.timedelta(seconds=confirm_ttl_seconds))
        self._pending: dict[str, _PendingPayment] = {}
        self._drafts: dict[str, MandateTerms] = {}
        self._outbox: list[ConfirmationRequest] = []
        self._lock = threading.RLock()

    # --- Small helpers -------------------------------------------------------------------

    @property
    def public_key(self) -> str:
        """The encoded public key, for the environment to verify approvals with."""
        return encode_public_key(self._public_key)

    def _now(self) -> dt.datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("The guard clock must return a timezone-aware datetime.")
        return now

    def _audit(
        self,
        event: str,
        principal: Principal | str | None,
        now: dt.datetime,
        session_id: str,
        **data: Any,
    ) -> None:
        self._audit_log.append(
            ts=now, event=event, principal=principal, data=data, session_id=session_id
        )

    def _audit_error(self, where: str, principal: Principal | None, session_id: str) -> None:
        """Best effort: record that something failed, without ever raising."""
        with contextlib.suppress(Exception):
            self._audit("error", principal, _utc_now(), session_id, where=where)

    def _read(self, call: Callable[..., Any], *args: Any) -> Any:
        """Call the environment, retrying once if it fails to answer."""
        try:
            return call(*args)
        except ToolFailure:
            return call(*args)

    def _in_business(self, principal: Principal) -> bool:
        return principal.business_id == self._business_id

    def _owner_problem(self, principal: Principal) -> str | None:
        """Why this principal cannot act as the owner, or None when they can.

        The role is not taken on trust: the environment is asked to recognise the principal,
        which it only does when the user exists and really has that role. This runs before a
        token is redeemed, so a failed attempt never uses up the real owner's confirmation.
        """
        if principal.role != "owner" or not self._in_business(principal):
            return "ROLE_NOT_ALLOWED"
        try:
            self._read(self._env.get_balance, principal)
        except AccessDenied:
            return "ROLE_NOT_ALLOWED"
        except ToolFailure:
            return "UNREACHABLE"
        return None

    def _load_mandate(self) -> Mandate | None:
        payload = self._store.active_mandate_payload()
        if payload is None:
            return None
        try:
            return Mandate.model_validate_json(payload)
        except ValidationError:
            return None

    def active_mandate(self) -> Mandate | None:
        """The current mandate, or None when there is none or it fails verification."""
        with self._lock:
            mandate = self._load_mandate()
            problem = mandate_problem(mandate, self._public_key, self._business_id, self._now())
            return mandate if problem is None else None

    def collect_confirmation_requests(self) -> list[ConfirmationRequest]:
        """FOR THE INTERFACE ONLY. Hand over new confirmation requests, tokens included."""
        with self._lock:
            requests, self._outbox = self._outbox, []
            return requests

    def is_pending(self, subject_id: str) -> bool:
        """Whether a proposal or draft is still waiting for confirmation. It stops being so
        when it is confirmed, declined, withdrawn, replaced, or expired."""
        with self._lock:
            return self._confirmations.has_pending(subject_id, self._now())

    # --- Screening -----------------------------------------------------------------------

    def _log_verdict(
        self,
        verdict: Verdict,
        text: str,
        principal: Principal | None,
        session_id: str,
        **where: Any,
    ) -> None:
        """Write a suspicious verdict to the audit log, once per text and session."""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if (session_id, digest) in self._logged_verdicts:
            return
        if len(self._logged_verdicts) > 10_000:
            self._logged_verdicts.clear()
        self._logged_verdicts.add((session_id, digest))
        self.audit_event(
            "sentinel_verdict",
            principal,
            session_id=session_id,
            categories=list(verdict.categories),
            layers=list(verdict.layers),
            reasons=list(verdict.reasons),
            withheld=verdict.withhold,
            text_sha256=digest,
            # Digits are masked: the log must never hold a full account number.
            excerpt=_DIGIT.sub("#", text[:MAX_AUDIT_EXCERPT_CHARS]),
            **{key: value for key, value in where.items() if value},
        )

    def screen_untrusted(
        self,
        text: str,
        *,
        principal: Principal | None = None,
        session_id: str = "",
        source: Source = "data",
        origin: str = "",
    ) -> Verdict:
        """Screen one piece of text that came from outside. ``source`` is "message" for what
        a person typed into the chat. Never raises: text that cannot be screened is reported
        as suspicious."""
        try:
            verdict = self._sentinel.screen([text], source=source)[0]
        except Exception:
            self._audit_error("screen_untrusted", principal, session_id)
            verdict = SCREENING_FAILED
        if verdict.suspicious:
            self._log_verdict(verdict, text, principal, session_id, origin=origin, source=source)
        return verdict

    def screen_records(
        self,
        value: Any,
        *,
        principal: Principal | None = None,
        session_id: str = "",
        origin: str = "",
    ) -> ScreenedRecords:
        """Screen every free-text field of one record or a list of records read from the
        environment, and return copies in which flagged text is replaced by a placeholder.
        What a model is shown must come from here, never from the environment directly."""
        records = value if isinstance(value, list) else [value]
        slots: list[tuple[int, str, str]] = []
        for index, record in enumerate(records):
            if not isinstance(record, BaseModel):
                continue
            for name, content in record:
                if not isinstance(content, str) or not content.strip():
                    continue
                if name in ACCOUNT_FIELDS:
                    self._outgoing.add_account(content)
                if name not in STRUCTURAL_FIELDS or not _IDENTIFIER.fullmatch(content):
                    slots.append((index, name, content))
        if not slots:
            return ScreenedRecords(value)
        try:
            verdicts = self._sentinel.screen([content for _, _, content in slots])
        except Exception:
            self._audit_error("screen_records", principal, session_id)
            verdicts = [SCREENING_FAILED] * len(slots)

        updates: dict[int, dict[str, str]] = {}
        categories: dict[str, None] = {}
        withheld, unscreened = 0, False
        for (index, name, content), verdict in zip(slots, verdicts, strict=True):
            if not verdict.suspicious:
                continue
            self._log_verdict(
                verdict,
                content,
                principal,
                session_id,
                origin=origin,
                record_id=getattr(records[index], "id", None),
                field=name,
            )
            categories.update(dict.fromkeys(verdict.categories))
            if verdict.withhold:
                updates.setdefault(index, {})[name] = WITHHELD_TEXT
                withheld += 1
            else:
                unscreened = True
        cleaned = [
            record.model_copy(update=updates[index]) if index in updates else record
            for index, record in enumerate(records)
        ]
        return ScreenedRecords(
            value=cleaned if isinstance(value, list) else cleaned[0],
            withheld=withheld,
            unscreened=unscreened,
            categories=tuple(categories),
        )

    def screen_outgoing(
        self, text: str, principal: Principal, *, session_id: str = ""
    ) -> OutgoingResult:
        """Check a reply before it is shown to ``principal``. A reply that carries key
        material, a raw token, system prompt text, a full account number, or data outside
        the principal's role is replaced by a fixed safe message. Never raises."""
        try:
            verdict = self._outgoing.check(
                text, principal.role, is_live_token=self._confirmations.is_live_token
            )
            if verdict.allowed:
                return OutgoingResult(text=text)
            categories = verdict.categories
        except Exception:
            self._audit_error("screen_outgoing", principal, session_id)
            categories = ("internal_error",)
        # The blocked text is not written to the log: it may hold the very thing being kept in.
        self.audit_event(
            "output_blocked",
            principal,
            session_id=session_id,
            categories=list(categories),
            length=len(text),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        return OutgoingResult(text=BLOCKED_REPLY, blocked=True, categories=categories)

    def screening_stats(self) -> dict[str, int]:
        """Counters of the screening model's use: calls made, calls that gave no usable
        answer, and texts left to the rules alone because there were too many."""
        return dict(self._sentinel.stats)

    def _for_model(self, summary: PaymentSummary, session_id: str) -> PaymentSummary:
        """The summary as a tool may see it: names from the records are screened first. The
        owner's confirmation screen gets the real names."""
        return self.screen_records(summary, session_id=session_id, origin="guard").value

    # --- Payments: proposing -------------------------------------------------------------

    def propose_payment(
        self,
        principal: Principal,
        invoice_id: str,
        *,
        session_id: str = "",
        suspicious: bool = False,
    ) -> PaymentDecision:
        """Ask to pay one invoice. Returns the guard's decision; a payment only happens when
        the policy allows it outright or the owner later confirms it."""
        with self._lock:
            try:
                return self._propose(principal, invoice_id, session_id, suspicious)
            except Exception:
                self._audit_error("propose_payment", principal, session_id)
                return PaymentDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def _propose(
        self, principal: Principal, invoice_id: str, session_id: str, suspicious: bool
    ) -> PaymentDecision:
        now = self._now()
        if not isinstance(invoice_id, str) or not invoice_id.strip():
            decision = evaluate_missing_invoice()
            self._audit(
                "payment_denied", principal, now, session_id, reason_code=decision.reason_code
            )
            return PaymentDecision(
                status="denied",
                reason_code=decision.reason_code,
                user_message=decision.user_message,
            )
        proposal = PaymentProposal(
            proposal_id=f"p-{secrets.token_hex(6)}",
            business_id=principal.business_id,
            invoice_id=invoice_id.strip(),
            proposed_by=principal.user_id,
        )
        earlier = self._store.proposals_since(principal.user_id, now - RATE_WINDOW)
        self._store.record_proposal(principal.user_id, now)
        self._audit(
            "payment_proposed",
            principal,
            now,
            session_id,
            proposal_id=proposal.proposal_id,
            invoice_id=proposal.invoice_id,
            suspicious=suspicious,
        )
        decision, view = self._decide(proposal, principal, now, suspicious, earlier, session_id)

        if isinstance(decision, Deny):
            return self._denied(proposal, principal, decision, now, session_id)
        if isinstance(decision, NeedsConfirmation):
            return self._request_confirmation(
                proposal, principal, decision, view, now, session_id, suspicious
            )
        return self._execute(proposal, principal, decision.terms, view, now, session_id, None)

    def _decide(
        self,
        proposal: PaymentProposal,
        principal: Principal,
        now: dt.datetime,
        suspicious: bool,
        proposals_last_hour: int,
        session_id: str = "",
    ) -> tuple[Decision, PolicyView | None]:
        """Run the policy. The environment is read only after the mandate and role checks
        pass, so a principal who may not propose learns nothing from it."""
        mandate = self._load_mandate()
        refused = check_authority(
            proposal, mandate, principal, self._public_key, self._business_id, now
        )
        if refused is not None:
            return refused, None
        try:
            view = self._build_view(
                proposal, principal, now, suspicious, proposals_last_hour, session_id
            )
        except AccessDenied:
            return Deny(
                reason_code="ROLE_NOT_ALLOWED",
                user_message="Your role is not allowed to propose this payment.",
            ), None
        except ToolFailure:
            return Deny(reason_code="INTERNAL_ERROR", user_message=_UNREACHABLE), None
        return evaluate(proposal, mandate, principal, view, now), view

    def _build_view(
        self,
        proposal: PaymentProposal,
        principal: Principal,
        now: dt.datetime,
        suspicious: bool,
        proposals_last_hour: int,
        session_id: str = "",
    ) -> PolicyView:
        payables: list[Invoice] = self._read(self._env.list_invoices, principal, "payable")
        invoice = next((i for i in payables if i.id == proposal.invoice_id), None)
        supplier: Supplier | None = None
        others: tuple[Invoice, ...] = ()
        if invoice is not None:
            try:
                supplier = self._read(self._env.get_supplier, principal, invoice.counterparty_id)
            except NotFound:
                supplier = None
            others = tuple(
                i
                for i in payables
                if i.counterparty_id == invoice.counterparty_id and i.id != invoice.id
            )
        balance: Money = self._read(self._env.get_balance, principal)
        # The verdict belongs to the content: an invoice or supplier whose own text looks like
        # an injected instruction is paid only with the owner's confirmation, in any turn.
        own_text = self.screen_records(
            [record for record in (invoice, supplier) if record is not None],
            principal=principal,
            session_id=session_id,
            origin="propose_payment",
        )
        suspicious = suspicious or own_text.suspicious
        return PolicyView(
            public_key=self._public_key,
            business_id=self._business_id,
            invoice=invoice,
            supplier=supplier,
            supplier_invoices=others,
            balance=balance,
            paid_last_7_days=self._store.paid_since(now - SPENDING_WINDOW),
            already_paid=self._store.invoice_paid(proposal.invoice_id),
            proposals_last_hour=proposals_last_hour,
            proposals_per_hour=self._proposals_per_hour,
            suspicious=suspicious,
        )

    def _denied(
        self,
        proposal: PaymentProposal,
        principal: Principal,
        decision: Deny,
        now: dt.datetime,
        session_id: str,
    ) -> PaymentDecision:
        self._audit(
            "payment_denied",
            principal,
            now,
            session_id,
            proposal_id=proposal.proposal_id,
            invoice_id=proposal.invoice_id,
            reason_code=decision.reason_code,
        )
        if decision.flag_for_review:
            item = self._store.add_review_item(
                invoice_id=proposal.invoice_id,
                reason_code=decision.reason_code,
                reason=decision.user_message,
                created_by="guard",
                now=now,
            )
            self._audit(
                "review_item_created",
                "guard",
                now,
                session_id,
                review_id=item.id,
                invoice_id=proposal.invoice_id,
                reason_code=decision.reason_code,
            )
        return PaymentDecision(
            status="denied",
            proposal_id=proposal.proposal_id,
            reason_code=decision.reason_code,
            user_message=decision.user_message,
        )

    @staticmethod
    def _summary(view: PolicyView, balance_after: Decimal) -> PaymentSummary:
        invoice, supplier = view.invoice, view.supplier
        return PaymentSummary(
            supplier_name=supplier.name,
            invoice_number=invoice.number,
            amount=invoice.amount,
            currency=invoice.currency,
            due_date=invoice.due_date,
            registered_account=mask_account(supplier.verified_account),
            balance_after=balance_after,
        )

    def _request_confirmation(
        self,
        proposal: PaymentProposal,
        proposer: Principal,
        decision: NeedsConfirmation,
        view: PolicyView,
        now: dt.datetime,
        session_id: str,
        suspicious: bool,
    ) -> PaymentDecision:
        # A newer proposal for the same invoice replaces an older pending one.
        for old_id, old in list(self._pending.items()):
            if old.proposal.invoice_id == proposal.invoice_id:
                self._confirmations.void_subject(old_id)
                del self._pending[old_id]

        summary = self._summary(view, decision.balance_after)
        token, expires_at = self._confirmations.issue(
            kind="payment",
            subject_id=proposal.proposal_id,
            subject_hash=decision.terms.digest(),
            required_role=decision.required_role,
            business_id=self._business_id,
            now=now,
        )
        self._pending[proposal.proposal_id] = _PendingPayment(
            proposal=proposal,
            proposer=proposer,
            warning_codes=frozenset(w.code for w in decision.risk_warnings),
            suspicious=suspicious,
            session_id=session_id,
        )
        self._outbox.append(
            ConfirmationRequest(
                token=token,
                kind="payment",
                subject_id=proposal.proposal_id,
                business_id=self._business_id,
                required_role=decision.required_role,
                requested_by=proposer.user_id,
                expires_at=expires_at,
                summary=summary,
                risk_warnings=decision.risk_warnings,
            )
        )
        self._audit(
            "confirmation_requested",
            proposer,
            now,
            session_id,
            proposal_id=proposal.proposal_id,
            invoice_id=proposal.invoice_id,
            amount=decision.terms.amount,
            terms_digest=decision.terms.digest(),
            warnings=[w.code for w in decision.risk_warnings],
            required_role=decision.required_role,
        )
        return PaymentDecision(
            status="needs_confirmation",
            proposal_id=proposal.proposal_id,
            user_message=(
                "Nothing has been paid yet. This payment needs the owner's confirmation, "
                "and the request has been sent to the owner."
            ),
            summary=self._for_model(summary, session_id),
            risk_warnings=decision.risk_warnings,
            required_role=decision.required_role,
        )

    # --- Payments: executing -------------------------------------------------------------

    def _execute(
        self,
        proposal: PaymentProposal,
        proposer: Principal,
        terms: PaymentTerms,
        view: PolicyView,
        now: dt.datetime,
        session_id: str,
        confirmed_by: Principal | None,
    ) -> PaymentDecision:
        unsigned = GuardApproval(
            approval_id=f"ap-{secrets.token_hex(8)}",
            proposal_hash=terms.digest(),
            business_id=terms.business_id,
            invoice_id=terms.invoice_id,
            supplier_id=terms.supplier_id,
            amount=terms.amount,
            currency=terms.currency,
            destination_account=terms.destination_account,
            expires_at=now + self._approval_ttl,
            signature="",
        )
        approval = unsigned.model_copy(
            update={"signature": sign_payload(self._private_key, unsigned.signing_payload())}
        )
        common = {
            "proposal_id": proposal.proposal_id,
            "approval_id": approval.approval_id,
            "invoice_id": terms.invoice_id,
            "supplier_id": terms.supplier_id,
            "amount": terms.amount,
            "currency": terms.currency,
        }
        self._audit(
            "approval_issued",
            confirmed_by or proposer,
            now,
            session_id,
            terms_digest=terms.digest(),
            confirmed=confirmed_by is not None,
            **common,
        )

        try:
            result: PaymentResult = self._read(self._env.execute_payment, approval)
        except ToolFailure:
            self._audit("payment_failed", proposer, now, session_id, **common)
            return PaymentDecision(
                status="failed",
                proposal_id=proposal.proposal_id,
                reason_code="ENVIRONMENT_FAILURE",
                user_message=(
                    "The payment system did not respond, so nothing was paid. Please try again."
                ),
            )
        if result.status != "success":
            self._audit(
                "payment_rejected", proposer, now, session_id, message=result.message, **common
            )
            # The environment's own words are outside text too.
            said = self.screen_untrusted(
                result.message, principal=proposer, session_id=session_id, origin="execute_payment"
            )
            detail = "" if said.withhold else f" {result.message}"
            return PaymentDecision(
                status="failed",
                proposal_id=proposal.proposal_id,
                reason_code="ENVIRONMENT_REJECTED",
                user_message=f"The payment was not accepted and nothing was paid.{detail}",
            )

        # The money has moved. Nothing below may turn this into a reported failure.
        notes = []
        try:
            self._store.record_execution(
                approval_id=approval.approval_id,
                invoice_id=terms.invoice_id,
                supplier_id=terms.supplier_id,
                amount=terms.amount,
                currency=terms.currency,
                proposed_by=proposer.user_id,
                now=now,
            )
            self._audit(
                "payment_executed",
                confirmed_by or proposer,
                now,
                session_id,
                transaction_id=result.transaction_id,
                **common,
            )
        except Exception:
            self._audit_error("record_execution", proposer, session_id)
            notes.append("The payment could not be written to the guard's own records.")

        summary = self._summary(view, view.balance.amount - terms.amount)
        mandate = self._load_mandate()
        if mandate is not None and "record_book_entry" in mandate.allowed_actions:
            entry = NewBookEntry(
                date=now.date(),
                amount=terms.amount,
                direction="out",
                category=BOOK_CATEGORY_FOR_PAYMENTS,
                description=f"Payment {summary.invoice_number} to {summary.supplier_name}",
                invoice_id=terms.invoice_id,
            )
            try:
                recorded = self._read(self._env.record_book_entry, proposer, entry)
                self._audit(
                    "book_entry_recorded",
                    proposer,
                    now,
                    session_id,
                    book_entry_id=recorded.id,
                    invoice_id=terms.invoice_id,
                )
            except Exception:
                self._audit_error("record_book_entry", proposer, session_id)
                notes.append("The books entry could not be recorded. Please add it by hand.")

        shown = self._for_model(summary, session_id)
        message = (
            f"Paid {_money(terms.amount, terms.currency)} for invoice {shown.invoice_number} "
            f"to the registered account of {shown.supplier_name}."
        )
        return PaymentDecision(
            status="executed",
            proposal_id=proposal.proposal_id,
            user_message=" ".join([message, *notes]),
            summary=shown,
            transaction_id=result.transaction_id,
        )

    # --- Payments: confirming ------------------------------------------------------------

    def confirm_payment(
        self, principal: Principal, token: str, *, session_id: str = ""
    ) -> PaymentDecision:
        """FOR THE INTERFACE ONLY, after an authenticated button press. Redeems the token and,
        if the policy still agrees on fresh data, pays."""
        with self._lock:
            try:
                return self._confirm(principal, token, session_id)
            except Exception:
                self._audit_error("confirm_payment", principal, session_id)
                return PaymentDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def _refuse_confirmation(
        self, principal: Principal, code: str, now: dt.datetime, session_id: str, **data: Any
    ) -> PaymentDecision:
        self._audit("confirmation_refused", principal, now, session_id, reason_code=code, **data)
        return PaymentDecision(
            status="denied", reason_code=code, user_message=CONFIRMATION_MESSAGES[code]
        )

    def _confirm(self, principal: Principal, token: str, session_id: str) -> PaymentDecision:
        now = self._now()
        problem = self._owner_problem(principal)
        if problem == "UNREACHABLE":
            return PaymentDecision(
                status="denied", reason_code="INTERNAL_ERROR", user_message=_UNREACHABLE
            )
        if problem is not None:
            return self._refuse_confirmation(principal, problem, now, session_id)
        try:
            item = self._confirmations.redeem(token, principal, "payment", now)
        except ConfirmationError as error:
            return self._refuse_confirmation(principal, error.code, now, session_id)
        pending = self._pending.pop(item.subject_id, None)
        if pending is None:
            return self._refuse_confirmation(principal, "CONFIRMATION_INVALID", now, session_id)
        proposal = pending.proposal

        # Judge the proposal again, as its original proposer, on what is true right now.
        decision, view = self._decide(
            proposal, pending.proposer, now, pending.suspicious, 0, session_id
        )
        if isinstance(decision, Deny):
            return self._denied(proposal, pending.proposer, decision, now, session_id)
        if decision.terms.digest() != item.subject_hash:
            return self._refuse_confirmation(
                principal, "CONFIRMATION_VOID", now, session_id, proposal_id=proposal.proposal_id
            )
        if isinstance(decision, NeedsConfirmation):
            new_warnings = {w.code for w in decision.risk_warnings} - pending.warning_codes
            if new_warnings:
                # The owner agreed to a summary that no longer tells the whole story.
                self._audit(
                    "confirmation_superseded",
                    principal,
                    now,
                    session_id,
                    proposal_id=proposal.proposal_id,
                    new_warnings=sorted(new_warnings),
                )
                again = self._request_confirmation(
                    proposal, pending.proposer, decision, view, now, session_id, pending.suspicious
                )
                return again.model_copy(
                    update={
                        "user_message": (
                            "Nothing has been paid. The situation changed since this was "
                            "requested, so please review the new warnings and confirm again."
                        )
                    }
                )
        self._audit(
            "payment_confirmed",
            principal,
            now,
            session_id,
            proposal_id=proposal.proposal_id,
            invoice_id=proposal.invoice_id,
        )
        return self._execute(
            proposal, pending.proposer, decision.terms, view, now, session_id, principal
        )

    def cancel_confirmation(
        self, principal: Principal, token: str, kind: ConfirmationKind, *, session_id: str = ""
    ) -> bool:
        """FOR THE INTERFACE ONLY. The person who could confirm declines instead."""
        with self._lock:
            try:
                now = self._now()
                item = self._confirmations.redeem(token, principal, kind, now)
                self._pending.pop(item.subject_id, None)
                self._drafts.pop(item.subject_id, None)
                self._audit(
                    "confirmation_cancelled", principal, now, session_id, subject_id=item.subject_id
                )
                return True
            except ConfirmationError:
                return False
            except Exception:
                self._audit_error("cancel_confirmation", principal, session_id)
                return False

    def withdraw_proposal(
        self, principal: Principal, proposal_id: str, *, session_id: str = ""
    ) -> bool:
        """Drop a pending proposal and void its token. Allowed for its proposer and the owner."""
        with self._lock:
            try:
                pending = self._pending.get(proposal_id)
                if pending is None or not self._in_business(principal):
                    return False
                if principal.user_id != pending.proposer.user_id and principal.role != "owner":
                    return False
                del self._pending[proposal_id]
                self._confirmations.void_subject(proposal_id)
                self._audit(
                    "proposal_withdrawn",
                    principal,
                    self._now(),
                    session_id,
                    proposal_id=proposal_id,
                )
                return True
            except Exception:
                self._audit_error("withdraw_proposal", principal, session_id)
                return False

    # --- Mandate -------------------------------------------------------------------------

    def draft_mandate(
        self, principal: Principal, request: MandateRequest, *, session_id: str = ""
    ) -> MandateDecision:
        """Prepare a mandate for the owner to confirm. Nothing is signed or activated here."""
        with self._lock:
            try:
                return self._draft_mandate(principal, request, session_id)
            except Exception:
                self._audit_error("draft_mandate", principal, session_id)
                return MandateDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def _mandate_denied(
        self, principal: Principal, code: str, message: str, now: dt.datetime, session_id: str
    ) -> MandateDecision:
        self._audit("mandate_denied", principal, now, session_id, reason_code=code)
        return MandateDecision(status="denied", reason_code=code, user_message=message)

    def _draft_mandate(
        self, principal: Principal, request: MandateRequest, session_id: str
    ) -> MandateDecision:
        now = self._now()
        problem = self._owner_problem(principal)
        if problem == "UNREACHABLE":
            return self._mandate_denied(principal, "INTERNAL_ERROR", _UNREACHABLE, now, session_id)
        if problem is not None:
            return self._mandate_denied(
                principal,
                "ROLE_NOT_ALLOWED",
                "Only the owner can set or change the spending mandate.",
                now,
                session_id,
            )
        for supplier_id in request.allowed_suppliers:
            try:
                supplier: Supplier = self._read(self._env.get_supplier, principal, supplier_id)
            except AccessDenied:
                return self._mandate_denied(
                    principal,
                    "ROLE_NOT_ALLOWED",
                    "Only the owner can set or change the spending mandate.",
                    now,
                    session_id,
                )
            except NotFound:
                return self._mandate_denied(
                    principal,
                    "MANDATE_INVALID",
                    f"There is no supplier with the id {supplier_id}. Nothing was changed.",
                    now,
                    session_id,
                )
            except ToolFailure:
                return self._mandate_denied(
                    principal, "INTERNAL_ERROR", _UNREACHABLE, now, session_id
                )
            if not supplier.account_verified:
                return self._mandate_denied(
                    principal,
                    "SUPPLIER_ACCOUNT_MISMATCH",
                    f"The bank account of supplier {supplier_id} is not verified, so it cannot "
                    "be added to the mandate. Verify the account with the supplier first.",
                    now,
                    session_id,
                )

        def money(amount: Decimal) -> Money:
            return Money(amount=amount, currency=self._currency)

        try:
            terms = MandateTerms(
                mandate_id=self._store.next_mandate_id(),
                business_id=self._business_id,
                issued_by=principal.user_id,
                expires_at=now + dt.timedelta(days=request.valid_days),
                allowed_actions=request.allowed_actions,
                limits=Limits(
                    per_payment=money(request.per_payment), per_week=money(request.per_week)
                ),
                allowed_suppliers=request.allowed_suppliers,
                role_authority={
                    "owner": RoleAuthority(can_propose=True, can_confirm=True),
                    "bookkeeper": RoleAuthority(
                        can_propose=request.bookkeeper_can_propose,
                        max_propose=request.bookkeeper_max_propose
                        if request.bookkeeper_can_propose
                        else None,
                    ),
                    "staff": RoleAuthority(),
                },
                confirm_above=money(request.confirm_above),
                min_cash_buffer=money(request.min_cash_buffer),
            )
        except ValidationError as error:
            problems = "; ".join(err["msg"].removeprefix("Value error, ") for err in error.errors())
            return self._mandate_denied(
                principal,
                "MANDATE_INVALID",
                f"These mandate terms are not valid: {problems}. Nothing was changed.",
                now,
                session_id,
            )

        changes, raises = describe_changes(terms, self.active_mandate())
        for old_id in list(self._drafts):
            self._confirmations.void_subject(old_id)
            del self._drafts[old_id]
        self._drafts[terms.mandate_id] = terms
        token, expires_at = self._confirmations.issue(
            kind="mandate",
            subject_id=terms.mandate_id,
            subject_hash=terms.digest(),
            required_role="owner",
            business_id=self._business_id,
            now=now,
        )
        self._outbox.append(
            ConfirmationRequest(
                token=token,
                kind="mandate",
                subject_id=terms.mandate_id,
                business_id=self._business_id,
                required_role="owner",
                requested_by=principal.user_id,
                expires_at=expires_at,
                changes=changes,
            )
        )
        self._audit(
            "mandate_drafted",
            principal,
            now,
            session_id,
            mandate_id=terms.mandate_id,
            terms=terms,
            terms_digest=terms.digest(),
            raises_authority=raises,
        )
        return MandateDecision(
            status="needs_confirmation",
            mandate_id=terms.mandate_id,
            user_message=(
                "The mandate is drafted but NOT active. It only takes effect after the owner "
                "confirms it."
            ),
            changes=changes,
            raises_authority=raises,
            required_role="owner",
        )

    def confirm_mandate(
        self, principal: Principal, token: str, *, session_id: str = ""
    ) -> MandateDecision:
        """FOR THE INTERFACE ONLY. The owner confirms a draft; it is then signed and activated."""
        with self._lock:
            try:
                return self._confirm_mandate(principal, token, session_id)
            except Exception:
                self._audit_error("confirm_mandate", principal, session_id)
                return MandateDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def _confirm_mandate(
        self, principal: Principal, token: str, session_id: str
    ) -> MandateDecision:
        now = self._now()

        def refuse(code: str) -> MandateDecision:
            self._audit("confirmation_refused", principal, now, session_id, reason_code=code)
            return MandateDecision(
                status="denied", reason_code=code, user_message=CONFIRMATION_MESSAGES[code]
            )

        problem = self._owner_problem(principal)
        if problem == "UNREACHABLE":
            return MandateDecision(
                status="denied", reason_code="INTERNAL_ERROR", user_message=_UNREACHABLE
            )
        if problem is not None:
            return refuse(problem)
        try:
            item = self._confirmations.redeem(token, principal, "mandate", now)
        except ConfirmationError as error:
            return refuse(error.code)
        terms = self._drafts.pop(item.subject_id, None)
        if terms is None:
            return refuse("CONFIRMATION_INVALID")
        if terms.digest() != item.subject_hash or terms.business_id != self._business_id:
            return refuse("CONFIRMATION_VOID")
        if now >= terms.expires_at:
            return refuse("CONFIRMATION_EXPIRED")

        mandate = sign_mandate(terms, self._private_key)
        self._store.activate_mandate(mandate.mandate_id, mandate.model_dump_json(), now)
        self._audit(
            "mandate_activated",
            principal,
            now,
            session_id,
            mandate_id=mandate.mandate_id,
            terms_digest=terms.digest(),
        )
        return MandateDecision(
            status="active",
            mandate_id=mandate.mandate_id,
            user_message=(
                f"The mandate is now active until {terms.expires_at.date().isoformat()}."
            ),
        )

    # --- Review items --------------------------------------------------------------------

    def flag_for_review(
        self, principal: Principal, invoice_id: str, reason: str, *, session_id: str = ""
    ) -> ReviewDecision:
        """Put an invoice in front of the owner. This never pays or changes the invoice."""
        with self._lock:
            try:
                now = self._now()
                if principal.role not in ("owner", "bookkeeper") or not self._in_business(
                    principal
                ):
                    return ReviewDecision(
                        status="denied",
                        reason_code="ROLE_NOT_ALLOWED",
                        user_message="Your role is not allowed to flag invoices.",
                    )
                try:
                    payables = self._read(self._env.list_invoices, principal, "payable")
                except AccessDenied:
                    return ReviewDecision(
                        status="denied",
                        reason_code="ROLE_NOT_ALLOWED",
                        user_message="Your role is not allowed to flag invoices.",
                    )
                except ToolFailure:
                    return ReviewDecision(
                        status="denied", reason_code="INTERNAL_ERROR", user_message=_UNREACHABLE
                    )
                if not any(i.id == invoice_id for i in payables):
                    return ReviewDecision(
                        status="denied",
                        reason_code="INVOICE_INVALID",
                        user_message="I could not find a supplier invoice with that id.",
                    )
                item = self._store.add_review_item(
                    invoice_id=invoice_id,
                    reason_code="FLAGGED_MANUALLY",
                    reason=self._review_reason(reason, principal, session_id),
                    created_by=principal.user_id,
                    now=now,
                )
                self._audit(
                    "review_item_created",
                    principal,
                    now,
                    session_id,
                    review_id=item.id,
                    invoice_id=invoice_id,
                    reason_code=item.reason_code,
                )
                return ReviewDecision(
                    status="flagged",
                    review_id=item.id,
                    user_message="The invoice is flagged for the owner to review.",
                )
            except Exception:
                self._audit_error("flag_for_review", principal, session_id)
                return ReviewDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def _review_reason(self, reason: object, principal: Principal, session_id: str) -> str:
        """The assistant's note for the owner, made safe to show: it was written by a model
        that may have read injected text, so it is screened like outside text, and full
        account numbers in it are masked."""
        text = str(reason).strip()[:MAX_REVIEW_REASON_LENGTH] or "No reason given."
        verdict = self.screen_untrusted(
            text, principal=principal, session_id=session_id, origin="flag_for_review"
        )
        if verdict.withhold:
            return f"{WITHHELD_TEXT} Look at the invoice itself."
        return self._outgoing.mask_accounts(text)

    def review_items(self, principal: Principal) -> list[ReviewItem]:
        """Review items, for the owner only."""
        with self._lock:
            if principal.role != "owner" or not self._in_business(principal):
                return []
            return self._store.review_items()

    # --- Books ---------------------------------------------------------------------------

    def record_book_entry(
        self, principal: Principal, entry: NewBookEntry, *, session_id: str = ""
    ) -> BookEntryDecision:
        """Add a books entry on someone's behalf. Needs a valid mandate that allows it and a
        role that keeps the books. This never moves money."""
        with self._lock:
            try:
                now = self._now()

                def denied(code: str, message: str) -> BookEntryDecision:
                    self._audit("book_entry_denied", principal, now, session_id, reason_code=code)
                    return BookEntryDecision(
                        status="denied", reason_code=code, user_message=message
                    )

                mandate = self._load_mandate()
                problem = mandate_problem(mandate, self._public_key, self._business_id, now)
                if problem is not None:
                    return denied(
                        problem,
                        "There is no valid spending mandate, so I cannot change the books. "
                        "The owner needs to confirm one.",
                    )
                if "record_book_entry" not in mandate.allowed_actions:
                    return denied(
                        "MANDATE_INVALID",
                        "The current mandate does not allow recording book entries.",
                    )
                if principal.role not in ("owner", "bookkeeper") or not self._in_business(
                    principal
                ):
                    return denied(
                        "ROLE_NOT_ALLOWED", "Your role is not allowed to record book entries."
                    )
                try:
                    recorded: BookEntry = self._read(self._env.record_book_entry, principal, entry)
                except AccessDenied:
                    return denied(
                        "ROLE_NOT_ALLOWED", "Your role is not allowed to record book entries."
                    )
                except NotFound:
                    return denied(
                        "INVOICE_INVALID", "I could not find the invoice this entry refers to."
                    )
                except ToolFailure:
                    return denied("INTERNAL_ERROR", _UNREACHABLE)
                self._audit(
                    "book_entry_recorded",
                    principal,
                    now,
                    session_id,
                    book_entry_id=recorded.id,
                    amount=recorded.amount,
                    direction=recorded.direction,
                    category=recorded.category,
                    invoice_id=recorded.invoice_id,
                )
                return BookEntryDecision(
                    status="recorded",
                    entry=self.screen_records(
                        recorded, principal=principal, session_id=session_id, origin="guard"
                    ).value,
                    user_message="The entry is recorded in the books. No money was moved.",
                )
            except Exception:
                self._audit_error("record_book_entry", principal, session_id)
                return BookEntryDecision(
                    status="denied", reason_code="INTERNAL_ERROR", user_message=_INTERNAL_ERROR
                )

    def audit_event(
        self, event: str, principal: Principal | None, *, session_id: str = "", **data: Any
    ) -> None:
        """Write an event from outside the guard (a tool call, a blocked reply) to the same
        audit log. Best effort: it never raises."""
        with self._lock, contextlib.suppress(Exception):
            self._audit(event, principal, self._now(), session_id, **data)


def evaluate_missing_invoice() -> Deny:
    return Deny(
        reason_code="INVOICE_INVALID",
        user_message="Please tell me which invoice to pay. I need its id.",
    )


def describe_changes(new: MandateTerms, old: Mandate | None) -> tuple[list[str], bool]:
    """Plain lines describing a draft, compared with the active mandate if there is one, and
    whether the draft gives more spending authority than before."""
    currency = new.currency
    bookkeeper = new.role_authority["bookkeeper"]

    def bookkeeper_line(authority: RoleAuthority) -> str:
        if not authority.can_propose:
            return "may not propose payments"
        if authority.max_propose is None:
            return "may propose payments up to the per-payment limit"
        return f"may propose payments up to {_money(authority.max_propose, currency)}"

    values = [
        ("Per-payment limit", new.limits.per_payment.amount, "limits.per_payment", True),
        ("Weekly limit", new.limits.per_week.amount, "limits.per_week", True),
        ("Owner confirmation needed above", new.confirm_above.amount, "confirm_above", True),
        ("Cash buffer to keep", new.min_cash_buffer.amount, "min_cash_buffer", False),
    ]

    if old is None:
        lines = [f"{label}: {_money(amount, currency)}" for label, amount, _, _ in values]
        lines.append(f"Suppliers that can be paid: {', '.join(new.allowed_suppliers) or 'none'}")
        lines.append(f"Bookkeeper {bookkeeper_line(bookkeeper)}")
        lines.append(f"Valid until: {new.expires_at.date().isoformat()}")
        return lines, True

    def old_amount(path: str) -> Decimal:
        target: Any = old
        for part in path.split("."):
            target = getattr(target, part)
        return target.amount

    lines, raises = [], False
    for label, amount, path, higher_is_more_authority in values:
        before = old_amount(path)
        if amount == before:
            continue
        direction = "raised" if amount > before else "lowered"
        lines.append(
            f"{label}: {_money(before, currency)} -> {_money(amount, currency)} ({direction})"
        )
        if (amount > before) == higher_is_more_authority:
            raises = True

    added = [s for s in new.allowed_suppliers if s not in old.allowed_suppliers]
    removed = [s for s in old.allowed_suppliers if s not in new.allowed_suppliers]
    if added:
        lines.append(f"Suppliers added: {', '.join(added)}")
        raises = True
    if removed:
        lines.append(f"Suppliers removed: {', '.join(removed)}")

    before_bookkeeper = old.role_authority.get("bookkeeper", RoleAuthority())
    if bookkeeper != before_bookkeeper:
        lines.append(
            f"Bookkeeper: {bookkeeper_line(before_bookkeeper)} -> {bookkeeper_line(bookkeeper)}"
        )
        limit = new.limits.per_payment.amount
        now_reach = (bookkeeper.max_propose or limit) if bookkeeper.can_propose else Decimal(0)
        old_limit = old.limits.per_payment.amount
        before_reach = (
            (before_bookkeeper.max_propose or old_limit)
            if before_bookkeeper.can_propose
            else Decimal(0)
        )
        if now_reach > before_reach:
            raises = True

    added_actions = [a for a in new.allowed_actions if a not in old.allowed_actions]
    removed_actions = [a for a in old.allowed_actions if a not in new.allowed_actions]
    if added_actions:
        lines.append(f"Actions added: {', '.join(added_actions)}")
        raises = True
    if removed_actions:
        lines.append(f"Actions removed: {', '.join(removed_actions)}")

    if new.expires_at.date() != old.expires_at.date():
        lines.append(
            f"Valid until: {old.expires_at.date().isoformat()} -> "
            f"{new.expires_at.date().isoformat()}"
        )
    if not lines:
        lines.append("No change to the current terms.")
    return lines, raises
