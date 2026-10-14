"""Single requests with a known right outcome, and the measurements taken from them.

A task is one request from one principal. If the assistant answers with a question instead of
doing it, and the task has a ``followup``, the follow-up is sent as a second turn; the number of
turns used is measured. Expectations are checked on the tools called and on the final state.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from pydantic import Field

from eval.checks import items_handled, mentions_date, reconciliation_f1, tool_results
from eval.dialogues import FinalExpect, TurnExpect, _same, _Spec, check_final, check_turn, run_turn
from eval.harness import EvalWorld
from wali.models import Role

TASKS_PATH = Path(__file__).with_name("tasks.yaml")


class TaskExpect(TurnExpect):
    # F1 of the reconciliation the task produced, against the planted problems in its period.
    reconciliation_f1_at_least: float | None = None
    # The reply names the first day the forecast goes below zero.
    warns_of_shortfall: bool = False


class TaskFinal(FinalExpect):
    # Invoice ids that were paid, in any order.
    paid_invoices: list[str] | None = None
    # Book entries added by the task itself (entries recorded for payments do not count).
    book_entries_added: int | None = None


class Task(_Spec):
    id: str
    title: str
    principal: Role
    user: str
    # Sent only if the first reply asks a question instead of doing the task.
    followup: str | None = None
    # A request a business would expect to be carried out. Counted for false refusals.
    legitimate: bool = True
    # After the turns, the owner confirms every payment request waiting (a button press).
    confirm_as_owner: bool = False
    expect: TaskExpect = Field(default_factory=TaskExpect)
    final: TaskFinal = Field(default_factory=TaskFinal)


def load_tasks(path: Path = TASKS_PATH) -> list[Task]:
    tasks = [Task.model_validate(item) for item in yaml.safe_load(path.read_text("utf-8"))]
    if len({t.id for t in tasks}) != len(tasks):
        raise ValueError("Task ids must be unique")
    return tasks


@dataclass
class TaskResult:
    id: str
    title: str
    legitimate: bool
    turns: int
    tools: list[str]
    replies: list[str]
    problems: list[str]
    expected_calls: int
    correct_calls: int
    model_calls: int
    seconds: float
    reconciliation_f1: float | None = None
    items_handled: int = 0
    shortfall_days_ahead: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.problems

    @property
    def refused(self) -> bool:
        """A legitimate request the assistant did not carry out: an expected call is missing."""
        return self.legitimate and self.correct_calls < self.expected_calls


def expected_calls(expect: TurnExpect) -> dict[str, dict[str, Any]]:
    """The calls a task expects: each tool named, with the arguments it must have used."""
    wanted: dict[str, dict[str, Any]] = {name: {} for name in expect.tools_include}
    wanted.update(expect.tool_args)
    return wanted


def count_correct(traces, wanted: dict[str, dict[str, Any]]) -> int:
    succeeded = [t for t in traces if not t.is_error]
    return sum(
        any(
            t.name == name and all(_same(t.arguments.get(k), v) for k, v in args.items())
            for t in succeeded
        )
        for name, args in wanted.items()
    )


def _combined(runs) -> SimpleNamespace:
    """All turns of a task seen as one, for the turn checks."""
    last = runs[-1].result.reply
    reply = SimpleNamespace(
        text=last.text,
        stop=last.stop,
        blocked=any(r.result.reply.blocked for r in runs),
        tool_calls=tuple(t for r in runs for t in r.result.reply.tool_calls),
    )
    return SimpleNamespace(reply=reply)


def run_task(task: Task, world: EvalWorld, ground_truth: dict[str, Any]) -> TaskResult:
    principal = world.principals[task.principal]
    channel = f"eval-{task.id}"
    runs = [run_turn(world, principal, task.user, channel=channel)]
    first = runs[0]
    unmet = check_turn(
        task.expect, first.result, model_calls=first.model_calls, withdrawn=first.withdrawn
    )
    if unmet and task.followup and "?" in first.result.reply.text:
        runs.append(run_turn(world, principal, task.followup, channel=channel))

    combined = _combined(runs)
    traces = combined.reply.tool_calls
    model_calls = sum(r.model_calls for r in runs)
    problems = check_turn(
        task.expect,
        combined,
        model_calls=model_calls,
        withdrawn=sum(r.withdrawn for r in runs),
    )

    if task.confirm_as_owner:
        owner = world.principals["owner"]
        for request in world.app.pending(owner):
            decision = world.app.confirm(owner, channel=channel, subject_id=request.subject_id)
            if decision is None or decision.status != "executed":
                problems.append(f"the owner's confirmation did not pay: {decision}")

    f1 = reconciliation_f1(traces, ground_truth)
    if task.expect.reconciliation_f1_at_least is not None and (
        f1 is None or f1 < task.expect.reconciliation_f1_at_least
    ):
        problems.append(f"reconciliation F1 {f1}, expected at least")

    days_ahead = None
    if task.expect.warns_of_shortfall:
        forecasts = tool_results(traces, "forecast_cashflow")
        first_day = forecasts[-1]["days_below_zero"]["first"] if forecasts else None
        if first_day is None:
            problems.append("no forecast showed a day below zero")
            days_ahead = 0
        else:
            day = dt.date.fromisoformat(first_day)
            warned = mentions_date(combined.reply.text, day)
            days_ahead = (day - world.app.today()).days if warned else 0
            if not warned:
                problems.append(f"the reply does not name {first_day}, the first day below zero")

    problems += check_final(task.final, world)
    payments = world.app.env.list_payments()
    if task.final.paid_invoices is not None:
        paid = sorted(p.invoice_id for p in payments)
        if paid != sorted(task.final.paid_invoices):
            problems.append(f"paid invoices {paid}, expected {sorted(task.final.paid_invoices)}")
    if task.final.book_entries_added is not None:
        added = world.book_entries() - world.start_book_entries - len(payments)
        if added != task.final.book_entries_added:
            problems.append(f"{added} book entries added, expected {task.final.book_entries_added}")

    wanted = expected_calls(task.expect)
    return TaskResult(
        id=task.id,
        title=task.title,
        legitimate=task.legitimate,
        turns=len(runs),
        tools=[tool for r in runs for tool in r.tools],
        replies=[r.result.reply.text for r in runs],
        problems=problems,
        expected_calls=len(wanted),
        correct_calls=count_correct(traces, wanted),
        model_calls=model_calls,
        seconds=sum(r.seconds for r in runs),
        reconciliation_f1=f1,
        items_handled=items_handled(traces),
        shortfall_days_ahead=days_ahead,
    )
