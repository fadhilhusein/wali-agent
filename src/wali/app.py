"""Wiring shared by every interface (CLI, Telegram, web).

``WaliApp`` owns the pieces and the two things an interface needs:

- ``chat``: hand a message from an authenticated principal to the agent;
- ``pending`` / ``confirm`` / ``cancel``: the confirmation inbox. Confirmation tokens live here,
  between the guard and the interface, and never pass through the model.

The principal given to these methods must come from the interface's own authentication. Nothing
typed in a chat can change it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wali.agent.llm import AnthropicLLM, LLMClient
from wali.agent.loop import Agent, AgentReply, Session
from wali.agent.prompts import build_system_prompt
from wali.config import Settings
from wali.finance.reconcile import ReconcileConfig
from wali.guard.audit import AuditLog
from wali.guard.keys import public_key_of
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
    _sessions: dict[tuple[str, str], Session] = field(default_factory=dict, repr=False)
    _inbox: list[ConfirmationRequest] = field(default_factory=list, repr=False)
    _session_counter: int = 0

    def __post_init__(self) -> None:
        self._agent = Agent(
            self.llm, max_steps=self.max_steps, history_max_turns=self.history_max_turns
        )

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
        session = self._session(principal, channel)
        registry = ToolRegistry(
            self.env,
            self.guard,
            principal,
            today=self.today,
            session_id=session.session_id,
            reconcile_config=self.reconcile_config,
        )
        reply = self._agent.respond(session, registry, text)
        return ChatResult(reply=reply, new_confirmations=tuple(self._collect()))

    def reset(self, principal: Principal, *, channel: str = "cli") -> None:
        """Forget the conversation with this principal on this channel."""
        self._sessions.pop((channel, principal.user_id), None)

    # --- Confirmation inbox --------------------------------------------------------------

    def _collect(self) -> list[ConfirmationRequest]:
        new = self.guard.collect_confirmation_requests()
        self._inbox.extend(new)
        return new

    def pending(self, principal: Principal) -> list[ConfirmationRequest]:
        """Requests this principal may confirm right now, oldest first."""
        self._collect()
        now = self.clock()
        self._inbox = [request for request in self._inbox if request.expires_at > now]
        return [
            request
            for request in self._inbox
            if request.required_role == principal.role
            and request.business_id == principal.business_id
        ]

    def _take(self, principal: Principal, number: int) -> ConfirmationRequest | None:
        waiting = self.pending(principal)
        if not 1 <= number <= len(waiting):
            return None
        request = waiting[number - 1]
        self._inbox.remove(request)
        return request

    def confirm(
        self, principal: Principal, number: int = 1, *, channel: str = "cli"
    ) -> PaymentDecision | MandateDecision | None:
        """Confirm the request shown to this principal as item ``number``. Returns None when
        there is no such request. The guard still checks the principal and the token."""
        request = self._take(principal, number)
        if request is None:
            return None
        session_id = self._session(principal, channel).session_id
        if request.kind == "payment":
            decision = self.guard.confirm_payment(principal, request.token, session_id=session_id)
        else:
            decision = self.guard.confirm_mandate(principal, request.token, session_id=session_id)
        self._collect()
        return decision

    def cancel(self, principal: Principal, number: int = 1, *, channel: str = "cli") -> bool:
        """Decline the request shown to this principal as item ``number``."""
        request = self._take(principal, number)
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


def build_app(settings: Settings, *, llm: LLMClient | None = None) -> WaliApp:
    """Build the application from settings. Raises ``SetupError`` with a plain instruction when
    something needed is missing."""
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
    )
    if llm is None:
        if not settings.agent_model:
            raise SetupError("No model is configured. Set WALI_AGENT_MODEL in the .env file.")
        api_key = settings.anthropic_api_key
        llm = AnthropicLLM(
            model=settings.agent_model,
            api_key=api_key.get_secret_value() if api_key else None,
            base_url=settings.llm_base_url,
            max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort,
            refusal_fallback=settings.llm_refusal_fallback,
            timeout_seconds=settings.llm_timeout_seconds,
        )
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
    )
