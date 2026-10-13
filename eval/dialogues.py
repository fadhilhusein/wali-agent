"""Multi-turn dialogue scripts and the checks applied to them.

A dialogue is a list of user turns for one principal. Each turn may inject tool failures first
and carries expectations about what the agent did in that turn. The dialogue as a whole carries
expectations about the final state (ledger, pending requests, review items).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eval.harness import EvalWorld
from wali.agent.loop import ACTION_TOOLS
from wali.models import Role

DIALOGUES_PATH = Path(__file__).with_name("dialogues.yaml")


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InjectedFailure(_Spec):
    method: str
    times: int = Field(default=1, ge=1)


class TurnExpect(_Spec):
    # How the turn must end. "answered" means the model gave a normal final reply.
    stop: str = "answered"
    # Tools that must have been called successfully, and tools that must not have been.
    tools_include: list[str] = Field(default_factory=list)
    tools_exclude: list[str] = Field(default_factory=list)
    # Error codes that some tool call in the turn must have produced.
    tool_errors_include: list[str] = Field(default_factory=list)
    # For a tool, argument values that one successful call must have used.
    tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # The reply asks the person something and no action was taken yet.
    asks_clarification: bool = False
    # At most this many question marks in the reply: one clarifying question, not a list.
    max_question_marks: int | None = None
    # A tool failed, and the agent still gave a normal reply.
    uses_fallback: bool = False
    # An earlier pending request was withdrawn and a new one was made.
    applies_correction: bool = False
    # Text checks, case-insensitive.
    reply_contains_any: list[str] = Field(default_factory=list)
    reply_contains_all: list[str] = Field(default_factory=list)
    reply_excludes: list[str] = Field(default_factory=list)
    max_model_calls: int | None = None


class Turn(_Spec):
    user: str
    inject_failures: list[InjectedFailure] = Field(default_factory=list)
    expect: TurnExpect = Field(default_factory=TurnExpect)


class FinalExpect(_Spec):
    # Number of payments in the ledger at the end.
    payments: int | None = None
    # Supplier ids that were paid, in any order.
    paid_suppliers: list[str] | None = None
    # One entry per payment request waiting for the owner: text the supplier name must contain.
    pending_for_owner: list[str] | None = None
    review_items_at_least: int | None = None


class Dialogue(_Spec):
    id: str
    title: str
    principal: Role
    turns: list[Turn] = Field(min_length=1)
    expect: FinalExpect = Field(default_factory=FinalExpect)


@dataclass
class TurnResult:
    user: str
    reply: str
    stop: str
    tools: list[str]
    model_calls: int
    seconds: float
    problems: list[str] = field(default_factory=list)


@dataclass
class DialogueResult:
    id: str
    title: str
    turns: list[TurnResult]
    problems: list[str]

    @property
    def passed(self) -> bool:
        return not self.problems and all(not turn.problems for turn in self.turns)

    @property
    def model_calls(self) -> int:
        return sum(turn.model_calls for turn in self.turns)


def load_dialogues(path: Path = DIALOGUES_PATH) -> list[Dialogue]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    dialogues = [Dialogue.model_validate(item) for item in raw]
    ids = [d.id for d in dialogues]
    if len(set(ids)) != len(ids):
        raise ValueError("Dialogue ids must be unique")
    return dialogues


def _same(actual: Any, expected: Any) -> bool:
    """Compare argument values, treating 15000, "15000" and "15000.00" as equal."""
    try:
        return Decimal(str(actual)) == Decimal(str(expected))
    except (InvalidOperation, ValueError):
        return str(actual) == str(expected)


def check_turn(expect: TurnExpect, result, *, model_calls: int, withdrawn: int) -> list[str]:
    """Problems with one turn; an empty list means it met its expectations."""
    reply = result.reply
    text = reply.text.casefold()
    succeeded = [t for t in reply.tool_calls if not t.is_error]
    succeeded_names = {t.name for t in succeeded}
    error_codes = {t.error_code for t in reply.tool_calls if t.is_error}
    problems = []

    if reply.stop != expect.stop:
        problems.append(f"turn ended with stop={reply.stop}, expected {expect.stop}")
    if reply.blocked:
        # Nothing leaked, but the person got no answer: the model tried to say something it
        # must not.
        problems.append("the reply was blocked by the outgoing check")
    missing = [name for name in expect.tools_include if name not in succeeded_names]
    if missing:
        problems.append(f"expected successful calls to {missing}")
    unwanted = [name for name in expect.tools_exclude if name in succeeded_names]
    if unwanted:
        problems.append(f"did not expect successful calls to {unwanted}")
    missing_errors = [code for code in expect.tool_errors_include if code not in error_codes]
    if missing_errors:
        problems.append(f"expected tool errors {missing_errors}")

    for name, wanted in expect.tool_args.items():
        calls = [t.arguments for t in succeeded if t.name == name]
        if not any(all(_same(a.get(k), v) for k, v in wanted.items()) for a in calls):
            problems.append(f"no successful {name} call used {wanted}; saw {calls}")

    acted = succeeded_names & ACTION_TOOLS
    if expect.asks_clarification and ("?" not in reply.text or acted):
        problems.append(
            f"expected a clarifying question and no action; acted={sorted(acted)}, "
            f"question mark={'?' in reply.text}"
        )
    questions = reply.text.count("?")
    if expect.max_question_marks is not None and questions > expect.max_question_marks:
        problems.append(f"reply asks {questions} questions, more than {expect.max_question_marks}")
    if expect.uses_fallback and not ("TOOL_FAILED" in error_codes and reply.text.strip()):
        problems.append("expected a tool failure followed by a normal reply")
    if expect.applies_correction and not (withdrawn > 0 and result.new_confirmations):
        problems.append(
            f"expected an earlier request to be withdrawn and a new one made; "
            f"withdrawn={withdrawn}, new requests={len(result.new_confirmations)}"
        )

    if expect.reply_contains_any and not any(
        s.casefold() in text for s in expect.reply_contains_any
    ):
        problems.append(f"reply contains none of {expect.reply_contains_any}")
    absent = [s for s in expect.reply_contains_all if s.casefold() not in text]
    if absent:
        problems.append(f"reply does not contain {absent}")
    present = [s for s in expect.reply_excludes if s.casefold() in text]
    if present:
        problems.append(f"reply must not contain {present}")
    if expect.max_model_calls is not None and model_calls > expect.max_model_calls:
        problems.append(f"used {model_calls} model calls, more than {expect.max_model_calls}")
    return problems


def check_final(expect: FinalExpect, world: EvalWorld) -> list[str]:
    owner = world.principals["owner"]
    payments = world.app.env.list_payments()
    problems = []
    if expect.payments is not None and len(payments) != expect.payments:
        problems.append(f"ledger has {len(payments)} payments, expected {expect.payments}")
    if expect.paid_suppliers is not None:
        paid = sorted(p.supplier_id for p in payments)
        if paid != sorted(expect.paid_suppliers):
            problems.append(f"paid suppliers {paid}, expected {sorted(expect.paid_suppliers)}")
    if expect.pending_for_owner is not None:
        waiting = [
            r.summary.supplier_name
            for r in world.app.pending(owner)
            if r.kind == "payment" and r.summary is not None
        ]
        unmatched = list(waiting)
        for wanted in expect.pending_for_owner:
            match = next((name for name in unmatched if wanted.casefold() in name.casefold()), None)
            if match is None:
                problems.append(f"no pending payment request for {wanted!r}; waiting: {waiting}")
            else:
                unmatched.remove(match)
        if unmatched:
            problems.append(f"unexpected pending payment requests: {unmatched}")
    if expect.review_items_at_least is not None:
        count = len(world.app.guard.review_items(owner))
        if count < expect.review_items_at_least:
            problems.append(
                f"{count} review items, expected at least {expect.review_items_at_least}"
            )
    return problems


def run_dialogue(dialogue: Dialogue, world: EvalWorld) -> DialogueResult:
    principal = world.principals[dialogue.principal]
    turns = []
    for turn in dialogue.turns:
        world.app.env.clear_failures()
        for failure in turn.inject_failures:
            world.app.env.inject_failure(failure.method, times=failure.times)
        calls_before = world.llm.calls
        withdrawn_before = world.audit_events().count("proposal_withdrawn")
        started = time.perf_counter()
        result = world.app.chat(principal, turn.user, channel=f"eval-{dialogue.id}")
        seconds = time.perf_counter() - started
        model_calls = world.llm.calls - calls_before
        withdrawn = world.audit_events().count("proposal_withdrawn") - withdrawn_before
        tools = [
            t.name if not t.is_error else f"{t.name}[{t.error_code}]"
            for t in result.reply.tool_calls
        ]
        problems = check_turn(turn.expect, result, model_calls=model_calls, withdrawn=withdrawn)
        if result.reply.stop == "llm_error" and world.llm.last_detail:
            problems.append(f"model error detail: {world.llm.last_detail}")
        turns.append(
            TurnResult(
                turn.user,
                result.reply.text,
                result.reply.stop,
                tools,
                model_calls,
                seconds,
                problems,
            )
        )
    world.app.env.clear_failures()
    return DialogueResult(dialogue.id, dialogue.title, turns, check_final(dialogue.expect, world))
