"""Wiring shared by every interface (CLI, Telegram, web).

``WaliApp`` owns the pieces and the two things an interface needs:

- ``chat``: hand a message from an authenticated principal to the agent;
- ``pending`` / ``confirm`` / ``cancel``: the confirmation inbox. Confirmation tokens live here,
  between the guard and the interface, and never pass through the model.

The principal given to these methods must come from the interface's own authentication. Nothing
typed in a chat can change it.

Every public method takes one lock, so interfaces that serve several people at once (Telegram,
web) can call it from any thread. A slow model answer for one person makes the others wait.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wali.agent.dialogue import is_correction
from wali.agent.llm import AnthropicLLM, LLMClient, LLMError
from wali.agent.llm_openai import OpenAICompatibleLLM
from wali.agent.loop import Agent, AgentReply, Session
from wali.agent.prompts import SENTINEL_PROMPT, build_system_prompt, protected_texts
from wali.config import Settings
from wali.finance.reconcile import ReconcileConfig
from wali.guard.audit import AuditLog
from wali.guard.keys import public_key_of
from wali.guard.sentinel import Sentinel
from wali.guard.service import (
    ConfirmationRequest,
    GuardService,
    MandateDecision,
    PaymentDecision,
)
from wali.guard.store import GuardStore
from wali.models import Principal
from wali.tools.base import FinancialEnvironment
from wali.tools.registry import ToolRegistry
from wali.tools.sim_env import SimEnvironment


class SetupError(RuntimeError):
    """The application cannot start as configured. The message says what to do."""


@dataclass(frozen=True)
class ChatResult:
    reply: AgentReply
    # Confirmation requests created by this message, for the interface to show to whoever
    # may confirm them. They are also kept in the inbox.
    new_confirmations: tuple[ConfirmationRequest, ...] = ()


@dataclass
class WaliApp:
    env: FinancialEnvironment
    guard: GuardService
    llm: LLMClient
    business_id: str
    currency: str
    clock: Callable[[], dt.datetime]
    max_steps: int = 8
    history_max_turns: int = 30
    reconcile_config: ReconcileConfig = field(default_factory=ReconcileConfig)
    # See Settings.sentinel_strict_turn.
    strict_turn: bool = False
    # Whether the sentinel's model layer is on, for an interface to show.
    sentinel_model_enabled: bool = False
    _sessions: dict[tuple[str, str], Session] = field(default_factory=dict, repr=False)
    _inbox: list[ConfirmationRequest] = field(default_factory=list, repr=False)
    _session_counter: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        self._agent = Agent(
            self.llm,
            max_steps=self.max_steps,
            history_max_turns=self.history_max_turns,
            screen_outgoing=self._screen_reply,
        )

    def _screen_reply(self, text: str, session: Session) -> str:
        return self.guard.screen_outgoing(
            text, session.principal, session_id=session.session_id
        ).text

    def today(self) -> dt.date:
        return self.clock().date()

    # --- Chat ----------------------------------------------------------------------------

    def _session(self, principal: Principal, channel: str) -> Session:
        key = (channel, principal.user_id)
        session = self._sessions.get(key)
        if session is None or session.principal != principal:
            self._session_counter += 1
            session = Session(
                session_id=f"{channel}:{principal.user_id}:{self._session_counter}",
                principal=principal,
                system_prompt=build_system_prompt(
                    role=principal.role, currency=self.currency, today=self.today()
                ),
            )
            self._sessions[key] = session
        return session

    def chat(self, principal: Principal, text: str, *, channel: str = "cli") -> ChatResult:
        """Answer one message from an authenticated principal."""
        with self._lock:
            return self._chat(principal, text, channel)

    def _chat(self, principal: Principal, text: str, channel: str) -> ChatResult:
        session = self._session(principal, channel)
        session.pending_proposals[:] = [
            p for p in session.pending_proposals if self.guard.is_pending(p["proposal_id"])
        ]
        # The message itself may carry pasted text that tries to steer the assistant. It
        # cannot be withheld, so instead every payment proposed in this turn waits for the owner.
        typed = self.guard.screen_untrusted(
            text,
            principal=principal,
            session_id=session.session_id,
            source="message",
            origin="user_message",
        )
        registry = ToolRegistry(
            self.env,
            self.guard,
            principal,
            today=self.today,
            session_id=session.session_id,
            reconcile_config=self.reconcile_config,
            suspicious=typed.suspicious,
            strict_turn=self.strict_turn,
            pending_proposals=session.pending_proposals,
            replace_pending=is_correction(text),
        )
        reply = self._agent.respond(session, registry, text)
        return ChatResult(reply=reply, new_confirmations=tuple(self._collect()))

    def reset(self, principal: Principal, *, channel: str = "cli") -> None:
        """Forget the conversation with this principal on this channel."""
        with self._lock:
            self._sessions.pop((channel, principal.user_id), None)

    # --- Confirmation inbox --------------------------------------------------------------

    def _collect(self) -> list[ConfirmationRequest]:
        new = self.guard.collect_confirmation_requests()
        self._inbox.extend(new)
        return new

    def pending(self, principal: Principal) -> list[ConfirmationRequest]:
        """Requests this principal may confirm right now, oldest first."""
        with self._lock:
            return self._pending(principal)

    def _pending(self, principal: Principal) -> list[ConfirmationRequest]:
        self._collect()
        now = self.clock()
        self._inbox = [
            request
            for request in self._inbox
            if request.expires_at > now and self.guard.is_pending(request.subject_id)
        ]
        return [
            request
            for request in self._inbox
            if request.required_role == principal.role
            and request.business_id == principal.business_id
        ]

    def _take(
        self, principal: Principal, number: int, subject_id: str | None
    ) -> ConfirmationRequest | None:
        waiting = self._pending(principal)
        if subject_id is not None:
            request = next((r for r in waiting if r.subject_id == subject_id), None)
        else:
            request = waiting[number - 1] if 1 <= number <= len(waiting) else None
        if request is not None:
            self._inbox.remove(request)
        return request

    def confirm(
        self,
        principal: Principal,
        number: int = 1,
        *,
        channel: str = "cli",
        subject_id: str | None = None,
    ) -> PaymentDecision | MandateDecision | None:
        """Confirm the request shown to this principal as item ``number``, or the one for
        ``subject_id`` (the proposal or draft id an interface put on a button). Returns None
        when there is no such request for this principal. The guard still checks the
        principal and the token."""
        with self._lock:
            request = self._take(principal, number, subject_id)
            if request is None:
                return None
            session_id = self._session(principal, channel).session_id
            if request.kind == "payment":
                decision = self.guard.confirm_payment(
                    principal, request.token, session_id=session_id
                )
            else:
                decision = self.guard.confirm_mandate(
                    principal, request.token, session_id=session_id
                )
            self._collect()
            return decision

    def cancel(
        self,
        principal: Principal,
        number: int = 1,
        *,
        channel: str = "cli",
        subject_id: str | None = None,
    ) -> bool:
        """Decline the request shown to this principal as item ``number``, or the one for
        ``subject_id``."""
        with self._lock:
            request = self._take(principal, number, subject_id)
            if request is None:
                return False
            session_id = self._session(principal, channel).session_id
            return self.guard.cancel_confirmation(
                principal, request.token, request.kind, session_id=session_id
            )


def simulated_clock(today: dt.date, tz: dt.tzinfo) -> Callable[[], dt.datetime]:
    """A clock that says it is ``today`` at the real time of day, and then runs at real speed.
    It keeps the seeded scenario coherent whenever the demo is run."""
    started = dt.datetime.now(tz)
    offset = dt.datetime.combine(today, started.timetz()) - started
    return lambda: dt.datetime.now(tz) + offset


def build_llm(settings: Settings, model: str | None) -> LLMClient:
    """The model client for the configured provider. Raises ``SetupError`` when a setting it
    needs is missing."""
    if not model:
        raise SetupError("No model is configured. Set WALI_AGENT_MODEL in the .env file.")
    try:
        if settings.llm_provider == "openai_compatible":
            key = settings.llm_api_key
            return OpenAICompatibleLLM(
                model=model,
                base_url=settings.llm_base_url or "",
                api_key=key.get_secret_value() if key else "",
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
                timeout_seconds=settings.llm_timeout_seconds,
            )
        key = settings.anthropic_api_key
        return AnthropicLLM(
            model=model,
            api_key=key.get_secret_value() if key else None,
            base_url=settings.llm_base_url,
            max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort,
            refusal_fallback=settings.llm_refusal_fallback,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    except LLMError as error:
        raise SetupError(error.user_message) from None


SENTINEL_MAX_TOKENS = 4000


def build_app(
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    sentinel_llm: LLMClient | None = None,
) -> WaliApp:
    """Build the application from settings. Raises ``SetupError`` with a plain instruction when
    something needed is missing.

    The sentinel's model layer is on when ``WALI_SENTINEL_MODEL`` is set (or ``sentinel_llm`` is
    given). Without it the sentinel still runs its built-in rules."""
    if settings.guard_private_key is None:
        raise SetupError(
            "No guard key is configured. Run: uv run python scripts/gen_guard_key.py --write-env"
        )
    private_key = settings.guard_private_key.get_secret_value()
    public_key = public_key_of(private_key)

    if settings.environment == "organiser":
        raise SetupError(
            "The organisers' environment is not implemented yet (docs/assumptions.md, U1). "
            "Set WALI_ENVIRONMENT=sim."
        )

    db_path = Path(settings.db_path)
    options = {"fail_rate": settings.sim_fail_rate, "seed": settings.sim_seed}
    if db_path.is_file():
        env = SimEnvironment.open(db_path, public_key, **options)
    else:
        if not Path(settings.seed_dir).is_dir():
            raise SetupError(
                f"Seed data not found in {settings.seed_dir}. "
                "Run: uv run python scripts/gen_seed_data.py"
            )
        env = SimEnvironment.create(settings.seed_dir, public_key, db_path=db_path, **options)
    today = settings.sim_today or env.as_of_date + dt.timedelta(days=1)
    business_id, currency = env.business_id, env.currency
    clock = simulated_clock(today, settings.tz)
    env.use_clock(clock)
    if sentinel_llm is None and settings.sentinel_model:
        capped = min(settings.llm_max_tokens, SENTINEL_MAX_TOKENS)
        sentinel_llm = build_llm(
            settings.model_copy(update={"llm_max_tokens": capped}), settings.sentinel_model
        )
    sentinel = Sentinel(sentinel_llm, prompt=SENTINEL_PROMPT)
    api_keys = (settings.anthropic_api_key, settings.llm_api_key, settings.telegram_bot_token)
    guard = GuardService(
        env,
        private_key,
        AuditLog(settings.audit_log_path),
        business_id=business_id,
        currency=currency,
        store=GuardStore(settings.guard_db_path),
        clock=clock,
        confirm_ttl_seconds=settings.confirm_token_ttl_seconds,
        proposals_per_hour=settings.proposals_per_hour,
        sentinel=sentinel,
        secrets=[key.get_secret_value() for key in api_keys if key is not None],
        protected_texts=protected_texts(),
    )
    if llm is None:
        llm = build_llm(settings, settings.agent_model)
    return WaliApp(
        env=env,
        guard=guard,
        llm=llm,
        business_id=business_id,
        currency=currency,
        clock=clock,
        max_steps=settings.agent_max_steps,
        history_max_turns=settings.history_max_turns,
        reconcile_config=ReconcileConfig.from_settings(settings),
        strict_turn=settings.sentinel_strict_turn,
        sentinel_model_enabled=sentinel.model_enabled,
    )
